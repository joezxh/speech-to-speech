"""TDD: SER_PROVIDER selects local SenseVoice vs emotion2vec proxy."""
from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from speech_to_speech.api.openai_realtime.websocket_router import create_app


def _routes(app) -> set[tuple[str, str]]:
    return {
        (m, r.path)
        for r in app.routes
        for m in (getattr(r, "methods", None) or set())
    }


def _client(monkeypatch, **env) -> TestClient:
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, str(v))
    return TestClient(create_app(pool=[], stop_event=threading.Event()))


def test_local_provider_registers_recognize_and_skips_proxy(monkeypatch):
    client = _client(
        monkeypatch,
        SER_PROVIDER="local",
        SER_ENABLED="true",
        SER_BASE_URL="http://ser.test/ser",
        SER_API_KEY="k",
    )
    routes = _routes(client.app)
    assert ("POST", "/recognize") in routes
    # Both share /v1/audio/emotion — exactly one handler registered.
    emotion_routes = [r for r in client.app.routes if getattr(r, "path", "") == "/v1/audio/emotion"]
    assert len(emotion_routes) == 1


def test_proxy_provider_registers_no_recognize(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: None)
    client = _client(
        monkeypatch,
        SER_PROVIDER="proxy",
        SER_ENABLED="true",
        SER_BASE_URL="http://ser.test/ser",
        SER_API_KEY="k",
    )
    routes = _routes(client.app)
    assert ("POST", "/recognize") not in routes
