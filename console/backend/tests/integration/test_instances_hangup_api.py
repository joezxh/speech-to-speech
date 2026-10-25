from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import allocator as allocator_settings
from app.config import console as console_settings
from app.db.database import get_db
from app.main import create_app
from app.models.param_instance import ParamInstance
from app.repositories.audit_repository import AuditRepository
from app.repositories.user_repository import UserRepository
from app.services import instance_monitor, instance_probe
from app.services.auth_service import hash_password


def _make_client(db_session, monkeypatch, tmp_path) -> TestClient:
    """Task 10 的 `client` fixture 去掉 fixture 包装：开关用例得在建 app 前改配置。"""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))
    monkeypatch.setattr(console_settings, "param_catalog_path", str(tmp_path / "missing.yaml"))
    users = UserRepository(db_session)
    users.create("ad", hash_password("correct-horse"), "admin")
    users.create("op", hash_password("correct-horse"), "operator")
    db_session.add(ParamInstance(instance_id="pipe-a", base_url="http://a:8765", weight=1,
                                 labels_json={}, enabled=True, drain_requested=False))
    db_session.commit()
    instance_monitor.reset_for_tests()
    instance_monitor.refresh_specs(db_session)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    yield _make_client(db_session, monkeypatch, tmp_path)
    instance_monitor.reset_for_tests()


def _auth(client, user="ad"):
    tokens = client.post("/api/v1/auth/login",
                         json={"username": user, "password": "correct-horse"}).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def test_hangup_route_absent_by_default(client):
    # 默认关：路由未注册。SPA catch-all 只注册了 GET（core/spa.py:64），所以
    # 这条未挂载的 POST 路径会命中 catch-all 的 path 但方法不匹→ 405（而非 404，
    # 也不是 200 text/html）——同样证明 hangup 路由没挂上去。
    response = client.post("/api/v1/instances/pipe-a/hangup",
                           json={"session_id": "c-1"}, headers=_auth(client))
    assert response.status_code == 405


def test_hangup_proxies_with_admin_token(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(allocator_settings, "webrtc_hangup_enabled", True)
    monkeypatch.setenv("S2S_ADMIN_TOKEN", "pipeline-admin-token")
    seen = {}

    def fake(base_url, call_id, token, timeout=5.0):
        seen.update(base_url=base_url, call_id=call_id, token=token, timeout=timeout)
        return 200

    monkeypatch.setattr(instance_probe, "hangup_call", fake)
    client = _make_client(db_session, monkeypatch, tmp_path)
    response = client.post("/api/v1/instances/pipe-a/hangup",
                           json={"session_id": "c-1"}, headers=_auth(client))
    assert response.status_code == 200
    assert response.json()["data"] == {"instance_id": "pipe-a", "session_id": "c-1",
                                       "upstream_status": 200}
    assert seen == {"base_url": "http://a:8765", "call_id": "c-1",
                    "token": "pipeline-admin-token", "timeout": 5.0}
    rows, _ = AuditRepository(db_session).list(action="instance.hangup", profile="pipe-a")
    assert len(rows) == 1 and rows[0].actor == "ad" and rows[0].fields == ["session_id"]


def test_hangup_is_admin_only(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(allocator_settings, "webrtc_hangup_enabled", True)
    client = _make_client(db_session, monkeypatch, tmp_path)
    response = client.post("/api/v1/instances/pipe-a/hangup",
                           json={"session_id": "c-1"}, headers=_auth(client, "op"))
    assert response.status_code == 403 and response.json()["code"] == "forbidden"


def test_hangup_without_a_configured_token_is_503(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(allocator_settings, "webrtc_hangup_enabled", True)
    monkeypatch.delenv("S2S_ADMIN_TOKEN", raising=False)
    client = _make_client(db_session, monkeypatch, tmp_path)
    response = client.post("/api/v1/instances/pipe-a/hangup",
                           json={"session_id": "c-1"}, headers=_auth(client))
    assert response.status_code == 503 and response.json()["code"] == "admin_disabled"


def test_hangup_unknown_call_passes_the_upstream_404_through(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(allocator_settings, "webrtc_hangup_enabled", True)
    monkeypatch.setenv("S2S_ADMIN_TOKEN", "pipeline-admin-token")
    monkeypatch.setattr(instance_probe, "hangup_call", lambda *args, **kwargs: 404)
    client = _make_client(db_session, monkeypatch, tmp_path)
    response = client.post("/api/v1/instances/pipe-a/hangup",
                           json={"session_id": "gone"}, headers=_auth(client))
    assert response.status_code == 404 and response.json()["code"] == "upstream_not_found"
