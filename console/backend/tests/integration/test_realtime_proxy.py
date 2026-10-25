from __future__ import annotations

import concurrent.futures
import contextlib
import socket
import threading

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.sync.server import serve

from app.main import create_app
from app.services import calls_service

OFFER = b"v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\n"


@contextlib.contextmanager
def realtime_socket(client: TestClient):
    """A `/v1/realtime` socket whose teardown race cannot masquerade as a failure.

    `TestClient.websocket_connect` runs the ASGI app in a blocking portal and, on
    exit, cancels it before waiting for its task. When the handler is still
    closing the upstream socket, the cancellation can land first and
    `Future.result()` then raises `CancelledError` from the *exit*, not from
    anything the test asserted (load and Windows/py3.14 widen that window).
    Suppressing exactly that keeps the assertions honest; an exception raised
    inside the `with` body still propagates.
    """
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
def pipeline():
    """A real echo server on a free port, driven from its own thread.

    The sync server keeps the fixture out of asyncio entirely: no second event
    loop to stop, and `shutdown()` closes open connections before the test ends.
    """
    raw = socket.socket()
    raw.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    raw.bind(("127.0.0.1", 0))
    raw.listen()
    port = raw.getsockname()[1]

    def echo(websocket):
        for message in websocket:
            websocket.send(message)

    server = serve(echo, sock=raw, subprotocols=["realtime"])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    thread.join(timeout=5)


def test_a_frame_round_trips(dist, pipeline, monkeypatch):
    monkeypatch.setattr("app.main.console_settings.pipeline_base_url", pipeline)
    with TestClient(create_app()) as client:
        # The echo server insists on the `realtime` subprotocol (websockets >= 14
        # rejects the handshake otherwise), which is what the browser SDK asks for.
        with realtime_socket(client) as ws:
            ws.send_text("hello")
            assert ws.receive_text() == "hello"


def test_the_realtime_subprotocol_is_forwarded(dist, pipeline, monkeypatch):
    monkeypatch.setattr("app.main.console_settings.pipeline_base_url", pipeline)
    with TestClient(create_app()) as client:
        with realtime_socket(client) as ws:
            assert ws.accepted_subprotocol == "realtime"


def test_an_unreachable_pipeline_fails_the_handshake(dist, monkeypatch):
    # Nothing listens on this port; the client must not be left holding an open socket.
    monkeypatch.setattr("app.main.console_settings.pipeline_base_url", "http://127.0.0.1:1")
    with TestClient(create_app()) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/v1/realtime"):
                pass


def test_the_sdp_offer_goes_to_loopback_without_a_location(dist, monkeypatch):
    seen = []

    async def fake(url, offer):
        seen.append((url, offer))
        return httpx.Response(
            201,
            content=b"v=0\r\nanswer\r\n",
            headers={"content-type": "application/sdp", "location": "http://127.0.0.1:8765/v1/realtime/calls/c1"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("app.main.console_settings.pipeline_base_url", "http://127.0.0.1:8765")
    monkeypatch.setattr(calls_service, "_http", fake)
    with TestClient(create_app()) as client:
        response = client.post("/v1/realtime/calls", content=OFFER, headers={"Content-Type": "application/sdp"})
    assert response.status_code == 201
    assert seen == [("http://127.0.0.1:8765/v1/realtime/calls", OFFER)]
    # A loopback Location would be undialable for the browser (spec §10.2.3).
    assert "location" not in response.headers
