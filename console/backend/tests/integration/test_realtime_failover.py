from __future__ import annotations

import concurrent.futures
import contextlib
import json
import socket
import threading

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.sync.server import serve

from app.main import create_app
from app.services import allocator, instance_monitor, upstream_resolver
from app.services.instance_registry import RuntimeState
from app.services.pool import PoolState

FULL_FRAME = json.dumps(
    {"type": "error", "error": {"type": "session_limit_reached", "message": "full"}}
)
CREATED_FRAME = json.dumps(
    {"type": "session.created", "event_id": "e2", "session": {"id": "s-remote"}}
)


@contextlib.contextmanager
def realtime_socket(client: TestClient):
    """同 test_realtime_proxy：退出时的取消竞态不该伪装成失败。"""
    session = client.websocket_connect("/v1/realtime", subprotocols=["realtime"])
    ws = session.__enter__()
    try:
        yield ws
    finally:
        with contextlib.suppress(concurrent.futures.CancelledError):
            session.__exit__(None, None, None)


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
    monkeypatch.setattr("app.main.console_settings.lb_failover_attempts", 2)
    monkeypatch.setattr("app.main.console_settings.lb_upstream_ready_timeout_s", 5.0)
    instance_monitor.reset_for_tests()
    allocator.store._pending.clear()
    allocator.store._held.clear()
    upstream_resolver.reset_inflight()


def _serve(handler):
    """在随机端口上起一个真实 WS 服务端，返回 base_url 与停止函数。"""
    raw = socket.socket()
    raw.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    raw.bind(("127.0.0.1", 0))
    raw.listen()
    port = raw.getsockname()[1]
    server = serve(handler, sock=raw, subprotocols=["realtime"])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def stop():
        server.shutdown()
        thread.join(timeout=5)

    return f"http://127.0.0.1:{port}", stop


def _full_upstream(websocket):
    """满员的上游：握手成功后回 error 事件再关掉（对齐 pipeline 的行为）。"""
    websocket.send(FULL_FRAME)
    websocket.close()


def _healthy_upstream(websocket):
    websocket.send(CREATED_FRAME)
    for message in websocket:
        websocket.send(message)


def _register(instance_id: str, base_url: str, size: int = 4) -> None:
    instance_monitor.registry._states[instance_id] = RuntimeState(
        instance_id=instance_id,
        base_url=base_url,
        capabilities=frozenset({"realtime"}),
    )
    instance_monitor.registry.observe_success(
        instance_id, PoolState(reachable=True, size=size, in_use=0, units=()), 5
    )


def test_a_full_upstream_is_never_seen_by_the_browser(dist, lb_proxy):
    full_url, stop_full = _serve(_full_upstream)
    good_url, stop_good = _serve(_healthy_upstream)
    try:
        with TestClient(create_app()) as client:
            # 注册放在 TestClient 之后：proxy 模式的 lifespan 会先探一轮，
            # 而假上游只说 WS、不说 HTTP /v1/pool（spec §4.2）。
            _register("pipe-full", full_url)
            _register("pipe-good", good_url)
            with realtime_socket(client) as ws:
                first = ws.receive_text()
        # 浏览器只看到健康实例的 session.created，看不到上游的满员错误。
        assert "session.created" in first
        assert "session_limit_reached" not in first
    finally:
        stop_full()
        stop_good()


def test_the_frames_keep_flowing_after_the_failover(dist, lb_proxy):
    full_url, stop_full = _serve(_full_upstream)
    good_url, stop_good = _serve(_healthy_upstream)
    try:
        with TestClient(create_app()) as client:
            _register("pipe-full", full_url)
            _register("pipe-good", good_url)
            with realtime_socket(client) as ws:
                assert "session.created" in ws.receive_text()
                ws.send_text("hello")
                assert ws.receive_text() == "hello"
    finally:
        stop_full()
        stop_good()


def test_an_unreachable_upstream_fails_the_handshake(dist, lb_proxy):
    with TestClient(create_app()) as client:
        _register("pipe-dead", "http://127.0.0.1:1")
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/v1/realtime"):
                pass


def test_no_candidate_fails_the_handshake(dist, lb_proxy):
    # 注册表为空 → 没有候选 → 不 accept，直接握手失败。
    with TestClient(create_app()) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/v1/realtime"):
                pass


def test_every_upstream_being_full_still_hands_the_error_to_the_browser(dist, lb_proxy):
    # 全部实例都满：accept 后把上游的 error 事件原样交给浏览器 + close 1008，
    # 与今天直连 pipeline 的表现一致（前端零改动）。
    full_url, stop_full = _serve(_full_upstream)
    try:
        with TestClient(create_app()) as client:
            _register("pipe-full", full_url)
            with realtime_socket(client) as ws:
                first = ws.receive_text()
        assert "session_limit_reached" in first
    finally:
        stop_full()
