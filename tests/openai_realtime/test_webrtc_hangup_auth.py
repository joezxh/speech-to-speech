"""P1.6 强制项：挂断端点的 fail-closed Bearer 校验（spec §9.2/§16）。"""
from __future__ import annotations

from threading import Event
from types import SimpleNamespace

from fastapi.testclient import TestClient

from speech_to_speech.api.openai_realtime.websocket_router import create_app


class _Transport:
    kind = "webrtc"

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _unit_with_call(call_id: str) -> SimpleNamespace:
    transport = _Transport()
    session = SimpleNamespace(session_id=call_id, released_at=None, transport=transport)
    return SimpleNamespace(index=0, session=session, transport=transport)


def _client(call_id="call-1"):
    return TestClient(create_app([_unit_with_call(call_id)], Event()))


def test_missing_token_env_is_fail_closed_503(monkeypatch):
    monkeypatch.delenv("S2S_ADMIN_TOKEN", raising=False)
    response = _client().delete("/v1/realtime/calls/call-1")
    assert response.status_code == 503


def test_wrong_token_is_401(monkeypatch):
    monkeypatch.setenv("S2S_ADMIN_TOKEN", "expected")
    response = _client().delete("/v1/realtime/calls/call-1", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401


def test_valid_token_hangs_up_200(monkeypatch):
    monkeypatch.setenv("S2S_ADMIN_TOKEN", "expected")
    response = _client().delete("/v1/realtime/calls/call-1", headers={"Authorization": "Bearer expected"})
    assert response.status_code == 200


def test_valid_token_unknown_call_404(monkeypatch):
    monkeypatch.setenv("S2S_ADMIN_TOKEN", "expected")
    response = _client().delete("/v1/realtime/calls/nope", headers={"Authorization": "Bearer expected"})
    assert response.status_code == 404
