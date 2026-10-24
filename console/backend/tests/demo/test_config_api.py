from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config import demo as demo_settings
from app.main import create_app

KEYS = {
    "search",
    "lb",
    "allowDirect",
    "s2sUrl",
    "rtc",
    "iceServers",
    "startupGreeting",
    "auth",
}


@pytest.fixture
def client(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))
    return TestClient(create_app())


def test_config_is_a_bare_object_and_needs_no_token(client):
    response = client.get("/api/config")
    assert response.status_code == 200
    body = response.json()
    # A.13 rule 1: the demo face never carries the /api/v1 envelope.
    assert "code" not in body and "data" not in body
    assert set(body) == KEYS


def test_config_never_returns_the_load_balancer_address(client, monkeypatch):
    monkeypatch.setattr(demo_settings, "load_balancer_url", "http://lb.internal:9000")
    monkeypatch.setattr(demo_settings, "speech_to_speech_url", "")
    body = client.get("/api/config").json()
    assert body["lb"] is True
    assert body["allowDirect"] is False
    assert "lb.internal" not in json.dumps(body)


def test_a_pinned_direct_url_turns_the_load_balancer_off(client, monkeypatch):
    monkeypatch.setattr(demo_settings, "load_balancer_url", "http://lb.internal:9000")
    monkeypatch.setattr(demo_settings, "speech_to_speech_url", "ws://127.0.0.1:8765/v1/realtime")
    body = client.get("/api/config").json()
    # demo/server.py:80-81: a pinned URL wins and every LB branch is disabled.
    assert body["lb"] is False
    assert body["allowDirect"] is True
    assert body["s2sUrl"] == "ws://127.0.0.1:8765/v1/realtime"
    assert body["rtc"] is True
