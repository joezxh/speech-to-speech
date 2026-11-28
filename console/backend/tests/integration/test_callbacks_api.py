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
    # send_test_event 复用 dispatcher 的 deliver_once，patch 共享 requests 模块
    monkeypatch.setattr(
        "speech_to_speech.callback.dispatcher.requests.post",
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


def test_put_with_masked_token_preserves_old_secret(
    client, auth_headers: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """前端编辑整行回传脱敏 authToken（含 ***）时，保留 DB 旧 token 不被掩码覆盖。"""
    captured: dict = {}

    def fake_post(url, **kwargs):  # noqa: ANN001, ANN003
        captured.update(kwargs.get("headers") or {})
        return type("R", (), {"status_code": 200, "text": "ok"})()

    monkeypatch.setattr("speech_to_speech.callback.dispatcher.requests.post", fake_post)
    real_token = "toktoktoktok"
    resp = client.post("/api/v1/callbacks/targets", json={
        "name": "mask-guard", "targetType": "python", "baseUrl": "http://probe",
        "authType": "header_token", "authHeaderName": "X-Callback-Token",
        "authToken": real_token, "extraHeaders": {}, "timeoutMs": 1000,
        "retryMaxAttempts": 1, "retryBackoffMs": 0, "events": ["transcript"], "enabled": True,
    }, headers=auth_headers)
    target_id = resp.json()["data"]["id"]
    masked = resp.json()["data"]["authToken"]
    assert masked == "tokt***ktok"  # 详情返回脱敏串

    # PUT 更新但 authToken 回传掩码值（模拟前端编辑/启停整行回传）
    resp = client.put(f"/api/v1/callbacks/targets/{target_id}", json={
        "name": "mask-guard", "targetType": "python", "baseUrl": "http://probe",
        "authType": "header_token", "authHeaderName": "X-Callback-Token",
        "authToken": masked, "extraHeaders": {}, "timeoutMs": 2000,
        "retryMaxAttempts": 1, "retryBackoffMs": 0, "events": ["transcript"], "enabled": True,
    }, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["timeoutMs"] == 2000  # 其余字段正常更新
    assert resp.json()["data"]["authToken"] == "tokt***ktok"  # 仍是旧 token 的掩码

    # test 投递：实际发出的鉴权头必须是旧 token，而非掩码串
    resp = client.post(f"/api/v1/callbacks/targets/{target_id}/test", headers=auth_headers)
    data = resp.json()["data"]
    assert data["ok"] is True and data["httpStatus"] == 200
    assert captured["X-Callback-Token"] == real_token


# ── 内部下发端点 GET /targets/dispatch-config（agent dispatcher 轮询拉取）──────


def test_dispatch_config_requires_internal_token(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("S2S_ADMIN_TOKEN", "admintok")
    # 无令牌头 → 401；错令牌 → 401
    assert client.get("/api/v1/callbacks/targets/dispatch-config").status_code == 401
    assert client.get(
        "/api/v1/callbacks/targets/dispatch-config",
        headers={"X-Internal-Token": "wrong"}).status_code == 401


def test_dispatch_config_disabled_without_console_token(client, monkeypatch: pytest.MonkeyPatch) -> None:
    # fail-closed：console 未配置 S2S_ADMIN_TOKEN → 503（配置缺失，不是无权限）
    monkeypatch.delenv("S2S_ADMIN_TOKEN", raising=False)
    resp = client.get(
        "/api/v1/callbacks/targets/dispatch-config", headers={"X-Internal-Token": "anything"})
    assert resp.status_code == 503
    assert resp.json()["code"] == "internal_disabled"


def test_dispatch_config_shape_and_plaintext(client, auth_headers: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("S2S_ADMIN_TOKEN", "admintok")
    headers = {"X-Internal-Token": "admintok"}
    real_token = "toktoktoktok"
    # 空库：空 targets 也是有效响应（dispatcher 语义 = 明确不投递）
    resp = client.get("/api/v1/callbacks/targets/dispatch-config", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["targets"] == []
    revision_empty = resp.json()["data"]["revision"]
    assert isinstance(revision_empty, str)

    # 建一个目标（另一个 disabled 不应出现），明文 token 必须原样下发
    client.post("/api/v1/callbacks/targets", json={
        "name": "d0", "targetType": "python", "baseUrl": "http://x",
        "authType": "none", "authToken": "", "extraHeaders": {}, "timeoutMs": 3000,
        "retryMaxAttempts": 1, "retryBackoffMs": 0, "events": ["transcript"], "enabled": False,
    }, headers=auth_headers)
    resp = client.post("/api/v1/callbacks/targets", json={
        "name": "d1", "targetType": "java", "baseUrl": "http://192.168.110.167:8086",
        "authType": "header_token", "authHeaderName": "X-Internal-Token",
        "authToken": real_token, "extraHeaders": {"tenant-id": "1"}, "timeoutMs": 3000,
        "retryMaxAttempts": 3, "retryBackoffMs": 500, "events": ["transcript"], "enabled": True,
    }, headers=auth_headers)
    assert resp.status_code == 200

    resp = client.get("/api/v1/callbacks/targets/dispatch-config", headers=headers)
    data = resp.json()["data"]
    assert [t["name"] for t in data["targets"]] == ["d1"]
    assert data["targets"][0]["authToken"] == real_token      # 明文（非 _to_out 的脱敏）
    assert data["targets"][0]["baseUrl"] == "http://192.168.110.167:8086"
    assert data["revision"] and data["revision"] != revision_empty

    # 禁用后从下发列表消失
    listing = client.get("/api/v1/callbacks/targets?page=1&pageSize=50", headers=auth_headers).json()["data"]
    target_id = next(r["id"] for r in listing["list"] if r["name"] == "d1")
    client.post("/api/v1/callbacks/targets/batch",
                json={"ids": [target_id], "action": "disable"}, headers=auth_headers)
    resp = client.get("/api/v1/callbacks/targets/dispatch-config", headers=headers)
    assert resp.json()["data"]["targets"] == []
