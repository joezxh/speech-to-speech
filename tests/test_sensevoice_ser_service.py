"""Contract tests for the in-process SenseVoice SER REST endpoints (TDD)."""
from __future__ import annotations

import io
import threading

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from speech_to_speech.api.openai_realtime.websocket_router import create_app


def _wav(seconds: float = 0.3, rate: int = 16000, amplitude: float = 0.1) -> bytes:
    t = np.arange(int(rate * seconds)) / rate
    audio = (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, audio, rate, format="WAV")
    return buf.getvalue()


class _FakeSERHandler:
    """Mimics a SenseVoiceSTTHandler with an attached emotion logits hook."""

    def __init__(self, raw="HAPPY", laughter=False, confidence=0.9, margin=0.4):
        self.raw = raw
        self.laughter = laughter
        self.confidence = confidence
        self.margin = margin

    def recognize(self, audio: np.ndarray) -> dict:
        return {
            "raw": self.raw,
            "laughter": self.laughter,
            "confidence": self.confidence,
            "margin": self.margin,
        }


def _pool_with(handler):
    class _Unit:
        handlers = [handler]

    return [_Unit()]


def _routes(app) -> set[tuple[str, str]]:
    return {
        (m, r.path)
        for r in app.routes
        for m in (getattr(r, "methods", None) or set())
    }


def _client(monkeypatch, handler) -> TestClient:
    monkeypatch.setenv("SER_PROVIDER", "local")
    from speech_to_speech.api.openai_realtime import emotion_local_service as els

    monkeypatch.setattr(els, "find_ser_handler", lambda pool: handler)
    return TestClient(create_app(pool=_pool_with(handler), stop_event=threading.Event()))


def test_local_ser_registers_both_aliases_and_health(monkeypatch):
    client = _client(monkeypatch, _FakeSERHandler())
    routes = _routes(client.app)
    assert ("POST", "/recognize") in routes
    assert ("POST", "/v1/audio/emotion") in routes
    assert ("GET", "/v1/audio/emotion/health") in routes


def test_recognize_returns_happy_with_confidence_margin(monkeypatch):
    client = _client(monkeypatch, _FakeSERHandler(raw="HAPPY", laughter=True))
    resp = client.post("/recognize", files={"file": ("a.wav", _wav(), "audio/wav")})
    assert resp.status_code == 200
    body = resp.json()
    assert body["emotion"] == "happy"
    assert body["confidence"] == 0.9
    assert body["margin"] == 0.4
    assert body["events"]["laughter"] is True
    assert body["rawLabel"] == "HAPPY"


def test_recognize_maps_fearful_and_surprised(monkeypatch):
    for raw, expected in (("FEARFUL", "anxious"), ("SURPRISED", "agitated")):
        client = _client(monkeypatch, _FakeSERHandler(raw=raw))
        resp = client.post("/recognize", files={"file": ("a.wav", _wav(), "audio/wav")})
        assert resp.status_code == 200
        assert resp.json()["emotion"] == expected


def test_silent_audio_returns_structured_409(monkeypatch):
    client = _client(monkeypatch, _FakeSERHandler())
    resp = client.post("/recognize", files={"file": ("a.wav", _wav(amplitude=0.0), "audio/wav")})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "SILENCE"
    assert resp.json()["error"]["stage"] == "SER"


def test_low_margin_returns_structured_409(monkeypatch):
    client = _client(monkeypatch, _FakeSERHandler(raw="HAPPY", confidence=0.9, margin=0.01))
    resp = client.post("/recognize", files={"file": ("a.wav", _wav(), "audio/wav")})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "LOW_MARGIN"


def test_rejected_label_returns_structured_409(monkeypatch):
    client = _client(monkeypatch, _FakeSERHandler(raw="EMO_UNKNOWN"))
    resp = client.post("/recognize", files={"file": ("a.wav", _wav(), "audio/wav")})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "REJECTED_LABEL"


def test_missing_handler_returns_503(monkeypatch):
    monkeypatch.setenv("SER_PROVIDER", "local")
    from speech_to_speech.api.openai_realtime import emotion_local_service as els

    monkeypatch.setattr(els, "find_ser_handler", lambda pool: None)
    client = TestClient(create_app(pool=[], stop_event=threading.Event()))
    resp = client.post("/recognize", files={"file": ("a.wav", _wav(), "audio/wav")})
    assert resp.status_code == 503


def test_health_reports_ready_and_labels(monkeypatch):
    client = _client(monkeypatch, _FakeSERHandler())
    resp = client.get("/v1/audio/emotion/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["provider"] == "local"
    assert "happy" in body["labels_supported"]
    assert "agitated" in body["labels_supported"]
