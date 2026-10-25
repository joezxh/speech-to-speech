import logging
import threading
from threading import Event
from typing import TYPE_CHECKING

import uvicorn

from speech_to_speech.api.openai_realtime.llm_proxy import LLMProxyConfig
from speech_to_speech.api.openai_realtime.pipeline_unit import PipelineUnit
from speech_to_speech.api.openai_realtime.websocket_router import create_app

if TYPE_CHECKING:
    from speech_to_speech.console_integration import ConsoleAttachment

logger = logging.getLogger(__name__)


class RealtimeServer:
    """
    Pipeline handler for the OpenAI Realtime API mode.

    Owns a pool of isolated PipelineUnits and a single uvicorn server.
    The websocket route claims the next free unit on each accept and releases
    it on disconnect; once all units are in use, further connections are rejected.
    """

    def __init__(
        self,
        stop_event: Event,
        pool: list[PipelineUnit],
        host: str = "0.0.0.0",
        port: int = 8765,
        llm_proxy_config: LLMProxyConfig | None = None,
        console_attachment: ConsoleAttachment | None = None,
    ) -> None:
        if not pool:
            raise ValueError("RealtimeServer requires at least one PipelineUnit in the pool")
        self.stop_event = stop_event
        self.pool = pool
        self.host = host
        self.port = port
        self.llm_proxy_config = llm_proxy_config
        self.console_attachment = console_attachment
        # Only meaningful with the console integrated: a bare realtime server keeps
        # today's exit-code behaviour untouched.
        self.startup_failed = False

    def run(self) -> None:
        """Start the FastAPI/uvicorn server (called from a ThreadManager thread)."""
        app = create_app(
            pool=self.pool,
            stop_event=self.stop_event,
            llm_proxy_config=self.llm_proxy_config,
            console_attachment=self.console_attachment,
        )

        logger.info(
            f"OpenAI Realtime API starting on ws://{self.host}:{self.port}/v1/realtime (pool size {len(self.pool)})"
        )

        config = uvicorn.Config(
            app,
            host=self.host,
            port=self.port,
            log_level="info",
        )
        server = uvicorn.Server(config)

        server.install_signal_handlers = lambda: None  # type: ignore[attr-defined]

        def _watch_stop() -> None:
            self.stop_event.wait()
            server.should_exit = True

        watcher = threading.Thread(target=_watch_stop, daemon=True)
        watcher.start()

        try:
            server.run()
        finally:
            # uvicorn exits with SystemExit from a worker thread on a failed bind,
            # and threading swallows it. Without this flag the process would report
            # success for a port it never owned.
            if self.console_attachment is not None and not server.started:
                self.startup_failed = True
                logger.error(
                    "OpenAI Realtime API could not bind %s:%s; aborting the console integration.",
                    self.host,
                    self.port,
                )
            # A bind/startup failure must also stop the model threads. During a
            # normal shutdown the event is already set by ThreadManager.
            self.stop_event.set()
