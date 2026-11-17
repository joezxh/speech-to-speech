"""WebRTC 的 SDP 握手转发。

三条路目标不同（A.13 末尾 / spec 2026-11-16 §5.5）：
- `/api/calls` 在 `CONSOLE_LB_MODE=off` 时转到**环境变量钉死的**
  `SPEECH_TO_SPEECH_URL`。接受客户端传目标就等于开放代理（SSRF），所以目标只能
  来自 env。
- `/api/calls` 在 `CONSOLE_LB_MODE=proxy` 时由 console **按注册表选台**决定目标
  ——目标仍然只来自服务端，不是开放代理。
- `/v1/realtime/calls` 转到回环的 pipeline：`8765` 不 publish，浏览器需要一条同源
  入口（demo 阶段是浏览器直连 8765）。

WebRTC 满员时上游回 503 + `session_limit_reached`（HTTP 层，可识别），所以换台
是可能的；501（没装 webrtc extra）不换台，直接透传。
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import HTTPException, Response
from loguru import logger

from app.config import console
from app.services import allocator, upstream_resolver


def handshake_url(realtime_url: str) -> str:
    """`ws://host:port/v1/realtime` → `http://host:port/v1/realtime/calls`。

    ws→http、wss→https；只有主机名时补默认的 `/v1/realtime` 路径（与客户端的
    `buildDirectWsUrl` 规整方式一致）。"""
    raw = realtime_url.strip()
    if not raw.startswith(("ws://", "wss://", "http://", "https://")):
        raw = "http://" + raw
    parts = urlsplit(raw)
    scheme = {"ws": "http", "wss": "https"}.get(parts.scheme, parts.scheme)
    path = parts.path if parts.path not in ("", "/") else "/v1/realtime"
    return urlunsplit((scheme, parts.netloc, path.rstrip("/") + "/calls", parts.query, ""))


def loopback_url() -> str:
    return handshake_url(console.pipeline_base_url)


async def _http(url: str, offer: bytes, *, timeout: float = 15.0) -> httpx.Response:
    """单独一层：测试替换点。超时给得宽松——pipeline 要等自己的 ICE 收集（~5 s）。

    `timeout` 是 keyword-only 且有默认值：既有的测试替身是 `fake(url, offer)`
    （两个位置参数），非 proxy 路径必须仍然这么调用，否则替身会 TypeError。
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.post(url, headers={"Content-Type": "application/sdp"}, content=offer)


def handshake_url_for(base_url: str) -> str:
    """实例基址 → 它的 SDP 入口。"""
    return handshake_url(base_url)


def is_full_response(response: httpx.Response) -> bool:
    """上游说"我满了"（503 + session_limit_reached）：该换一台。"""
    if response.status_code != 503:
        return False
    try:
        payload = json.loads(response.content)
    except (TypeError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    error = payload.get("error")
    if isinstance(error, dict):
        return error.get("type") == "session_limit_reached"
    return payload.get("type") == "session_limit_reached"


def _to_response(upstream: httpx.Response, *, keep_location: bool) -> Response:
    headers = {}
    if keep_location and "location" in upstream.headers:
        headers["Location"] = upstream.headers["location"]
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/sdp"),
        headers=headers,
    )


async def forward_selected(offer: bytes, *, keep_location: bool, request=None) -> Response:
    """proxy 模式：选台 → 转发 offer → 上游满员就换台（spec §5.5）。

    目标由服务端决定（注册表），不是客户端传的，所以不构成开放代理。
    request（Task 17 接线）：有票据/tenant_tag 时按 RoutingEngine 决策选台；
    无票据且规则表为空 → routing=None，与改前逐字一致。
    """
    from app.services.routing_service import (  # noqa: PLC0415
        RoutingEngine,
        context_from_ticket,
        drop_sticky,
        sticky_key,
    )

    decision = None
    context = None
    if request is not None:
        try:
            from app.db.database import SessionLocal  # noqa: PLC0415

            session = SessionLocal()
            try:
                query = getattr(request, "query_params", {})
                context = context_from_ticket(
                    query.get("ticket", ""),
                    session_key=query.get("session_key") or "sdp",
                    tenant_tag=query.get("tenant_tag", ""),
                )
                decision = RoutingEngine(session).resolve(context)
            finally:
                session.close()
        except Exception:  # noqa: BLE001 - 路由是增强，不阻断 SDP 握手
            decision, context = None, None

    tried: set[str] = set()
    last: httpx.Response | None = None
    timeout = console.lb_upstream_ready_timeout_s + 10.0
    for _attempt in range(console.lb_failover_attempts + 1):
        ranked = upstream_resolver.rank_session(
            store=allocator.store,
            capability="realtime",
            exclude=frozenset(tried),
            rng=allocator._rng,
            routing=decision,
        )
        if not ranked:
            break
        target = ranked[0]
        tried.add(target.instance_id)
        url = handshake_url_for(target.base_url)
        try:
            last = await _http(url, offer, timeout=timeout)
        except httpx.HTTPError as exc:
            logger.warning("sdp handshake unreachable on {}: {}", target.instance_id, exc)
            continue
        if not is_full_response(last):
            break
        logger.warning("lb failover: {} is full, trying another instance", target.instance_id)
        if decision is not None and decision.sticky_hit:
            # 粘性目标满员：删亲和行 + 回落，理由 sticky_target_unavailable。
            try:
                from app.db.database import SessionLocal  # noqa: PLC0415

                session = SessionLocal()
                try:
                    drop_sticky(session, sticky_key(context) if context else decision.affinity_key)
                finally:
                    session.close()
            except Exception:  # noqa: BLE001
                pass
            decision = None
    if last is None:
        raise HTTPException(status_code=503, detail="No speech instance is available.")
    return _to_response(last, keep_location=keep_location)



async def forward(url: str, offer: bytes, *, keep_location: bool) -> Response:
    """把 SDP offer 打给 upstream，把 answer（或错误体）原样转回。"""
    try:
        upstream = await _http(url, offer)
    except httpx.HTTPError as exc:
        logger.warning("sdp handshake unreachable: {}", exc)
        raise HTTPException(status_code=502, detail="Speech service unreachable.") from exc

    return _to_response(upstream, keep_location=keep_location)
