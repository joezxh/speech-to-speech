from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import allocator, calls_service, instance_monitor, upstream_resolver
from app.services.instance_registry import RuntimeState
from app.services.pool import PoolState

OFFER = b"v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\n"
FULL_BODY = json.dumps({"type": "error", "error": {"type": "session_limit_reached"}})


@pytest.fixture
def dist(tmp_path, monkeypatch):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(root))
    return root


@pytest.fixture
def lb_proxy(monkeypatch):
    monkeypatch.setattr("app.main.console_settings.lb_mode", "proxy")
    instance_monitor.reset_for_tests()
    allocator.store._pending.clear()
    allocator.store._held.clear()
    upstream_resolver.reset_inflight()


def _register(instance_id: str, base_url: str, size: int = 4, in_use: int = 0) -> None:
    instance_monitor.registry._states[instance_id] = RuntimeState(
        instance_id=instance_id,
        base_url=base_url,
        capabilities=frozenset({"realtime"}),
    )
    instance_monitor.registry.observe_success(
        instance_id, PoolState(reachable=True, size=size, in_use=in_use, units=()), 5
    )


def _answer(url: str) -> httpx.Response:
    return httpx.Response(
        201,
        content=b"v=0\r\nanswer\r\n",
        headers={"content-type": "application/sdp", "location": "/v1/realtime/calls/c1"},
        request=httpx.Request("POST", url),
    )


def test_the_offer_reaches_the_selected_instance(dist, lb_proxy, monkeypatch):
    seen: list[str] = []

    async def fake(url, offer, **kwargs):
        seen.append(url)
        return _answer(url)

    _register("pipe-a", "http://pipe-a:8765")
    monkeypatch.setattr(calls_service, "_http", fake)
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/calls", content=OFFER, headers={"Content-Type": "application/sdp"}
        )
    assert response.status_code == 201
    assert seen == ["http://pipe-a:8765/v1/realtime/calls"]


def test_a_full_instance_is_retried_on_another_one(dist, lb_proxy, monkeypatch):
    seen: list[str] = []

    async def fake(url, offer, **kwargs):
        seen.append(url)
        if "pipe-a" in url:
            return httpx.Response(
                503,
                content=FULL_BODY.encode(),
                headers={"content-type": "application/json"},
                request=httpx.Request("POST", url),
            )
        return _answer(url)

    # pipe-a 更空闲（ratio 1.0 > 0.5），所以第一台必定是它；同分时是加权随机，
    # 顺序不可预测 —— 这里用不同负载把顺序定死。
    _register("pipe-a", "http://pipe-a:8765", size=4, in_use=0)
    _register("pipe-b", "http://pipe-b:8765", size=8, in_use=4)
    monkeypatch.setattr(calls_service, "_http", fake)
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/calls", content=OFFER, headers={"Content-Type": "application/sdp"}
        )
    assert response.status_code == 201
    assert seen == [
        "http://pipe-a:8765/v1/realtime/calls",
        "http://pipe-b:8765/v1/realtime/calls",
    ]


def test_the_same_origin_entry_also_selects_an_instance(dist, lb_proxy, monkeypatch):
    seen: list[str] = []

    async def fake(url, offer, **kwargs):
        seen.append(url)
        return _answer(url)

    _register("pipe-a", "http://pipe-a:8765")
    monkeypatch.setattr(calls_service, "_http", fake)
    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/realtime/calls", content=OFFER, headers={"Content-Type": "application/sdp"}
        )
    assert response.status_code == 201
    assert seen == ["http://pipe-a:8765/v1/realtime/calls"]
    # proxy 模式回填 Location：console 自己也注册了这条路径，浏览器拿得到。
    assert response.headers["location"] == "/v1/realtime/calls/c1"
