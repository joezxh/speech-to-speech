"""会话记录管理面 HTTP 契约：保存、列表/详情、改标题、消息编辑/单删/清空、单删/批删、审计。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.database import get_db
from app.main import create_app
from app.models.param_audit import ParamAudit
from app.repositories.user_repository import UserRepository
from app.services.auth_service import hash_password


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


def _save_payload(**overrides) -> dict:
    payload = {
        "title": "",
        "note": "冒烟回灌",
        "pipelineSessionId": "sess-abc-1",
        "instanceId": "pipe-a",
        "node": "local-split2",
        "state": "done",
        "turns": 2,
        "durationMs": 15300,
        "ttfaMs": 660,
        "messages": [
            {"role": "user", "type": "audio", "content": "你好"},
            {"role": "assistant", "type": "text", "content": "你好，有什么可以帮你？"},
            {"role": "tool", "type": "text", "content": "search(...)"},
        ],
    }
    payload.update(overrides)
    return payload


def test_save_and_detail_roundtrip(client):
    headers = _auth(client)
    saved = client.post("/api/v1/session-records", json=_save_payload(), headers=headers)
    assert saved.status_code == 200
    data = saved.json()["data"]
    # 空标题落默认名；消息保持通话顺序。
    assert data["title"] == "未命名会话"
    assert data["userId"] == "alice"
    assert data["turns"] == 2 and data["ttfaMs"] == 660
    assert [m["role"] for m in data["messages"]] == ["user", "assistant", "tool"]
    assert data["messages"][0]["ordinal"] == 0

    got = client.get(f"/api/v1/session-records/{data['id']}", headers=headers).json()["data"]
    assert got["pipelineSessionId"] == "sess-abc-1"
    assert len(got["messages"]) == 3


def test_save_rejects_bad_state(client):
    resp = client.post("/api/v1/session-records", json=_save_payload(state="weird"), headers=_auth(client))
    assert resp.status_code == 400


def test_list_filters_and_pagination(client):
    headers = _auth(client)
    for index in range(3):
        client.post(
            "/api/v1/session-records",
            json=_save_payload(title=f"会话 {index}", state="failed" if index == 2 else "done"),
            headers=headers,
        )
    listed = client.get("/api/v1/session-records", params={"q": "会话", "pageSize": 2}, headers=headers)
    data = listed.json()["data"]
    assert data["total"] == 3
    assert len(data["list"]) == 2
    # created_at 同秒内按 id 倒序（新会话在前）。
    assert data["list"][0]["id"] > data["list"][1]["id"]

    failed_only = client.get("/api/v1/session-records", params={"state": "failed"}, headers=headers)
    assert failed_only.json()["data"]["total"] == 1


def test_stats(client):
    headers = _auth(client)
    client.post("/api/v1/session-records", json=_save_payload(), headers=headers)
    client.post("/api/v1/session-records", json=_save_payload(state="failed"), headers=headers)
    stats = client.get("/api/v1/session-records/stats", headers=headers).json()["data"]
    assert stats["total"] == 2 and stats["done"] == 1 and stats["failed"] == 1
    assert stats["turns"] == 4 and stats["avgDurationMs"] == 15300


def test_update_title_and_note(client):
    headers = _auth(client)
    record = client.post("/api/v1/session-records", json=_save_payload(), headers=headers).json()["data"]
    updated = client.patch(
        f"/api/v1/session-records/{record['id']}",
        json={"title": "周一调解", "note": "已归档"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["title"] == "周一调解"


def test_message_edit_delete_clear(client):
    headers = _auth(client)
    record = client.post("/api/v1/session-records", json=_save_payload(), headers=headers).json()["data"]
    mid = record["messages"][1]["id"]

    edited = client.patch(
        f"/api/v1/session-records/{record['id']}/messages/{mid}",
        json={"content": "（编辑）你好，请问需要什么帮助？"},
        headers=headers,
    )
    assert edited.status_code == 200
    assert edited.json()["data"]["content"].startswith("（编辑）")

    removed = client.delete(f"/api/v1/session-records/{record['id']}/messages/{mid}", headers=headers)
    assert removed.status_code == 204
    assert len(client.get(f"/api/v1/session-records/{record['id']}", headers=headers).json()["data"]["messages"]) == 2

    cleared = client.post(f"/api/v1/session-records/{record['id']}/messages/clear", headers=headers)
    assert cleared.json()["data"]["cleared"] == 2
    assert client.get(f"/api/v1/session-records/{record['id']}", headers=headers).json()["data"]["messages"] == []


def test_delete_and_batch_delete(client):
    headers = _auth(client)
    first = client.post("/api/v1/session-records", json=_save_payload(), headers=headers).json()["data"]
    second = client.post("/api/v1/session-records", json=_save_payload(), headers=headers).json()["data"]

    assert client.delete(f"/api/v1/session-records/{first['id']}", headers=headers).status_code == 204
    batch = client.post(
        "/api/v1/session-records/batch-delete", json={"ids": [second["id"]]}, headers=headers
    )
    assert batch.status_code == 200 and batch.json()["data"]["deleted"] == 1
    assert client.get("/api/v1/session-records", headers=headers).json()["data"]["total"] == 0


def test_batch_delete_empty_result_is_404(client):
    resp = client.post("/api/v1/session-records/batch-delete", json={"ids": [999]}, headers=_auth(client))
    assert resp.status_code == 404


def test_missing_record_is_404(client):
    headers = _auth(client)
    assert client.get("/api/v1/session-records/42", headers=headers).status_code == 404
    assert client.patch("/api/v1/session-records/42", json={"title": "x"}, headers=headers).status_code == 404


def test_requires_auth_and_permission(client, monkeypatch):
    assert client.get("/api/v1/session-records").status_code == 401
    headers = _auth(client)
    assert client.get("/api/v1/session-records", headers=headers).status_code == 200
    # 保存入口需要 write 码（登录即有）；未带 token 一律 401。
    assert client.post("/api/v1/session-records", json=_save_payload()).status_code == 401


def test_audit_actions_recorded(client, db_session):
    headers = _auth(client)
    record = client.post("/api/v1/session-records", json=_save_payload(), headers=headers).json()["data"]
    client.patch(f"/api/v1/session-records/{record['id']}", json={"title": "t"}, headers=headers)
    client.patch(
        f"/api/v1/session-records/{record['id']}/messages/{record['messages'][0]['id']}",
        json={"content": "x"},
        headers=headers,
    )
    actions = {row.action for row in db_session.query(ParamAudit).all()}
    assert {"session-record.save", "session-record.update", "message.update"} <= actions


def test_save_persists_message_status_and_duration(client):
    headers = _auth(client)
    payload = _save_payload(
        messages=[
            {"role": "user", "type": "audio", "content": "你好", "status": "ok", "durationMs": 4200},
            {"role": "assistant", "type": "text", "content": "", "status": "fail", "durationMs": 0},
        ]
    )
    data = client.post("/api/v1/session-records", json=payload, headers=headers).json()["data"]
    assert data["messageCount"] == 2
    assert data["messages"][0]["status"] == "ok" and data["messages"][0]["durationMs"] == 4200
    assert data["messages"][1]["status"] == "fail"


def test_save_rejects_bad_message_status(client):
    payload = _save_payload(messages=[{"role": "user", "content": "x", "status": "weird"}])
    assert client.post("/api/v1/session-records", json=payload, headers=_auth(client)).status_code == 400


def test_delete_message_recomputes_turns(client):
    headers = _auth(client)
    record = client.post("/api/v1/session-records", json=_save_payload(), headers=headers).json()["data"]
    # _save_payload 默认 3 条消息，assistant 只有 1 条（index 1）；删它后 turns 重算为 0。
    mid = record["messages"][1]["id"]
    assert client.delete(f"/api/v1/session-records/{record['id']}/messages/{mid}", headers=headers).status_code == 204
    got = client.get(f"/api/v1/session-records/{record['id']}", headers=headers).json()["data"]
    assert got["turns"] == 0
    assert got["messageCount"] == 2


def test_clear_messages_zeros_turns(client):
    headers = _auth(client)
    record = client.post("/api/v1/session-records", json=_save_payload(), headers=headers).json()["data"]
    client.post(f"/api/v1/session-records/{record['id']}/messages/clear", headers=headers)
    got = client.get(f"/api/v1/session-records/{record['id']}", headers=headers).json()["data"]
    assert got["turns"] == 0 and got["messageCount"] == 0 and got["excerpt"] == ""


def test_list_inst_range_and_excerpt(client):
    headers = _auth(client)
    client.post("/api/v1/session-records", json=_save_payload(instanceId="pipe-a", node="n1"), headers=headers)
    client.post("/api/v1/session-records", json=_save_payload(instanceId="pipe-b", node="n2"), headers=headers)

    data = client.get("/api/v1/session-records", params={"inst": "pipe-a"}, headers=headers).json()["data"]
    assert data["total"] == 1

    data = client.get("/api/v1/session-records", params={"range": "today"}, headers=headers).json()["data"]
    assert data["total"] == 2
    # from/to 与 range 并存：from/to 优先（未来日期 → 0 行）。
    data = client.get(
        "/api/v1/session-records", params={"range": "7d", "from_date": "2030-01-01"}, headers=headers
    ).json()["data"]
    assert data["total"] == 0

    row = client.get("/api/v1/session-records", headers=headers).json()["data"]["list"][0]
    assert row["messageCount"] == 3
    assert "你好" in row["excerpt"] and "search(...)" in row["excerpt"]

    # q 搜转写原文（EXISTS 消息 content）。
    data = client.get("/api/v1/session-records", params={"q": "有什么可以帮你"}, headers=headers).json()["data"]
    assert data["total"] == 2


def test_instances_endpoint(client):
    headers = _auth(client)
    client.post("/api/v1/session-records", json=_save_payload(instanceId="pipe-a", node="n1"), headers=headers)
    data = client.get("/api/v1/session-records/instances", headers=headers).json()["data"]
    assert {"instanceId": "pipe-a", "node": "n1"} in data


def test_stats_avg_ttfa(client):
    headers = _auth(client)
    client.post("/api/v1/session-records", json=_save_payload(), headers=headers)
    stats = client.get("/api/v1/session-records/stats", headers=headers).json()["data"]
    assert stats["avgTtfaMs"] == 660
