"""WebRTC 的 SDP 握手转发。

两条路目标不同（A.13 末尾）：
- `/api/calls` 转到**环境变量钉死的** `SPEECH_TO_SPEECH_URL`。接受客户端传目标就
  等于开放代理（SSRF），所以目标只能来自 env。
- `/v1/realtime/calls` 转到回环的 pipeline：`8765` 不 publish，浏览器需要一条同源
  入口（demo 阶段是浏览器直连 8765）。
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import HTTPException, Response
from loguru import logger

from app.config import console


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


async def _http(url: str, offer: bytes) -> httpx.Response:
    """单独一层：测试替换点。超时给得宽松——pipeline 要等自己的 ICE 收集（~5 s）。"""
    async with httpx.AsyncClient(timeout=15.0) as client:
        return await client.post(url, headers={"Content-Type": "application/sdp"}, content=offer)


async def forward(url: str, offer: bytes, *, keep_location: bool) -> Response:
    """把 SDP offer 打给 upstream，把 answer（或错误体）原样转回。"""
    try:
        upstream = await _http(url, offer)
    except httpx.HTTPError as exc:
        logger.warning("sdp handshake unreachable: {}", exc)
        raise HTTPException(status_code=502, detail="Speech service unreachable.") from exc

    headers = {}
    if keep_location and "location" in upstream.headers:
        headers["Location"] = upstream.headers["location"]
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/sdp"),
        headers=headers,
    )
