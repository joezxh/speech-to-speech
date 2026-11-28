"""HandlerLifecycle 端口：按 handler 登记/启动/退役/join（TDD RED → GREEN）。"""

from __future__ import annotations

import threading
from queue import Queue
from types import SimpleNamespace

import pytest

from speech_to_speech.api.openai_realtime.handler_lifecycle import (
    ThreadManagerLifecycle,
)
from speech_to_speech.baseHandler import BaseHandler
from speech_to_speech.pipeline.messages import PIPELINE_END
from speech_to_speech.utils.thread_manager import ThreadManager


class _Handler(BaseHandler):
    def __init__(self, queue_out: Queue) -> None:
        self.retired = False
        super().__init__(threading.Event(), Queue(), queue_out)

    def _run_loop(self) -> None:
        self.stop_event.wait(0.01)

    def retire(self) -> None:
        self.retired = True
        self.stop_event.set()


def test_retire_does_not_emit_pipeline_end():
    queue_out = Queue()
    handler = _Handler(queue_out)

    handler.retire()
    handler.run()

    assert not any(
        getattr(item, "kind", item) == PIPELINE_END for item in queue_out.queue
    )


def test_thread_manager_lifecycle_replaces_one_handler_without_stopping_others():
    out = Queue()
    first = _Handler(out)
    other = _Handler(out)
    lifecycle = ThreadManagerLifecycle(ThreadManager([first, other]))

    lifecycle.start_all()
    assert lifecycle.alive(first)
    assert lifecycle.alive(other)

    lifecycle.retire(first)
    replacement = _Handler(out)
    lifecycle.register(replacement)
    lifecycle.start(replacement)

    assert not lifecycle.alive(first)
    assert lifecycle.alive(replacement)
    assert lifecycle.alive(other)

    lifecycle.stop_all()
