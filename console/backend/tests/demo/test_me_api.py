from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import demo as demo_settings
from app.main import create_app
from app.services import identity_service


@pytest.fixture
def dist(tmp_path, monkeypatch):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(root))
    return root


@pytest.fixture
def metered(tmp_path, monkeypatch):
    """An LB + a Space id is exactly what turns metering on (demo/server.py:88)."""
    monkeypatch.setattr(demo_settings, "load_balancer_url", "http://lb.internal:9000")
    monkeypatch.setattr(demo_settings, "space_id", "my-space")
    monkeypatch.setattr(demo_settings, "speech_to_speech_url", "")
    monkeypatch.setattr("app.config.database.usage_db_path", str(tmp_path / "usage.sqlite3"))


def test_without_metering_the_body_is_just_enabled_false(dist):
    response = TestClient(create_app()).get("/api/me")
    assert response.status_code == 200
    assert response.json() == {"enabled": False}


def test_an_anonymous_visitor_gets_the_anon_budget_and_a_cookie(dist, metered):
    # The lifespan is what runs metering_service.init(); without `with` it never runs.
    with TestClient(create_app()) as client:
        response = client.get("/api/me")
    body = response.json()
    assert body["enabled"] is True
    assert body["loggedIn"] is False and body["tier"] == "anon"
    assert body["limitSec"] == 300 and body["remainingSec"] == 300
    # No OAUTH_CLIENT_ID in tests, so there is nothing to log in to.
    assert body["auth"] is False and body["loginUrl"] is None and body["logoutUrl"] is None
    # A.13 rule 1: no envelope on the demo face.
    assert "code" not in body and "data" not in body
    cookies = response.headers.get_list("set-cookie")
    assert any(identity_service.ANON_COOKIE + "=" in value for value in cookies)


def test_a_forged_anon_cookie_is_replaced(dist, metered):
    with TestClient(create_app()) as client:
        response = client.get("/api/me", cookies={identity_service.ANON_COOKIE: "forged.nope"})
    minted = [v for v in response.headers.get_list("set-cookie") if identity_service.ANON_COOKIE + "=" in v]
    assert minted, "a forged cookie must be replaced with a fresh signed one"
    assert "forged.nope" not in minted[0]
