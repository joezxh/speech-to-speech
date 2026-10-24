from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import demo as demo_settings
from app.main import create_app
from app.services import search_service


@pytest.fixture
def client(tmp_path, monkeypatch):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(root))
    monkeypatch.setattr(demo_settings, "serper_api_key", "")
    monkeypatch.setattr(demo_settings, "space_id", "")
    return TestClient(create_app())


@pytest.fixture
def serper(monkeypatch):
    """Records the payload/headers and answers with a canned Serper body."""
    calls = []

    async def fake_post(payload, key):
        calls.append((payload, key))
        return httpx.Response(
            200,
            json={
                "organic": [
                    {"title": "T", "snippet": "S", "link": "https://e.test/a"},
                    {"title": "T2", "snippet": "S2", "link": "https://e.test/b"},
                ],
                "answerBox": {"answer": "42"},
            },
            request=httpx.Request("POST", search_service.SERPER_URL),
        )

    monkeypatch.setattr(search_service, "_post", fake_post)
    return calls


def test_an_empty_query_is_400(client):
    response = client.post("/api/search", json={"query": "   "})
    assert response.status_code == 400
    # A.13 rule 1: FastAPI's own {"detail": …}, no envelope.
    assert set(response.json()) == {"detail"}


def test_nothing_configured_and_no_user_key_is_503(client):
    response = client.post("/api/search", json={"query": "weather"})
    assert response.status_code == 503


def test_the_user_supplied_key_is_used_and_never_echoed(client, serper):
    response = client.post("/api/search", json={"query": "weather", "key": "user-key"})
    assert response.status_code == 200
    assert serper == [([{"q": "weather", "num": 5}][0], "user-key")]
    assert "user-key" not in response.text


def test_a_server_key_on_a_space_requires_sign_in(client, monkeypatch, serper):
    monkeypatch.setattr(demo_settings, "serper_api_key", "paid")
    # `server_search` only spends the paid key once sign-in is actually possible
    # on the Space (demo/server.py:205); without OAuth the key is simply off (503).
    monkeypatch.setattr(demo_settings, "load_balancer_url", "https://lb.test")
    monkeypatch.setattr(demo_settings, "oauth_client_id", "client")
    monkeypatch.setattr(demo_settings, "space_id", "my-space")
    response = client.post("/api/search", json={"query": "weather"})
    # An anonymous identity is only an IP + a cookie, both cheap to rotate.
    assert response.status_code == 401
    assert serper == []


def test_the_direct_answer_and_results_are_flattened(client, serper):
    body = client.post("/api/search", json={"query": "weather", "key": "k"}).json()
    assert body["query"] == "weather"
    assert body["answer"] == "42"
    assert body["results"] == [
        {"title": "T", "snippet": "S", "url": "https://e.test/a"},
        {"title": "T2", "snippet": "S2", "url": "https://e.test/b"},
    ]


def test_a_provider_error_is_relayed_as_502(client, monkeypatch):
    async def failing(payload, key):
        return httpx.Response(
            403,
            json={"message": "Not enough credits"},
            request=httpx.Request("POST", search_service.SERPER_URL),
        )

    monkeypatch.setattr(search_service, "_post", failing)
    response = client.post("/api/search", json={"query": "weather", "key": "k"})
    assert response.status_code == 502
    assert "Not enough credits" in response.json()["detail"]
