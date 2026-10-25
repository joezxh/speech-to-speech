"""A failed bind must not look like a clean shutdown (spec §5.3)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from threading import Event
from types import SimpleNamespace

import uvicorn
from fastapi import FastAPI

from speech_to_speech.api.openai_realtime.server import RealtimeServer


def _unit() -> SimpleNamespace:
    # A real PipelineUnit needs service/cancel_scope/four queues/five events;
    # run() only reads .index through create_app, so a stub is enough here.
    return SimpleNamespace(index=0, handlers=[], session=None)


def _attachment() -> SimpleNamespace:
    # create_app() mounts attachment.app at "/", so .app must be a real ASGI
    # callable; the lifespan is never entered because no request is served.
    @asynccontextmanager
    async def lifespan(_app):
        yield

    return SimpleNamespace(app=FastAPI(), lifespan=lifespan)


def _server(attachment):
    return RealtimeServer(
        stop_event=Event(), pool=[_unit()], host="127.0.0.1", port=8765, console_attachment=attachment
    )


def test_bind_failure_is_flagged_when_the_console_is_integrated(monkeypatch):
    class FailedRun(uvicorn.Server):
        def run(self, sockets=None):  # noqa: D401 - simulates a bind failure
            return None

    monkeypatch.setattr(uvicorn, "Server", FailedRun)
    server = _server(attachment=_attachment())

    server.run()

    assert server.startup_failed is True
    assert server.stop_event.is_set()


def test_a_clean_bind_is_not_flagged(monkeypatch):
    class CleanRun(uvicorn.Server):
        def run(self, sockets=None):
            self.started = True

    monkeypatch.setattr(uvicorn, "Server", CleanRun)
    server = _server(attachment=_attachment())

    server.run()

    assert server.startup_failed is False


def test_switch_off_keeps_the_old_exit_code_semantics(monkeypatch):
    class FailedRun(uvicorn.Server):
        def run(self, sockets=None):
            return None

    monkeypatch.setattr(uvicorn, "Server", FailedRun)
    server = _server(attachment=None)

    server.run()

    assert server.startup_failed is False
    assert server.stop_event.is_set()
