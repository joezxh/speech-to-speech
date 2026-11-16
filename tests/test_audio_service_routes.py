"""Contract tests for the standalone ASR / TTS / voiceprint endpoints.

These endpoints used to exist only as build-time string patches inside the
container image. They must be reachable when the source tree is started from
PyCharm, so they are asserted against ``create_app()`` directly.
"""
from __future__ import annotations

import io
import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf
import yaml
from fastapi.testclient import TestClient

from speech_to_speech.api.openai_realtime.websocket_router import create_app
from speech_to_speech.voiceprint import service as voiceprint_service
from speech_to_speech.voiceprint.errors import VoiceprintErrorCode
from speech_to_speech.voiceprint.service import VoiceprintRequestError

REPO_ROOT = Path(__file__).resolve().parents[1]


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


def _client(pool, monkeypatch, **env) -> TestClient:
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, str(value))
    return TestClient(create_app(pool=pool, stop_event=threading.Event()))


# The patched implementation locates handlers by class name.
class Qwen3ASRSTTHandler:
    def _transcribe(self, audio, lang):
        assert isinstance(audio, np.ndarray)
        return ("你好", "zh")


class _FakeTTSModel:
    def generate_custom_voice(self, text, speaker, language, non_streaming_mode):
        assert text == "你好"
        return [np.zeros(240, dtype=np.float32)], 24000


class Qwen3TTSHandler:
    def __init__(self):
        self.model = _FakeTTSModel()
        self.streaming_chunk_size = 4
        self.ref_audio = None
        self.ref_spk = None
        self.ref_rvq = None
        self.ref_text = ""

    def _has_voice_clone_reference(self):
        return False


class _FakeVoiceprintService:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def attach_pool(self, pool, encoder_dir=None):
        self.attached = encoder_dir

    def authorize(self, header):
        if header != "Bearer test-key":
            raise VoiceprintRequestError(VoiceprintErrorCode.UNAUTHORIZED)

    def embed(self, data, model=None, purpose=None):
        if model not in (None, "", "qwen3-tts-base-speaker"):
            raise VoiceprintRequestError(VoiceprintErrorCode.MODEL_MISMATCH)
        return {
            "embedding": [0.0] * 2048,
            "dim": 2048,
            "model": "qwen3-tts-base-speaker",
            "quality": 1.0,
            "speechDurationMs": 100,
        }

    def capability(self):
        return {"ready": True, "dim": 2048, "model": "qwen3-tts-base-speaker", "device": "cpu"}


@pytest.fixture
def fake_voiceprint(monkeypatch):
    monkeypatch.setattr(voiceprint_service, "VoiceprintService", _FakeVoiceprintService)
    return _FakeVoiceprintService


def test_audio_service_routes_are_registered():
    app = create_app(pool=[], stop_event=threading.Event())
    assert ("POST", "/v1/audio/transcriptions") in _routes(app)
    assert ("POST", "/v1/audio/speech") in _routes(app)


def test_asr_without_handler_returns_503(monkeypatch):
    client = _client([], monkeypatch)
    response = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("a.wav", _wav_bytes(), "audio/wav")},
    )
    assert response.status_code == 503


def test_asr_transcribes_wav_with_handler(monkeypatch):
    unit = SimpleNamespace(handlers=[Qwen3ASRSTTHandler()])
    client = _client([unit], monkeypatch)
    response = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("a.wav", _wav_bytes(), "audio/wav")},
        data={"language": "auto", "model": "qwen3-asr"},
    )
    assert response.status_code == 200
    assert response.json() == {"text": "你好", "language": "zh"}


def test_tts_without_handler_returns_503(monkeypatch):
    client = _client([], monkeypatch)
    response = client.post("/v1/audio/speech", json={"input": "你好"})
    assert response.status_code == 503


def test_tts_returns_wav_with_handler(monkeypatch):
    unit = SimpleNamespace(handlers=[Qwen3TTSHandler()])
    client = _client([unit], monkeypatch)
    response = client.post("/v1/audio/speech", json={"input": "你好", "voice": "Aiden"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content[:4] == b"RIFF"


def test_voiceprint_routes_registered_when_enabled(monkeypatch, fake_voiceprint):
    client = _client(
        [],
        monkeypatch,
        VOICEPRINT_ENABLED="true",
        VOICEPRINT_API_KEY="test-key",
        VOICEPRINT_MODEL="qwen3-tts-base-speaker",
        VOICEPRINT_ENCODER_DIR="cache/qwen3-speaker-encoder",
    )
    assert ("POST", "/v1/audio/embeddings") in _routes(client.app)
    assert ("GET", "/v1/audio/embeddings/capability") in _routes(client.app)


def test_voiceprint_routes_absent_when_disabled(monkeypatch, fake_voiceprint):
    client = _client([], monkeypatch, VOICEPRINT_ENABLED="false")
    assert ("POST", "/v1/audio/embeddings") not in _routes(client.app)
    assert ("GET", "/v1/audio/embeddings/capability") not in _routes(client.app)


def test_voiceprint_rejects_missing_bearer(monkeypatch, fake_voiceprint):
    client = _client(
        [], monkeypatch, VOICEPRINT_ENABLED="true", VOICEPRINT_API_KEY="test-key"
    )
    response = client.post(
        "/v1/audio/embeddings",
        files={"file": ("a.wav", _wav_bytes(), "audio/wav")},
        data={"model": "qwen3-tts-base-speaker"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_voiceprint_rejects_model_mismatch(monkeypatch, fake_voiceprint):
    client = _client(
        [], monkeypatch, VOICEPRINT_ENABLED="true", VOICEPRINT_API_KEY="test-key"
    )
    response = client.post(
        "/v1/audio/embeddings",
        files={"file": ("a.wav", _wav_bytes(), "audio/wav")},
        data={"model": "rr"},
        headers={"Authorization": "Bearer test-key"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MODEL_MISMATCH"


def test_voiceprint_capability_reports_dim(monkeypatch, fake_voiceprint):
    client = _client(
        [], monkeypatch, VOICEPRINT_ENABLED="true", VOICEPRINT_API_KEY="test-key"
    )
    response = client.get(
        "/v1/audio/embeddings/capability",
        headers={"Authorization": "Bearer test-key"},
    )
    assert response.status_code == 200
    assert response.json()["dim"] == 2048


def test_prod_yaml_keeps_top_level_keys_in_whitelist():
    document = yaml.safe_load((REPO_ROOT / "config/prod.yaml").read_text(encoding="utf-8"))
    assert set(document) <= {"schema_version", "runtime", "blocks", "pipelines", "models"}
