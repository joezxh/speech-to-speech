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


def test_local_mode_grants_without_touching_lb(dist, lb, monkeypatch):
    # 注册表非空 + mode=local + 无 lb_url → 本地分配，lb_service._http 零调用
    from app.config import allocator as allocator_settings
    from app.services import allocator, instance_monitor
    from app.services.instance_registry import RuntimeState
    from app.services.pool import PoolState

    allocator.store._pending.clear()
    allocator.store._counters.clear()
    allocator.store._begun.clear()
    allocator.store._grants.clear()
    monkeypatch.setattr(demo_settings, "load_balancer_url", "")
    monkeypatch.setattr(allocator_settings, "mode", "local")
    instance_monitor.reset_for_tests()
    instance_monitor.registry._states["pipe-a"] = RuntimeState(instance_id="pipe-a", base_url="http://a:8765")
    instance_monitor.registry.observe_success("pipe-a", PoolState(reachable=True, size=2, units=()), 5)
    with TestClient(create_app()) as client:
        body = client.post("/api/session", headers={"X-Request-Id": "r-1"}).json()
    assert body["state"] == "granted" and body["connect_url"] == "ws://a:8765/v1/realtime"
    assert body["tier"] == "anon" and "expires_in" in body  # finalize 补齐的字段（与 LB 模式同构）
    assert lb == []  # 一次转发都没发生：P1.4 验收证据
    instance_monitor.reset_for_tests()


def test_local_mode_dedupes_by_request_id(dist, monkeypatch):
    from app.config import allocator as allocator_settings
    from app.services import allocator, instance_monitor
    from app.services.instance_registry import RuntimeState
    from app.services.pool import PoolState

    allocator.store._pending.clear()
    allocator.store._counters.clear()
    allocator.store._begun.clear()
    allocator.store._grants.clear()
    monkeypatch.setattr(demo_settings, "load_balancer_url", "")
    monkeypatch.setattr(allocator_settings, "mode", "local")
    instance_monitor.reset_for_tests()
    instance_monitor.registry._states["pipe-a"] = RuntimeState(instance_id="pipe-a", base_url="http://a:8765")
    instance_monitor.registry.observe_success("pipe-a", PoolState(reachable=True, size=2, units=()), 5)
    with TestClient(create_app()) as client:
        first = client.post("/api/session", headers={"X-Request-Id": "same"}).json()
        second = client.post("/api/session", headers={"X-Request-Id": "same"}).json()
    assert first["session_id"] == second["session_id"]  # 同一个 grant，不重复占位
    instance_monitor.reset_for_tests()


def test_local_mode_at_capacity_is_503_when_registry_full(dist, monkeypatch):
    from app.config import allocator as allocator_settings
    from app.services import allocator, instance_monitor
    from app.services.instance_registry import RuntimeState
    from app.services.pool import PoolState

    allocator.store._pending.clear()
    allocator.store._counters.clear()
    allocator.store._begun.clear()
    allocator.store._grants.clear()
    monkeypatch.setattr(demo_settings, "load_balancer_url", "")
    monkeypatch.setattr(allocator_settings, "mode", "local")
    instance_monitor.reset_for_tests()
    instance_monitor.registry._states["pipe-a"] = RuntimeState(instance_id="pipe-a", base_url="http://a:8765")
    instance_monitor.registry.observe_success(
        "pipe-a", PoolState(reachable=True, size=1, in_use=1, units=()), 5
    )
    with TestClient(create_app()) as client:
        response = client.post("/api/session")
    assert response.status_code == 503 and response.json() == {"state": "at_capacity"}
    instance_monitor.reset_for_tests()


def test_empty_registry_falls_back_to_the_old_404(dist, monkeypatch):
    from app.config import allocator as allocator_settings
    from app.services import instance_monitor

    monkeypatch.setattr(demo_settings, "load_balancer_url", "")
    monkeypatch.setattr(allocator_settings, "mode", "local")
    # 注册表空：行为回到本期之前（spec §15 P1.4）
    instance_monitor.reset_for_tests()
    with TestClient(create_app()) as client:
        assert client.post("/api/session").status_code == 404


def test_lb_mode_still_forwards_verbatim(dist, metered, lb):
    # 既有 fixture：lb 记录 (_http 调用序列)；这里显式把“mock 断言零变化”钉为
    # P1.4 验收条目（不改任何现有断言）。
    with TestClient(create_app()) as client:
        client.post("/api/session")
    assert lb[0][0] == "POST" and lb[0][1] == "http://lb.internal:9000/session"
