"""LiveKit worker 实时转写 SSE 流（spec §7.1 修订版）。

订阅进程内 TranscriptEventBus，把转写事件以 SSE data 行推给前端。
- worker 与 console 同进程（--with-console 内嵌）时有事件流；
- standalone console 部署时 livekit_worker 不可导入 → 首帧 error 事件。
鉴权：JWT（require_permission("console:callback:query")）；前端用 fetch 流式
读取并携带 Authorization 头（EventSource 无法自定义头）。
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.permissions import require_permission
from app.core.security import CurrentUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/live-transcripts", tags=["live-transcripts"])

QUEUE_MAXSIZE = 200
KEEPALIVE_SECONDS = 15.0


@router.get("/stream")
async def stream_live_transcripts(
    user: CurrentUser = Depends(require_permission("console:callback:query")),
) -> StreamingResponse:
    """SSE：每条转写事件一行 data JSON；15s 无事件发 keep-alive 注释行。"""

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        try:
            from speech_to_speech.livekit_worker.events import get_event_bus

            bus = get_event_bus()
        except Exception as exc:  # noqa: BLE001 - worker 不在本进程 / extra 未安装
            detail = json.dumps({"detail": f"livekit worker not in this process: {exc}"},
                                ensure_ascii=False)
            yield f"event: error\ndata: {detail}\n\n"
            return
        loop = asyncio.get_running_loop()

        def on_event(event) -> None:  # noqa: ANN001 - worker 线程回调 → 转投 asyncio 队列
            def _put() -> None:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    # 队列满（消费端卡死/积压）时静默丢新事件，只在 debug 级留痕，
                    # 避免回调在事件循环内抛 QueueFull 刷出 ERROR traceback。
                    logger.debug("live-transcript queue full; dropping newest event")

            try:
                loop.call_soon_threadsafe(_put)
            except RuntimeError:
                pass  # loop 已关闭（客户端断开）

        unsubscribe = bus.subscribe(on_event)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                    payload = json.dumps(event.to_payload(), ensure_ascii=False)
                    yield f"data: {payload}\n\n"
                except TimeoutError:  # noqa: UP041 - asyncio.TimeoutError 在 3.11+ 即 builtin 别名
                    yield ": keep-alive\n\n"
        finally:
            unsubscribe()

    return StreamingResponse(
        event_stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
