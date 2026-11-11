"""The console's machine-to-machine fanout endpoint (spec §5.1 / A.12)."""

from __future__ import annotations

from threading import Event
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from speech_to_speech.api.openai_realtime.websocket_router import create_app

ENDPOINT = "/internal/sessions/update"


class _SessionStub:
    """Records fanout instead of touching a real pipeline."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.reject: set[str] = set()

    def handle_session_update(self, conn_id, event):
        self.calls.append(conn_id)
        if conn_id in self.reject:
            return SimpleNamespace(error=SimpleNamespace(code="invalid_request_error"))
        return None


class _ServiceStub:
    def __init__(self, conn_ids) -> None:
        self._conns = {cid: object() for cid in conn_ids}
        self.session = _SessionStub()

    def active_connection_ids(self):
        return list(self._conns)


def _unit(index: int, session_id: str, conn_ids):
    return SimpleNamespace(index=index, session=SimpleNamespace(session_id=session_id), service=_ServiceStub(conn_ids))


@pytest.fixture
def client():
    return TestClient(create_app([], Event()))


def test_missing_token_env_is_fail_closed(client, monkeypatch):
    monkeypatch.delenv("S2S_INTERNAL_TOKEN", raising=False)
    response = client.post(ENDPOINT, json={"scope": "all", "session": {"instructions": "hi"}})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "internal_token_missing"


def test_wrong_token_is_401(client, monkeypatch):
    monkeypatch.setenv("S2S_INTERNAL_TOKEN", "expected")
    response = client.post(
        ENDPOINT,
        json={"scope": "all", "session": {"instructions": "hi"}},
        headers={"Authorization": "Bearer nope"},
    )
    assert response.status_code == 401


def test_empty_pool_returns_empty_fanout(client, monkeypatch):
    monkeypatch.setenv("S2S_INTERNAL_TOKEN", "tok")
    response = client.post(
        ENDPOINT,
        json={"scope": "all", "session": {"instructions": "hi"}},
        headers={"Authorization": "Bearer tok"},
    )
    assert response.status_code == 200
    assert response.json() == {"updated": [], "failed": []}


def test_scope_session_touches_only_the_named_connection(monkeypatch):
    monkeypatch.setenv("S2S_INTERNAL_TOKEN", "tok")
    unit = _unit(0, "s1", ["s1", "s2"])
    app = create_app([unit], Event())
    response = TestClient(app).post(
        ENDPOINT,
        json={"scope": "session", "target": "s1", "session": {"instructions": "hi"}},
        headers={"Authorization": "Bearer tok"},
    )
    assert response.status_code == 200
    assert response.json()["updated"] == ["s1"]
    assert unit.service.session.calls == ["s1"]


def test_scope_all_reports_partial_failures(monkeypatch):
    monkeypatch.setenv("S2S_INTERNAL_TOKEN", "tok")
    unit = _unit(0, "s1", ["s1", "s2"])
    unit.service.session.reject.add("s2")
    app = create_app([unit], Event())
    body = (
        TestClient(app)
        .post(
            ENDPOINT,
            json={"scope": "all", "session": {"instructions": "hi"}},
            headers={"Authorization": "Bearer tok"},
        )
        .json()
    )
    assert body["updated"] == ["s1"]
    assert body["failed"] == [{"session_id": "s2", "error": "invalid_request_error"}]
