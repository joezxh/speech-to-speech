from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import console as console_settings
from app.db.database import get_db
from app.main import create_app
from app.repositories.draft_repository import DraftRepository
from app.repositories.user_repository import UserRepository
from app.services import publish_flow_service
from app.services.auth_service import hash_password

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parameter-catalog.min.yaml"

PROFILE_YAML = """\
schema_version: 1
runtime:
  log_level: info
blocks:
  vad-main: {kind: vad, backend: silero, settings: {min_silence_ms: 700}}
  stt-main: {kind: stt, backend: whisper}
  llm-main: {kind: llm, backend: chat-completions}
  tts-main: {kind: tts, backend: kokoro}
pipelines:
  prod:
    stages: {vad: vad-main, stt: stt-main, llm: llm-main, tts: tts-main}
    num_pipelines: 1
"""


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "prod.yaml").write_text(PROFILE_YAML, encoding="utf-8")
    monkeypatch.setattr(console_settings, "param_config_dir", str(config))
    monkeypatch.setattr(console_settings, "param_catalog_path", str(FIXTURE))

    # The validator needs the whole runtime package; it is covered in
    # tests/unit/test_validator_service.py. Here the render is stubbed.
    monkeypatch.setattr(
        publish_flow_service,
        "render",
        lambda profile, values, environ=None: publish_flow_service.Rendered(
            text="schema_version: 1\n",
            values=values,
            applied=sorted(values),
            expected_size=1,
            resolved={"pipelines": [profile]},
        ),
    )

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    UserRepository(db_session).create("alice", hash_password("correct-horse"), "admin")
    UserRepository(db_session).create("bob", hash_password("correct-horse"), "operator")
    return TestClient(app)


def _auth(client, username="alice"):
    tokens = client.post("/api/v1/auth/login", json={"username": username, "password": "correct-horse"}).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def test_draft_is_empty_and_carries_the_live_version(client):
    data = client.get("/api/v1/profiles/prod/draft", headers=_auth(client)).json()["data"]
    assert data == {
        "profile": "prod",
        "baseVersion": 0,
        "draft": {},
        "masked": [],
        "updatedAt": None,
        "updatedBy": "",
    }


def test_patch_is_merged_and_secrets_come_back_masked(client):
    headers = _auth(client)
    first = client.post(
        "/api/v1/profiles/prod/draft",
        json={"patch": {"vad.min_silence_ms": 900, "llm.api_key": "sk-real"}},
        headers=headers,
    ).json()["data"]
    assert first["draft"] == {"vad.min_silence_ms": 900, "llm.api_key": "***"}
    assert first["validation"]["ok"] is True
    assert first["validation"]["mode"] == "runtime"

    second = client.post(
        "/api/v1/profiles/prod/draft", json={"patch": {"vad.min_silence_ms": 950}}, headers=headers
    ).json()["data"]
    assert second["draft"] == {"vad.min_silence_ms": 950, "llm.api_key": "***"}


def test_resending_the_mask_does_not_store_the_literal(client, db_session):
    headers = _auth(client)
    client.post("/api/v1/profiles/prod/draft", json={"patch": {"llm.api_key": "sk-real"}}, headers=headers)
    data = client.post(
        "/api/v1/profiles/prod/draft", json={"patch": {"llm.api_key": "***"}}, headers=headers
    ).json()["data"]
    assert data["skippedMasked"] == ["llm.api_key"]
    # The point of the check: the literal "***" must never reach the row.
    assert DraftRepository(db_session).get("prod").patch == {"llm.api_key": "sk-real"}


def test_null_drops_the_key_instead_of_storing_it(client, db_session):
    """A null patch value means "back to the catalog default" (A.3).

    A draft is a patch, so keeping `key: null` in the row would leave a key that
    reads as default, still counts as "in draft", and can never be cleared again
    — nor can it be discarded, because the page sees no dirty field.
    """
    headers = _auth(client)
    client.post(
        "/api/v1/profiles/prod/draft", json={"patch": {"vad.min_silence_ms": 900}}, headers=headers
    )

    data = client.post(
        "/api/v1/profiles/prod/draft", json={"patch": {"vad.min_silence_ms": None}}, headers=headers
    ).json()["data"]

    assert data["draft"] == {}
    assert DraftRepository(db_session).get("prod").patch == {}


def test_structural_mode_is_reported_to_the_caller(client, monkeypatch):
    monkeypatch.setattr(
        publish_flow_service,
        "render",
        lambda profile, values, environ=None: publish_flow_service.Rendered(
            text="schema_version: 1\n", values=values, applied=sorted(values)
        ),
    )
    data = client.post(
        "/api/v1/profiles/prod/draft",
        json={"patch": {"vad.min_silence_ms": 900}},
        headers=_auth(client),
    ).json()["data"]
    assert data["validation"]["mode"] == "structural"
    assert data["validation"]["expectedPoolSize"] is None


def test_base_version_conflict_is_409(client):
    response = client.post(
        "/api/v1/profiles/prod/draft",
        json={"patch": {"vad.min_silence_ms": 1}, "baseVersion": 7},
        headers=_auth(client),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "version_conflict"


def test_operator_may_patch_a_basic_field(client):
    assert (
        client.post(
            "/api/v1/profiles/prod/draft",
            json={"patch": {"vad.min_silence_ms": 800}},
            headers=_auth(client, "bob"),
        ).status_code
        == 200
    )


def test_operator_may_not_patch_an_expert_field(client):
    response = client.post(
        "/api/v1/profiles/prod/draft",
        json={"patch": {"stt.language": "en"}},
        headers=_auth(client, "bob"),
    )
    assert response.status_code == 403
    assert response.json()["detail"] == [{"field": "stt.language", "exposure": "expert"}]


def test_discard_requires_admin(client):
    assert client.delete("/api/v1/profiles/prod/draft", headers=_auth(client, "bob")).status_code == 403


def test_discard_without_a_draft_is_404_no_draft(client):
    response = client.delete("/api/v1/profiles/prod/draft", headers=_auth(client))
    assert response.status_code == 404
    assert response.json()["code"] == "no_draft"


def test_discard_removes_the_draft_and_creates_no_version(client, db_session):
    headers = _auth(client)
    client.post("/api/v1/profiles/prod/draft", json={"patch": {"vad.min_silence_ms": 900}}, headers=headers)
    data = client.delete("/api/v1/profiles/prod/draft", headers=headers).json()["data"]
    assert data["discarded"] is True
    assert data["revertedTo"] == "catalog-defaults"
    assert DraftRepository(db_session).get("prod") is None


def test_unknown_profile_is_404(client):
    response = client.get("/api/v1/profiles/nope/draft", headers=_auth(client))
    assert response.status_code == 404
    assert response.json()["code"] == "unknown_profile"
