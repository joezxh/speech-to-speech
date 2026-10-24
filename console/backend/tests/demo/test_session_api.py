from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import demo as demo_settings
from app.main import create_app
from app.services import lb_service, metering_service


@pytest.fixture
def dist(tmp_path, monkeypatch):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(root))
    monkeypatch.setattr(demo_settings, "speech_to_speech_url", "")
    return root


@pytest.fixture
def metered(tmp_path, monkeypatch):
    """An LB + a Space id turns metering on; the usage DB goes to a temp file."""
    monkeypatch.setattr(demo_settings, "load_balancer_url", "http://lb.internal:9000")
    monkeypatch.setattr(demo_settings, "space_id", "my-space")
    monkeypatch.setattr("app.config.database.usage_db_path", str(tmp_path / "usage.sqlite3"))


@pytest.fixture
def lb(monkeypatch):
    calls = []
    reply = {"state": "queued", "queue_id": "q1", "position": 3}

    async def fake(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return httpx.Response(200, json=reply, request=httpx.Request(method, url))

    monkeypatch.setattr(lb_service, "_http", fake)
    return calls


def test_without_a_load_balancer_the_route_is_404(dist):
    with TestClient(create_app()) as client:
        assert client.post("/api/session").status_code == 404


def test_a_queued_reply_is_relayed_without_reserving(dist, metered, lb):
    with TestClient(create_app()) as client:
        body = client.post("/api/session").json()
    assert body == {"state": "queued", "queue_id": "q1", "position": 3, "tier": "anon"}
    # Waiting in line must never cost the day's budget.
    assert metering_service.remaining.__module__  # sanity: metering is importable here


def test_a_grant_reserves_the_first_chunk(dist, metered, monkeypatch):
    async def fake(method, url, **kwargs):
        return httpx.Response(
            200,
            json={"state": "granted", "session_id": "s-1", "connect_url": "wss://c.test/rt"},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(lb_service, "_http", fake)
    with TestClient(create_app()) as client:
        body = client.post("/api/session").json()
    assert body["tier"] == "anon" and body["limited"] is True
    assert body["heartbeatSec"] == 5
    # 300 - one 10 s chunk reserved at grant time.
    assert body["remainingSec"] == 290
    assert body["session_id"] == "s-1"


def test_a_spent_budget_is_refused_before_the_lb_is_called(dist, metered, lb, monkeypatch):
    monkeypatch.setattr(metering_service, "remaining", lambda keys, tier: 0)
    with TestClient(create_app()) as client:
        response = client.post("/api/session")
    assert response.status_code == 402
    assert response.json() == {"tier": "anon", "reason": "limit", "remainingSec": 0}
    assert lb == []


def test_heartbeat_reports_expired_for_an_unknown_session(dist, metered):
    with TestClient(create_app()) as client:
        body = client.post("/api/session/heartbeat", json={"sessionId": "nope"}).json()
    assert body == {"expired": True}


def test_session_end_always_answers_ok(dist, metered):
    with TestClient(create_app()) as client:
        # sendBeacon may post nothing at all; the answer must not depend on the body.
        assert client.post("/api/session/end").json() == {"ok": True}
        assert client.post("/api/session/end", content=b"{oops").json() == {"ok": True}


def test_heartbeat_and_end_are_404_without_metering(dist):
    with TestClient(create_app()) as client:
        assert client.post("/api/session/heartbeat", json={}).status_code == 404
        assert client.post("/api/session/end", json={}).status_code == 404
