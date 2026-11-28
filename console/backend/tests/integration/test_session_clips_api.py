"""会话音频片段 HTTP 契约：multipart 上传、字节回放、详情 clips 概要、越界/鉴权。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.database import get_db
from app.main import create_app
from app.repositories.user_repository import UserRepository
from app.services.auth_service import hash_password

# 最小合法 WAV：RIFF 头 + 4 字节伪数据（回放端点只透传字节，不做音频解码）。
_WAV_BYTES = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00" + b"\x00" * 8


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    UserRepository(db_session).create("alice", hash_password("correct-horse"), "admin")
    yield TestClient(app)


def _auth(client: TestClient, username: str = "alice") -> dict:
    tokens = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "correct-horse"}
    ).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def _save_record(client: TestClient, headers: dict) -> dict:
    payload = {
        "title": "片段冒烟",
        "note": "",
        "pipelineSessionId": "sess-clip-1",
        "instanceId": "pipe-a",
        "node": "local-split2",
        "state": "done",
        "turns": 1,
        "durationMs": 4200,
        "ttfaMs": 660,
        "messages": [
            {"role": "user", "type": "audio", "content": "你好"},
            {"role": "assistant", "type": "text", "content": "你好，需要什么帮助？"},
        ],
    }
    saved = client.post("/api/v1/session-records", json=payload, headers=headers)
    assert saved.status_code == 200
    return saved.json()["data"]


def _clip_files(**overrides) -> dict:
    files = {"file": ("turn.wav", _WAV_BYTES, "audio/wav")}
    data = {"message_ordinal": "0", "role": "user", "item_ref": "item-1", "sample_rate": "24000", "duration_ms": "1800"}
    data.update(overrides)
    return {"files": files, "data": data}


def test_clip_upload_and_bytes_roundtrip(client):
    headers = _auth(client)
    record = _save_record(client, headers)
    up = client.post(f"/api/v1/session-records/{record['id']}/clips", headers=headers, **_clip_files())
    assert up.status_code == 200
    clip = up.json()["data"]
    assert clip["role"] == "user"
    assert clip["messageOrdinal"] == 0
    assert clip["durationMs"] == 1800
    assert clip["sizeBytes"] == len(_WAV_BYTES)
    assert "data" not in clip  # 概要不含字节

    got = client.get(f"/api/v1/session-records/{record['id']}/clips/{clip['id']}", headers=headers)
    assert got.status_code == 200
    assert got.headers["content-type"].startswith("audio/wav")
    assert got.content == _WAV_BYTES

    detail = client.get(f"/api/v1/session-records/{record['id']}", headers=headers).json()["data"]
    assert [c["id"] for c in detail["clips"]] == [clip["id"]]
    assert all("data" not in c for c in detail["clips"])


def test_clip_upload_rejects_over_size(client):
    headers = _auth(client)
    record = _save_record(client, headers)
    big = b"RIFF" + b"\x00" * (8 * 1024 * 1024 + 1)
    files = {"file": ("big.wav", big, "audio/wav")}
    resp = client.post(f"/api/v1/session-records/{record['id']}/clips", headers=headers, files=files,
                       data={"messageOrdinal": "0", "role": "user", "itemRef": "x"})
    assert resp.status_code == 400
    # 记录仍在：上传失败不影响已保存记录。
    got = client.get(f"/api/v1/session-records/{record['id']}", headers=headers)
    assert got.status_code == 200


def test_clip_upload_rejects_bad_role(client):
    headers = _auth(client)
    record = _save_record(client, headers)
    resp = client.post(f"/api/v1/session-records/{record['id']}/clips", headers=headers,
                       **_clip_files(role="tool"))
    assert resp.status_code == 400


def test_clip_download_unknown_clip_404(client):
    headers = _auth(client)
    record = _save_record(client, headers)
    resp = client.get(f"/api/v1/session-records/{record['id']}/clips/9999", headers=headers)
    assert resp.status_code == 404


def test_clip_endpoints_require_auth(client):
    record = _save_record(client, _auth(client))
    assert client.post(f"/api/v1/session-records/{record['id']}/clips").status_code == 401
    assert client.get(f"/api/v1/session-records/{record['id']}/clips/1").status_code == 401


def test_clip_download_404_when_record_missing(client):
    resp = client.get("/api/v1/session-records/424242/clips/1", headers=_auth(client))
    assert resp.status_code == 404
