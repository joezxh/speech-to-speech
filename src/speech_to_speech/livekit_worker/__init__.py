# src/speech_to_speech/livekit_worker/__init__.py
"""LiveKit room transcript worker: embedded thread runtime.

The worker runs livekit-agents WorkerServer inside a dedicated thread with its
own asyncio loop (same pattern as --with-console / voiceprint service). A crash
in the worker thread must never take down the speech pipeline: the thread
isolates failures and ThreadManager shutdown reaches the loop through the
shared stop event.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from concurrent.futures import Future
from threading import Event

logger = logging.getLogger(__name__)


class LiveKitWorkerRuntime:
    """内嵌 LiveKit 转写 worker：独立线程 + 专用 asyncio loop 跑 livekit-agents WorkerServer。

    遵循 ThreadManager handler 协议（与 EmbeddedAgent 同型）：``stop_event`` 供
    ThreadManager.stop() 置位，``run()`` 作为线程目标。worker 线程内的任何崩溃
    只记日志，绝不拖垮语音主流程。
    """

    def __init__(self, stop_event: Event, *, stt_handler: object | None = None) -> None:
        self.stop_event = stop_event
        self._shared_stt_handler = stt_handler
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: object | None = None

    @property
    def name(self) -> str:
        return "livekit-worker"

    def attach_stt_handler(self, handler: object) -> None:
        """由 build_pipeline 注入 pipeline 已解析的 STT handler（local ASR 模式用）。"""
        self._shared_stt_handler = handler

    def _resolve_stt_handler(self) -> object | None:
        """local ASR 模式取 pipeline STT handler；gateway 模式恒为 None。"""
        if os.environ.get("LIVEKIT_WORKER_ASR_MODE", "gateway").strip().lower() != "local":
            return None
        return self._shared_stt_handler

    def run(self) -> None:
        """ThreadManager 线程目标：启动专用 asyncio loop，并侦听共享 stop_event。"""
        loop = asyncio.new_event_loop()
        self._loop = loop
        loop_thread = threading.Thread(target=loop.run_forever, name="livekit-worker-loop", daemon=True)
        loop_thread.start()
        try:
            serve_future = asyncio.run_coroutine_threadsafe(self._serve(), loop)
            serve_future.add_done_callback(self._log_serve_crash)
            # ThreadManager.stop() 置位 stop_event → 收掉 loop，线程随之退出
            self.stop_event.wait()
        finally:
            self._shutdown_loop(loop)
            loop_thread.join(timeout=5)
            loop.close()

    @staticmethod
    def _log_serve_crash(serve_future: Future) -> None:
        exc = serve_future.exception()
        if exc is not None:
            logger.error("livekit-worker thread crashed; pipeline keeps running", exc_info=exc)

    @staticmethod
    def _shutdown_loop(loop: asyncio.AbstractEventLoop) -> None:
        """停机收尾：取消 loop 内在飞任务后再 stop，避免悬挂任务告警。"""

        async def _cancel_pending() -> None:
            tasks = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        try:
            asyncio.run_coroutine_threadsafe(_cancel_pending(), loop).result(timeout=5)
        except Exception:  # noqa: BLE001 - 关停路径尽力而为
            pass
        loop.call_soon_threadsafe(loop.stop)

    async def _serve(self) -> None:
        from livekit.agents import WorkerOptions

        from speech_to_speech.livekit_worker import worker
        from speech_to_speech.livekit_worker.worker import AGENT_NAME, HEALTH_PORT, LOAD_THRESHOLD, entrypoint

        worker.set_shared_state(
            stt_handler=self._resolve_stt_handler(), stop_event=self.stop_event,
        )
        try:
            from livekit.agents.worker import WorkerServer
        except ImportError:  # noqa: PLC0415 - 0.12.x 内嵌 API 名称实现期核对
            from livekit.agents import WorkerServer  # type: ignore[no-redef]

        server = WorkerServer(WorkerOptions(
            entrypoint_fnc=entrypoint,
            port=HEALTH_PORT,
            agent_name=AGENT_NAME,
            load_threshold=LOAD_THRESHOLD,
        ))
        self._server = server
        await server.start()
        await server.run()
