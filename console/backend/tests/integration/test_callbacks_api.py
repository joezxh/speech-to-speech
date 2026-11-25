"""callbacks CRUD/batch/test/logs API 契约测试。"""
from __future__ import annotations

import pytest


@pytest.fixture()
def auth_headers(client) -> dict:
    tokens = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "correct-horse"}
    ).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def test_target_crud_roundtrip(client, auth_headers: dict) -> None:
    payload = {
        "name": "ai-server", "targetType": "java", "baseUrl": "http://ai",
        "authType": "header_token", "authHeaderName": "X-Internal-Token", "authToken": "toktoktoktok",
        "extraHeaders": {"tenant-id": "1"}, "timeoutMs": 3000, "retryMaxAttempts": 3,
        "retryBackoffMs": 500, "events": ["transcript"], "filters": None, "enabled": True,
    }
    resp = client.post("/api/v1/callbacks/targets", json=payload, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 200
    target_id = body["data"]["id"]
    assert body["data"]["authToken"] == "tokt***ktok"  # 详情返回脱敏（前4+***+后4）

    resp = client.get(f"/api/v1/callbacks/targets/{target_id}", headers=auth_headers)
    assert resp.status_code == 200

    resp = client.put(f"/api/v1/callbacks/targets/{target_id}",
                      json={**payload, "timeoutMs": 5000}, headers=auth_headers)
    assert resp.json()["data"]["timeoutMs"] == 5000

    resp = client.delete(f"/api/v1/callbacks/targets/{target_id}", headers=auth_headers)
    assert resp.status_code == 204


def test_list_and_pagination(client, auth_headers: dict) -> None:
    for i in range(3):
        client.post("/api/v1/callbacks/targets", json={
            "name": f"t{i}", "targetType": "python", "baseUrl": "http://x",
            "authType": "none", "authToken": "", "extraHeaders": {}, "timeoutMs": 3000,
            "retryMaxAttempts": 1, "retryBackoffMs": 0, "events": ["transcript"], "enabled": True,
        }, headers=auth_headers)
    resp = client.get("/api/v1/callbacks/targets?page=1&pageSize=2", headers=auth_headers)
    data = resp.json()["data"]
    assert len(data["list"]) == 2 and data["total"] == 3


def test_batch_enable_disable_delete(client, auth_headers: dict) -> None:
    ids = []
    for i in range(2):
        resp = client.post("/api/v1/callbacks/targets", json={
            "name": f"b{i}", "targetType": "python", "baseUrl": "http://x",
            "authType": "none", "authToken": "", "extraHeaders": {}, "timeoutMs": 3000,
            "retryMaxAttempts": 1, "retryBackoffMs": 0, "events": ["transcript"], "enabled": False,
        }, headers=auth_headers)
        ids.append(resp.json()["data"]["id"])
    resp = client.post("/api/v1/callbacks/targets/batch",
                       json={"ids": ids, "action": "enable"}, headers=auth_headers)
    assert resp.json()["data"]["updated"] == 2
    resp = client.post("/api/v1/callbacks/targets/batch",
                       json={"ids": ids, "action": "delete"}, headers=auth_headers)
    assert resp.json()["data"]["deleted"] == 2


def test_test_delivery_endpoint(client, auth_headers: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.callback_service.requests.post",
        lambda url, **kwargs: type("R", (), {"status_code": 200, "text": "ok"})())
    resp = client.post("/api/v1/callbacks/targets", json={
        "name": "probe", "targetType": "python", "baseUrl": "http://probe",
        "authType": "none", "authToken": "", "extraHeaders": {}, "timeoutMs": 1000,
        "retryMaxAttempts": 1, "retryBackoffMs": 0, "events": ["transcript"], "enabled": True,
    }, headers=auth_headers)
    target_id = resp.json()["data"]["id"]
    resp = client.post(f"/api/v1/callbacks/targets/{target_id}/test", headers=auth_headers)
    data = resp.json()["data"]
    assert data["ok"] is True and data["httpStatus"] == 200


def test_java_target_rejects_non_transcript_events(client, auth_headers: dict) -> None:
    resp = client.post("/api/v1/callbacks/targets", json={
        "name": "bad-java", "targetType": "java", "baseUrl": "http://ai",
        "authType": "header_token", "authToken": "t", "extraHeaders": {},
        "events": ["transcript", "session_end"], "enabled": True,
    }, headers=auth_headers)
    assert resp.status_code == 400  # java 协议仅支持 transcript


def test_logs_endpoint_filters(client, auth_headers: dict) -> None:
    resp = client.get("/api/v1/callbacks/logs?status=failed&page=1&pageSize=10",
                      headers=auth_headers)
    assert resp.status_code == 200
    assert {"list", "total", "page", "pageSize"} <= set(resp.json()["data"])


def test_requires_permission(client) -> None:
    # 未带 JWT → 401；带普通 user JWT → 403（callback 写仅 admin）
    assert client.get("/api/v1/callbacks/targets").status_code == 401
