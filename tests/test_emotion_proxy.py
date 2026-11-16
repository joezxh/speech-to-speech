"""Contract tests for the emotion proxy that reuses the existing SER service."""
from __future__ import annotations

import io
import threading

import httpx
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from speech_to_speech.api.openai_realtime.websocket_router import create_app


def _wav_bytes(seconds: float = 0.2, rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, np.zeros(int(rate * seconds), dtype=np.float32), rate, format="WAV")
    return buffer.getvalue()


def _routes(app) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in app.routes
        for method in (getattr(route, "methods", None) or set())
    }


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient so no real SER service is needed."""

    status_code = 200
    payload: dict = {"emotion": "calm", "confidence": 0.9}
    exception: Exception | None = None
    last_request: dict | None = None

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def _respond(self, url: str, kwargs: dict) -> httpx.Response:
        type(self).last_request = {"url": url, **kwargs}
        if type(self).exception is not None:
            raise type(self).exception
        return httpx.Response(
            type(self).status_code,
            json=type(self).payload,
            request=httpx.Request("POST", url),
        )

    async def post(self, url, **kwargs):
        return self._respond(url, kwargs)

    async def get(self, url, **kwargs):
        return self._respond(url, kwargs)


@pytest.fixture
def fake_httpx(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.status_code = 200
    _FakeAsyncClient.payload = {"emotion": "calm", "confidence": 0.9}
    _FakeAsyncClient.exception = None
    _FakeAsyncClient.last_request = None
    return _FakeAsyncClient


def _client(monkeypatch, **env) -> TestClient:
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, str(value))
    return TestClient(create_app(pool=[], stop_event=threading.Event()))


def _enabled(monkeypatch, fake_httpx) -> TestClient:
    return _client(
        monkeypatch,
        SER_ENABLED="true",
        SER_BASE_URL="http://ser.test/ser",
        SER_API_KEY="ser-key",
        SER_TIMEOUT_MS="1500",
    )


def test_emotion_routes_registered_when_enabled(monkeypatch, fake_httpx):
    client = _enabled(monkeypatch, fake_httpx)
    assert ("POST", "/v1/audio/emotion") in _routes(client.app)
    assert ("GET", "/v1/audio/emotion/health") in _routes(client.app)


def test_emotion_routes_absent_when_disabled(monkeypatch, fake_httpx):
    client = _client(monkeypatch, SER_ENABLED="false")
    assert ("POST", "/v1/audio/emotion") not in _routes(client.app)
    assert ("GET", "/v1/audio/emotion/health") not in _routes(client.app)


def test_emotion_proxy_injects_api_key_and_passes_response(monkeypatch, fake_httpx):
    client = _enabled(monkeypatch, fake_httpx)
    response = client.post(
        "/v1/audio/emotion",
        files={"file": ("a.wav", _wav_bytes(), "audio/wav")},
        data={"sample_rate": "16000", "language": "zh"},
        headers={"Authorization": "Bearer browser-token"},
    )
    assert response.status_code == 200
    assert response.json() == {"emotion": "calm", "confidence": 0.9}
    request = _FakeAsyncClient.last_request
    assert request is not None
    assert request["url"] == "http://ser.test/ser/v1/audio/emotion"
    assert request["headers"]["X-API-Key"] == "ser-key"
    assert "Authorization" not in request["headers"]


def test_emotion_proxy_passes_through_downstream_error(monkeypatch, fake_httpx):
    _FakeAsyncClient.status_code = 409
    _FakeAsyncClient.payload = {"detail": "silent audio"}
    client = _enabled(monkeypatch, fake_httpx)
    response = client.post(
        "/v1/audio/emotion",
        files={"file": ("a.wav", _wav_bytes(), "audio/wav")},
    )
    assert response.status_code == 409


def test_emotion_proxy_maps_timeout_to_504(monkeypatch, fake_httpx):
    _FakeAsyncClient.exception = httpx.ReadTimeout("slow upstream")
    client = _enabled(monkeypatch, fake_httpx)
    response = client.post(
        "/v1/audio/emotion",
        files={"file": ("a.wav", _wav_bytes(), "audio/wav")},
    )
    assert response.status_code == 504


def test_emotion_proxy_maps_unreachable_to_503(monkeypatch, fake_httpx):
    _FakeAsyncClient.exception = httpx.ConnectError("connection refused")
    client = _enabled(monkeypatch, fake_httpx)
    response = client.post(
        "/v1/audio/emotion",
        files={"file": ("a.wav", _wav_bytes(), "audio/wav")},
    )
    assert response.status_code == 503


def test_emotion_health_forwards_to_ser_health(monkeypatch, fake_httpx):
    _FakeAsyncClient.payload = {"status": "ok", "ready": True}
    client = _enabled(monkeypatch, fake_httpx)
    response = client.get("/v1/audio/emotion/health")
    assert response.status_code == 200
    assert response.json()["ready"] is True
    assert _FakeAsyncClient.last_request["url"] == "http://ser.test/ser/health"
    assert _FakeAsyncClient.last_request["headers"]["X-API-Key"] == "ser-key"
