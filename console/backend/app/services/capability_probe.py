"""能力指纹：探测每个实例上实际注册了哪些端点（spec §5.1）。

为什么需要它：同一批 pipeline 的端点集合可能不同——声纹只在
`VOICEPRINT_ENABLED=true` 时注册（voiceprint_routes.py:31-36），情感只在
`SER_ENABLED=true` 且 SER 配置齐备时注册（emotion_routes.py:44-53）。不做能力
过滤，console 会把请求发给没有该路由的机器，拿到 404，表现为"偶发功能不可用"。

判据表（每条都有测试钉住，见 tests/unit/test_capability_probe.py）：

| 能力      | 探测端点                           | 401/403 | 404 | 503 | 其它 | 超时 |
|-----------|------------------------------------|---------|-----|-----|------|------|
| realtime  | GET /v1/pool                       |  -      | 缺  |  -  | 缺   | 缺   |
| voiceprint| GET /v1/audio/embeddings/capability | 有      | 缺  | 在  | 在   | 在   |
| emotion   | GET /v1/audio/emotion/health       |  -      | 缺  |  -  | 在   | 在   |

- voiceprint 的 401/403 是"路由存在"的免费信号：VOICEPRINT_API_KEY 由调用方持有，
  console 不持有也不该持有；路由不存在时 FastAPI 直接 404，路由存在而 token 缺失
  时才 401/403。
- 503 = 路由在但没配 key（voiceprint/service.py 的 AUTH_NOT_CONFIGURED）→ 存在但不可用。
- emotion 的 /health 是同步转发 SER 的（超时 5s），所以探针超时必须比它长，否则
  "慢"会被误判成"没有这个能力"。
- asr/tts 恒注册（mount_audio_services 无条件挂载），不探测。

能力是镜像/env 的函数，会随实例重建变化，所以只驻留内存（RuntimeState），
不落库、不进 seed（spec §5.1）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

CAPABILITIES = frozenset({"realtime", "asr", "tts", "voiceprint", "emotion"})

VOICEPRINT_PATH = "/v1/audio/embeddings/capability"
EMOTION_PATH = "/v1/audio/emotion/health"
POOL_PATH = "/v1/pool"

# 无条件可用的能力：路由恒注册，handler 缺失时上游返 503，由代理层记 proxy_fail。
_ALWAYS_AVAILABLE = frozenset({"asr", "tts"})

_TIMEOUT = "timeout"
_UNREACHABLE = "unreachable"
_MISCONFIGURED = "misconfigured"
_UPSTREAM_ERROR = "upstream_error"


@dataclass(frozen=True)
class CapabilityReport:
    """一次能力探测的结论。

    available：可用于选台。
    present：路由存在（含"存在但不可用"）。
    issues：capability → 原因码（misconfigured / timeout / unreachable / upstream_error）。
    """

    available: frozenset[str] = frozenset()
    present: frozenset[str] = frozenset()
    issues: dict[str, str] = field(default_factory=dict)


async def _status(
    client: httpx.AsyncClient, base_url: str, path: str, timeout: float
) -> tuple[int | None, str]:
    """返回 (状态码, 错误类别)。状态码 None 表示超时/连不上这类传输层错误。"""
    url = base_url.rstrip("/") + path
    try:
        response = await client.get(url, timeout=timeout)
    except httpx.TimeoutException:
        return None, _TIMEOUT
    except httpx.HTTPError:
        return None, _UNREACHABLE
    return response.status_code, ""


async def probe_capabilities(
    base_url: str,
    *,
    timeout: float,
    client: httpx.AsyncClient | None = None,
) -> CapabilityReport:
    """探测单个实例的能力。绝不抛异常：探测失败只体现在结论里。"""
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=timeout)
    available: set[str] = set(_ALWAYS_AVAILABLE)
    present: set[str] = set(_ALWAYS_AVAILABLE)
    issues: dict[str, str] = {}
    try:
        await _probe_realtime(client, base_url, timeout, available, present, issues)
        await _probe_voiceprint(client, base_url, timeout, available, present, issues)
        await _probe_emotion(client, base_url, timeout, available, present, issues)
    finally:
        if owns_client:
            await client.aclose()
    return CapabilityReport(
        available=frozenset(available), present=frozenset(present), issues=issues
    )


async def _probe_realtime(
    client: httpx.AsyncClient,
    base_url: str,
    timeout: float,
    available: set[str],
    present: set[str],
    issues: dict[str, str],
) -> None:
    status, error = await _status(client, base_url, POOL_PATH, timeout)
    if status == 200:
        available.add("realtime")
        present.add("realtime")
        return
    if status is None:
        issues["realtime"] = error
        return
    if status != 404:
        issues["realtime"] = _UPSTREAM_ERROR


async def _probe_voiceprint(
    client: httpx.AsyncClient,
    base_url: str,
    timeout: float,
    available: set[str],
    present: set[str],
    issues: dict[str, str],
) -> None:
    status, error = await _status(client, base_url, VOICEPRINT_PATH, timeout)
    if status is None:
        # 连不上/超时：路由在不在都不知道，按"存在但不可用"处理，不浪费候选。
        present.add("voiceprint")
        issues["voiceprint"] = error
        return
    if status in (401, 403):
        available.add("voiceprint")
        present.add("voiceprint")
        return
    if status == 404:
        return  # 路由没注册：这个实例就是没有声纹。
    present.add("voiceprint")
    issues["voiceprint"] = _MISCONFIGURED if status == 503 else _UPSTREAM_ERROR


async def _probe_emotion(
    client: httpx.AsyncClient,
    base_url: str,
    timeout: float,
    available: set[str],
    present: set[str],
    issues: dict[str, str],
) -> None:
    status, error = await _status(client, base_url, EMOTION_PATH, timeout)
    if status is None:
        present.add("emotion")
        issues["emotion"] = error
        return
    if status == 404:
        return  # 路由没注册（SER_ENABLED=false 或 SER 配置缺失）。
    present.add("emotion")
    if 200 <= status < 300:
        available.add("emotion")
    else:
        issues["emotion"] = _UPSTREAM_ERROR


async def probe_all_capabilities(
    base_urls: list[tuple[str, str]],
    *,
    timeout: float,
    client_factory: Callable[[float], httpx.AsyncClient] | None = None,
) -> dict[str, CapabilityReport]:
    """并发探测全部实例。base_urls = [(instance_id, base_url)]。

    单台失败只影响它自己（结论里体现），不让整轮抛出去（spec §5.1）。
    """
    if not base_urls:
        return {}
    factory = client_factory or (lambda t: httpx.AsyncClient(timeout=t))
    client = factory(timeout)
    try:
        results = await asyncio.gather(
            *(
                probe_capabilities(base_url, timeout=timeout, client=client)
                for _, base_url in base_urls
            ),
            return_exceptions=True,
        )
    finally:
        await client.aclose()
    out: dict[str, CapabilityReport] = {}
    for (instance_id, _), result in zip(base_urls, results, strict=True):
        if isinstance(result, BaseException):
            # 理论上 probe_capabilities 不抛；真抛了也只让这台退化成"什么都没有"。
            out[instance_id] = CapabilityReport()
        else:
            out[instance_id] = result
    return out
