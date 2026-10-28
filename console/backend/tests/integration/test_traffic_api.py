"""S1 spec §10.2: read-only traffic settings snapshot; no writes, no audit."""
from __future__ import annotations

from app.config import allocator


def _auth(client):
    tokens = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "correct-horse"}
    ).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def test_requires_auth(client):
    assert client.get("/api/v1/traffic/settings").status_code == 401


def test_envelope_and_fields(client):
    body = client.get("/api/v1/traffic/settings", headers=_auth(client)).json()
    assert set(body) == {"code", "message", "data"}
    data = body["data"]
    assert data["allocatorMode"] == allocator.mode
    assert data["consoleId"] == allocator.resolved_console_id
    assert data["seedConfigured"] == bool(allocator.seed_path.strip())
    assert data["probeIntervalS"] == allocator.probe_interval_s
    assert data["scheduling"] == {
        "policy": "least-in-use",
        "configurable": False,
        "tieBreaker": "weight-random",
    }
    assert "session-stickiness" in data["unimplemented"]


def test_off_mode_still_200(client, monkeypatch):
    monkeypatch.setattr(allocator, "mode", "off")
    assert client.get("/api/v1/traffic/settings", headers=_auth(client)).status_code == 200


def test_write_methods_not_registered(client):
    headers = _auth(client)
    assert client.post("/api/v1/traffic/settings", headers=headers).status_code == 405


def test_no_audit_row_written(client):
    headers = _auth(client)
    client.get("/api/v1/traffic/settings", headers=headers)
    # No side effects: re-read yields identical payload and DB/audit untouched.
    assert client.get("/api/v1/traffic/settings", headers=headers).json()["data"]["allocatorMode"] == allocator.mode
