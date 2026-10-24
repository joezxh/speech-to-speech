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
    return root


@pytest.fixture
def metered(tmp_path, monkeypatch):
    monkeypatch.setattr(demo_settings, "load_balancer_url", "http://lb.internal:9000")
    monkeypatch.setattr(demo_settings, "space_id", "my-space")
    monkeypatch.setattr(demo_settings, "speech_to_speech_url", "")
    monkeypatch.setattr("app.config.database.usage_db_path", str(tmp_path / "usage.sqlite3"))


def _stub(monkeypatch, status: int, payload: dict, calls: list):
    async def fake(method, url, **kwargs):
        calls.append((method, url))
        return httpx.Response(status, json=payload, request=httpx.Request(method, url))

    monkeypatch.setattr(lb_service, "_http", fake)


def test_queue_routes_are_404_without_a_load_balancer(dist):
    with TestClient(create_app()) as client:
        assert client.get("/api/queue/q1").status_code == 404
        assert client.delete("/api/queue/q1").status_code == 404
        assert client.post("/api/queue/end", json={"queueId": "q1"}).status_code == 404


def test_a_waiting_ticket_is_relayed_with_the_tier(dist, metered, monkeypatch):
    calls: list = []
    _stub(monkeypatch, 200, {"state": "queued", "position": 2}, calls)
    with TestClient(create_app()) as client:
        body = client.get("/api/queue/q1").json()
    assert body == {"state": "queued", "position": 2, "tier": "anon"}
    assert calls[0][0] == "GET" and calls[0][1].endswith("/queue/q1")


def test_an_unknown_ticket_tells_the_client_to_start_over(dist, metered, monkeypatch):
    _stub(monkeypatch, 404, {}, [])
    with TestClient(create_app()) as client:
        response = client.get("/api/queue/gone")
    assert response.status_code == 404
    assert response.json() == {"state": "expired"}


def test_a_claim_rechecks_the_budget(dist, metered, monkeypatch):
    # The LB hands over a slot; the budget was spent in another tab during the wait.
    _stub(monkeypatch, 200, {"state": "granted", "session_id": "s-9"}, [])
    monkeypatch.setattr(metering_service, "remaining", lambda keys, tier: 0)
    with TestClient(create_app()) as client:
        response = client.get("/api/queue/q1")
    assert response.status_code == 402
    assert response.json()["reason"] == "limit"


def test_leaving_the_queue_calls_the_lb(dist, metered, monkeypatch):
    calls: list = []
    _stub(monkeypatch, 200, {}, calls)
    with TestClient(create_app()) as client:
        assert client.delete("/api/queue/q1").json() == {"ok": True}
        assert client.post("/api/queue/end", json={"queueId": "q2"}).json() == {"ok": True}
    assert [c[0] for c in calls] == ["DELETE", "DELETE"]
    assert calls[1][1].endswith("/queue/q2")
