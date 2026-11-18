"""TDD: in-process /v1/audio/visemes endpoint + capability."""
from __future__ import annotations

import io
import threading

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from speech_to_speech.api.openai_realtime.websocket_router import create_app
from speech_to_speech.pipeline.visemes import Viseme


def _wav(seconds=0.5, rate=16000):
    buf = io.BytesIO()
    sf.write(buf, (0.05 * np.sin(2 * np.pi * 200 * np.arange(int(rate*seconds))/rate)).astype(np.float32), rate, format="WAV")
    return buf.getvalue()


class _FakeSTV:
    def speech_to_visemes(self, audio: np.ndarray) -> list[Viseme]:
        return [Viseme(viseme=6, start_s=0.0, end_s=0.2)]


def _pool_with(handler):
    class _U:
        handlers = [handler] if handler else []
    return [_U()]


def _routes(app):
    return {(m, r.path) for r in app.routes for m in (getattr(r, "methods", None) or set())}


def _client(monkeypatch, handler):
    from speech_to_speech.api.openai_realtime import visemes_routes as vr
    monkeypatch.setattr(vr, "find_stv_handler", lambda pool: handler)
    return TestClient(create_app(pool=_pool_with(handler), stop_event=threading.Event()))


def test_visemes_routes_registered(monkeypatch):
    client = _client(monkeypatch, _FakeSTV())
    routes = _routes(client.app)
    assert ("POST", "/v1/audio/visemes") in routes
    assert ("GET", "/v1/audio/visemes/capability") in routes


def test_visemes_returns_list(monkeypatch):
    client = _client(monkeypatch, _FakeSTV())
    resp = client.post("/v1/audio/visemes", files={"file": ("a.wav", _wav(), "audio/wav")})
    assert resp.status_code == 200
    body = resp.json()
    assert "visemes" in body
    assert body["visemes"][0]["viseme"] == 6


def test_visemes_missing_handler_503(monkeypatch):
    client = _client(monkeypatch, None)
    resp = client.post("/v1/audio/visemes", files={"file": ("a.wav", _wav(), "audio/wav")})
    assert resp.status_code == 503


def test_visemes_capability_ready_false_when_missing(monkeypatch):
    client = _client(monkeypatch, None)
    resp = client.get("/v1/audio/visemes/capability")
    assert resp.status_code == 200
    assert resp.json()["ready"] is False


def test_visemes_capability_ready_true(monkeypatch):
    client = _client(monkeypatch, _FakeSTV())
    resp = client.get("/v1/audio/visemes/capability")
    assert resp.json()["ready"] is True
