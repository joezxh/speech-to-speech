from __future__ import annotations

import io
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.config import console as console_settings
from app.db.database import get_db
from app.main import create_app
from app.repositories.draft_repository import DraftRepository
from app.repositories.user_repository import UserRepository
from app.repositories.version_repository import VersionRepository
from app.services.auth_service import hash_password

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parameter-catalog.min.yaml"

PROFILE_YAML = """\
schema_version: 1
blocks:
  tts-main: {kind: tts, backend: qwen3, settings: {model_name: Qwen3-TTS}}
pipelines:
  prod:
    stages: {tts: tts-main}
    num_pipelines: 1
"""


def _wav(seconds: float = 8.0, *, rate: int = 16000, channels: int = 1) -> bytes:
    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(channels)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(b"\x00\x00" * int(seconds * rate) * channels)
        return buffer.getvalue()


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "prod.yaml").write_text(PROFILE_YAML, encoding="utf-8")
    monkeypatch.setattr(console_settings, "param_config_dir", str(config))
    monkeypatch.setattr(console_settings, "param_catalog_path", str(FIXTURE))
    monkeypatch.setattr(console_settings, "voice_data_dir", str(tmp_path / "voices"))

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))

    # The background task opens its own session; in production that is the same
    # database, in tests it has to be the fixture's engine.
    factory = sessionmaker(bind=db_session.get_bind(), future=True)
    monkeypatch.setattr("app.db.database.SessionLocal", factory)

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    UserRepository(db_session).create("alice", hash_password("correct-horse"), "admin")
    UserRepository(db_session).create("bob", hash_password("correct-horse"), "operator")
    return TestClient(app)


def _auth(client, username: str = "alice") -> dict[str, str]:
    tokens = client.post("/api/v1/auth/login", json={"username": username, "password": "correct-horse"}).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def _upload(client, monkeypatch, **overrides):
    calls: list[str] = []

    async def fake_run(voice_id, ref_wav, out_dir):
        calls.append(voice_id)
        return (True, None)

    monkeypatch.setattr("app.services.voice_precompute.run", fake_run)
    form = {
        "name": "嘉嘉",
        "source": "clone",
        "backend": "qwen3",
        "language": "zh",
        "refText": "这是一段用于克隆的逐字转写。",
        "consent": "biometric-ack",
        "retentionDays": "30",
    }
    form.update(overrides)
    files = {"audio": ("ref.wav", _wav(8.0), "audio/wav")}
    response = client.post("/api/v1/voices", data=form, files=files, headers=_auth(client))
    return response, calls


def test_upload_runs_precompute_and_becomes_ready(client, monkeypatch):
    response, calls = _upload(client, monkeypatch)
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["status"] == "precomputing"
    assert data["jobId"] == f"voice-{data['id']}"
    assert calls == [data["id"]]

    detail = client.get(f"/api/v1/voices/{data['id']}", headers=_auth(client)).json()["data"]
    assert detail["status"] == "ready"
    assert detail["precompute"] == {"stage": "done", "progress": 100, "errorCode": None}
    assert detail["refText"] == "这是一段用于克隆的逐字转写。"


def test_missing_consent_is_refused_before_anything_else(client, monkeypatch):
    response, _ = _upload(client, monkeypatch, consent="")
    assert response.status_code == 400
    assert response.json()["code"] == "voice_consent_required"


def test_oversized_audio_is_413_with_the_voice_code(client, monkeypatch):
    monkeypatch.setattr(console_settings, "voice_max_bytes", 256)
    response, _ = _upload(client, monkeypatch)
    assert response.status_code == 413
    assert response.json()["code"] == "voice_too_large"


def test_wrong_sample_rate_is_audio_invalid(client, monkeypatch):
    calls: list[str] = []

    async def fake_run(voice_id, ref_wav, out_dir):  # pragma: no cover - not reached
        calls.append(voice_id)
        return (True, None)

    monkeypatch.setattr("app.services.voice_precompute.run", fake_run)
    form = {
        "name": "错的采样率",
        "source": "clone",
        "backend": "qwen3",
        "refText": "转写",
        "consent": "biometric-ack",
    }
    response = client.post(
        "/api/v1/voices",
        data=form,
        files={"audio": ("ref.wav", _wav(4.0, rate=44100), "audio/wav")},
        headers=_auth(client),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "voice_audio_invalid"
    assert calls == []


def test_duplicate_name_is_refused_case_insensitively(client, monkeypatch, db_session):
    first, _ = _upload(client, monkeypatch, name="Jiajia")
    assert first.status_code == 201
    second, _ = _upload(client, monkeypatch, name="jiajia")
    assert second.status_code == 409
    assert second.json()["code"] == "voice_name_taken"


def test_delete_refuses_a_voice_a_draft_still_uses(client, monkeypatch, db_session):
    response, _ = _upload(client, monkeypatch)
    voice_id = response.json()["data"]["id"]
    DraftRepository(db_session).put(
        "prod",
        base_version=0,
        patch={"tts.qwen3_tts_ref_spk": f"/app/data/voices/{voice_id}/spk.npy"},
        actor="alice",
    )

    blocked = client.delete(f"/api/v1/voices/{voice_id}", headers=_auth(client))
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "voice_in_use"
    assert blocked.json()["detail"] == [
        {"field": "profiles", "value": ["prod"]},
        {"field": "versions", "value": 0},
    ]

    DraftRepository(db_session).drop("prod")
    VersionRepository(db_session).create(
        "prod",
        status="live",
        yaml_text=f"spk: /app/data/voices/{voice_id}/spk.npy\n",
        env_sha256="",
        note="",
        author="alice",
    )
    still_blocked = client.delete(f"/api/v1/voices/{voice_id}", headers=_auth(client))
    assert still_blocked.status_code == 409
    assert still_blocked.json()["detail"][1] == {"field": "versions", "value": 1}


def test_audition_supports_range_requests(client, monkeypatch):
    response, _ = _upload(client, monkeypatch)
    voice_id = response.json()["data"]["id"]
    headers = {**_auth(client), "Range": "bytes=0-99"}
    chunk = client.get(f"/api/v1/voices/{voice_id}/audio", headers=headers)
    assert chunk.status_code == 206
    assert chunk.headers["content-range"].startswith("bytes 0-99/")
    assert chunk.headers["cache-control"] == "no-store"
    assert len(chunk.content) == 100


def test_ggml_backend_skips_precompute_and_keeps_ref_audio(client, monkeypatch, tmp_path):
    (tmp_path / "config" / "prod.yaml").write_text(
        PROFILE_YAML.replace("model_name: Qwen3-TTS", "model_name: Qwen3-TTS\n    qwen3_tts_backend: ggml"),
        encoding="utf-8",
    )
    response, calls = _upload(client, monkeypatch)
    assert response.status_code == 201
    assert response.json()["data"]["status"] == "ready"
    assert calls == []


def test_operator_may_not_delete(client, monkeypatch):
    response, _ = _upload(client, monkeypatch)
    voice_id = response.json()["data"]["id"]
    denied = client.delete(f"/api/v1/voices/{voice_id}", headers=_auth(client, "bob"))
    assert denied.status_code == 403
