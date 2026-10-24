"""`/v1/realtime*`：浏览器进入回环 8765 的唯一通道（§10.2.3）。

只开两条路。`/v1/pool`、`/v1/usage` 是运维数据，控制台在服务端自己读，不往
公网放（§12 R4）。
"""

from __future__ import annotations

import asyncio
from contextlib import suppress

import websockets
from fastapi import APIRouter, Request, WebSocket
from loguru import logger

from app.config import console
from app.services import calls_service

router = APIRouter(tags=["realtime"])


def _upstream_url(url) -> str:
    """`http://127.0.0.1:8765` + 浏览器的 path/query → `ws://…`（https→wss）。"""
    base = console.pipeline_base_url.strip().rstrip("/")
    if "://" not in base:
        base = "http://" + base
    scheme, host = base.split("://", 1)
    query = f"?{url.query}" if url.query else ""
    return f"{'wss' if scheme == 'https' else 'ws'}://{host}{url.path}{query}"


def _subprotocols(websocket: WebSocket) -> list[str]:
    raw = websocket.headers.get("sec-websocket-protocol", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


async def _client_to_upstream(client: WebSocket, upstream) -> None:
    while True:
        message = await client.receive()
        if message["type"] == "websocket.disconnect":
            return
        if message.get("text") is not None:
            await upstream.send(message["text"])
        elif message.get("bytes") is not None:
            await upstream.send(message["bytes"])


async def _upstream_to_client(client: WebSocket, upstream) -> None:
    async for message in upstream:
        if isinstance(message, bytes):
            await client.send_bytes(message)
        else:
            await client.send_text(message)


@router.websocket("/v1/realtime")
async def realtime(websocket: WebSocket) -> None:
    """把浏览器的 Realtime WS 接到回环 pipeline。

    不改路径、不缓冲帧（缓冲会把 TTS 首字节延迟放大，§12 R20）——两边都是逐帧转发。
    一侧关闭就关另一侧，否则回环端口会积压僵尸连接。
    """
    try:
        upstream = await websockets.connect(
            _upstream_url(websocket.url),
            subprotocols=_subprotocols(websocket) or None,
            max_size=None,  # base64 音频帧可能超过默认 1 MiB
            # R20: deflate 会把帧缓冲到凑满一个块，TTS 首字节因此晚到。
            compression=None,
            open_timeout=5.0,
        )
    except Exception as exc:
        logger.warning("realtime upstream unreachable: {}", exc)
        # 还没 accept：ASGI 会把这次握手判为失败，而不是收下一个谁也服务不了的会话。
        await websocket.close(code=1013)
        return

    await websocket.accept(subprotocol=upstream.subprotocol)
    tasks = [
        asyncio.create_task(_client_to_upstream(websocket, upstream)),
        asyncio.create_task(_upstream_to_client(websocket, upstream)),
    ]
    _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    with suppress(Exception):
        await upstream.close()
    with suppress(Exception):
        await websocket.close()


@router.post("/v1/realtime/calls", include_in_schema=False)
async def realtime_calls(request: Request):
    """同源的 SDP 入口。不回填 `Location`：它指向回环，浏览器拿不到。"""
    return await calls_service.forward(
        calls_service.loopback_url(), await request.body(), keep_location=False
    )
