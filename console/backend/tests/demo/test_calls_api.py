from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import demo as demo_settings
from app.main import create_app
from app.services import calls_service

OFFER = b"v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\n"


@pytest.fixture
def client(tmp_path, monkeypatch):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(root))
    return TestClient(create_app())


@pytest.fixture
def upstream(monkeypatch):
    calls = []

    async def fake(url, offer):
        calls.append((url, offer))
        return httpx.Response(
            201, content=b"v=0\r\nanswer\r\n",
            headers={"content-type": "application/sdp", "location": "http://s2s.test/v1/realtime/calls/call_1"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(calls_service, "_http", fake)
    return calls


def test_without_a_pinned_url_the_route_is_404(client):
    response = client.post("/api/calls", content=OFFER, headers={"Content-Type": "application/sdp"})
    # A.13 rule 3: indistinguishable from a missing route.
    assert response.status_code == 404


def test_the_offer_is_relayed_to_the_pinned_url(client, monkeypatch, upstream):
    monkeypatch.setattr(demo_settings, "speech_to_speech_url", "ws://s2s.test:8765/v1/realtime")
    response = client.post("/api/calls", content=OFFER, headers={"Content-Type": "application/sdp"})
    assert response.status_code == 201
    assert response.content == b"v=0\r\nanswer\r\n"
    assert upstream == [("http://s2s.test:8765/v1/realtime/calls", OFFER)]


def test_the_upstream_location_header_is_kept(client, monkeypatch, upstream):
    monkeypatch.setattr(demo_settings, "speech_to_speech_url", "ws://s2s.test:8765/v1/realtime")
    response = client.post("/api/calls", content=OFFER, headers={"Content-Type": "application/sdp"})
    # The call id lives in Location; the pinned target is dialable by the browser.
    assert response.headers["location"].endswith("/call_1")


def test_an_unreachable_upstream_is_502(client, monkeypatch):
    async def boom(url, offer):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(demo_settings, "speech_to_speech_url", "ws://s2s.test:8765/v1/realtime")
    monkeypatch.setattr(calls_service, "_http", boom)
    response = client.post("/api/calls", content=OFFER, headers={"Content-Type": "application/sdp"})
    assert response.status_code == 502


def test_the_call_url_is_derived_from_the_realtime_url():
    assert calls_service.handshake_url("ws://h:8765/v1/realtime") == "http://h:8765/v1/realtime/calls"
    assert calls_service.handshake_url("wss://h/realtime") == "https://h/realtime/calls"
    assert calls_service.handshake_url("h:8765") == "http://h:8765/v1/realtime/calls"
