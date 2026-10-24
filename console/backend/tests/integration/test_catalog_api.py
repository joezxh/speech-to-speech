from pathlib import Path

import pytest

from app.config import console as console_settings

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parameter-catalog.min.yaml"


@pytest.fixture
def catalog_client(client, monkeypatch):
    monkeypatch.setattr(console_settings, "param_catalog_path", str(FIXTURE))
    return client


def _auth(client):
    tokens = client.post("/api/v1/auth/login", json={"username": "alice", "password": "correct-horse"}).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def test_catalog_needs_a_token(catalog_client):
    assert catalog_client.get("/api/v1/catalog").status_code == 401


def test_catalog_envelope_is_camelcase_and_entries_stay_snake_case(catalog_client):
    body = catalog_client.get("/api/v1/catalog", headers=_auth(catalog_client)).json()
    assert body["code"] == 200
    data = body["data"]
    assert data["generatedFrom"] == "tests@fixture"
    assert data["variantKeys"] == ["llm.model_name"]
    first = data["parameters"][0]
    assert first["key"] == "vad.min_silence_ms"
    # Catalog rows are the contract the frontend indexes by; never camelCased.
    assert first["source_ref"] == ""
    assert "sourceRef" not in first


def test_catalog_exposure_filter_takes_the_highest_level(catalog_client):
    data = catalog_client.get("/api/v1/catalog?exposure=basic,advanced", headers=_auth(catalog_client)).json()["data"]
    assert data["returned"] == 2


def test_unknown_exposure_is_400_invalid_parameter(catalog_client):
    response = catalog_client.get("/api/v1/catalog?exposure=secret", headers=_auth(catalog_client))
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_parameter"


def test_missing_catalog_is_503(catalog_client, monkeypatch, tmp_path):
    monkeypatch.setattr(console_settings, "param_catalog_path", str(tmp_path / "nope.yaml"))
    response = catalog_client.get("/api/v1/catalog", headers=_auth(catalog_client))
    assert response.status_code == 503
    assert response.json()["code"] == "catalog_unavailable"
