"""S2S 数据面反代（spec §5.4）。

把 ASR / TTS / 声纹 / 情感这四条独立端点收敛到 console：按注册表选台后转发，
8765 不再对外。它们不占 pipeline unit 槽位（audio_services 的 find_handlers
不 claim unit），所以用 stateless 选台策略：在途请求数少的优先。

三条硬规则（都是这类代理最常见的坑）：
1. multipart boundary 原样透传——重新拼 multipart 会让上游解析失败。
2. 响应只回 content-type + 自算 content-length——httpx 会解压响应体，但 headers
   里仍留着 content-encoding 与压缩前的 content-length，照抄会把 wav 弄坏。
3. 体积闸由代理自己把关（中间件豁免这几条路径）——413 的错误体形状必须唯一。
"""

from __future__ import annotations

import time

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response
from loguru import logger

from app.config import console
from app.services import allocator, proxy_counters, upstream_resolver

# 端点 → 服务键。路径与 pipeline 侧完全一致（附录 A）。
SERVICES: dict[str, dict] = {
    "asr": {
        "path": "/v1/audio/transcriptions",
        "method": "POST",
        "capability": "asr",
        "timeout": "lb_asr_timeout_s",
    },
    "tts": {
        "path": "/v1/audio/speech",
        "method": "POST",
        "capability": "tts",
        "timeout": "lb_tts_timeout_s",
    },
    "voiceprint": {
        "path": "/v1/audio/embeddings",
        "method": "POST",
        "capability": "voiceprint",
        "timeout": "lb_voiceprint_timeout_s",
    },
    "voiceprint_capability": {
        "path": "/v1/audio/embeddings/capability",
        "method": "GET",
        "capability": "voiceprint",
        "timeout": "lb_voiceprint_timeout_s",
    },
    "emotion": {
        "path": "/v1/audio/emotion",
        "method": "POST",
        "capability": "emotion",
        "timeout": "lb_emotion_timeout_s",
    },
    "emotion_health": {
        "path": "/v1/audio/emotion/health",
        "method": "GET",
        "capability": "emotion",
        "timeout": "lb_emotion_timeout_s",
    },
}

# 请求头白名单：content-type 必须原样透传（multipart boundary 就在里面），
# authorization 是声纹的 Bearer（调用方持有，console 只透传不校验不记录）。
PROXY_HEADER_ALLOWLIST = frozenset({"content-type", "authorization", "accept"})


def _client(timeout: float) -> httpx.AsyncClient:
    """上游客户端的替换点：测试用 MockTransport 换掉它（与 lb_service 的做法一致）。"""
    return httpx.AsyncClient(timeout=timeout)


def _error(code: str, message: str, status: int, *, retryable: bool) -> JSONResponse:
    """pipeline 风格的错误体（不是 console 的 envelope）：反代面要保持调用方不改。"""
    return JSONResponse(
        {"error": {"code": code, "message": message, "retryable": retryable}},
        status_code=status,
    )


def _timeout_for(spec: dict) -> float:
    return float(getattr(console, spec["timeout"]))


def _upstream_url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + path


async def forward(service: str, request: Request) -> Response:
    """把一条 S2S 端点请求转发到选中的实例。"""
    spec = SERVICES[service]
    if console.lb_mode != "proxy":
        return _error(
            "lb_disabled",
            "the console is not in load-balancing mode",
            501,
            retryable=False,
        )

    ranked = upstream_resolver.rank_stateless(
        store=allocator.store,
        capability=spec["capability"],
        rng=allocator._rng,
    )
    if not ranked:
        return _error(
            "no_available_instance",
            "no speech instance matches this request",
            503,
            retryable=True,
        )
    target = ranked[0]

    # 先看 content-length：超限直接拒，不读 body、不向上游发任何字节。
    limit = console.lb_audio_max_bytes
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        return _error(
            "request_too_large",
            f"request body exceeds {limit} bytes",
            413,
            retryable=False,
        )
    body = await request.body()
    if len(body) > limit:
        # 只兜 chunked 请求（没有 content-length）：这类请求的 body 先进内存。
        return _error(
            "request_too_large",
            f"request body exceeds {limit} bytes",
            413,
            retryable=False,
        )

    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() in PROXY_HEADER_ALLOWLIST
    }
    url = _upstream_url(target.base_url, spec["path"])
    started = time.monotonic()
    upstream_resolver.inflight_enter(target.instance_id)
    try:
        async with _client(_timeout_for(spec)) as client:
            response = await client.request(
                spec["method"], url, content=body, headers=headers
            )
    except httpx.TimeoutException:
        logger.warning(
            "lb route path={} upstream={} status=timeout", spec["path"], target.instance_id
        )
        proxy_counters.bump(
            target.instance_id,
            spec["capability"],
            ok=False,
            fail_reason="upstream_timeout",
        )
        return _error(
            "upstream_timeout", "the speech instance timed out", 504, retryable=True
        )
    except httpx.HTTPError as exc:
        logger.warning(
            "lb route path={} upstream={} status=unreachable error={}",
            spec["path"],
            target.instance_id,
            exc,
        )
        proxy_counters.bump(
            target.instance_id,
            spec["capability"],
            ok=False,
            fail_reason="upstream_unreachable",
        )
        return _error(
            "upstream_unreachable",
            "the speech instance is unreachable",
            502,
            retryable=True,
        )
    finally:
        upstream_resolver.inflight_exit(target.instance_id)

    elapsed_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "lb route path={} upstream={} status={} ms={}",
        spec["path"],
        target.instance_id,
        response.status_code,
        elapsed_ms,
    )
    proxy_counters.bump(
        target.instance_id,
        spec["capability"],
        ok=response.status_code < 400,
        fail_reason="" if response.status_code < 400 else "upstream_error",
        duration_ms=elapsed_ms,
    )
    # 只回 content-type 与自算的 content-length：上游的 content-encoding 与
    # 压缩前的 content-length 会把已解压的 body 弄坏（wav 尤其明显）。
    out_headers: dict[str, str] = {}
    content_type = response.headers.get("content-type")
    if content_type:
        out_headers["content-type"] = content_type
    out_headers["content-length"] = str(len(response.content))
    return Response(
        content=response.content, status_code=response.status_code, headers=out_headers
    )
