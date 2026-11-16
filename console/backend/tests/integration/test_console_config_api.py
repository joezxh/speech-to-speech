"""配置读写接口（spec 2026-11-17 §6.1）。

守住这几条不变量：
- 读要登录，写要管理员；
- 非法值 400 且**一项都不落库**；
- 写入留审计，但审计里只有字段名没有值；
- 写完立刻生效（同一进程内缓存失效）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.config import store as config_store
from app.db.database import get_db
from app.main import create_app
from app.repositories.audit_repository import AuditRepository
from app.repositories.config_repository import ConfigRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import hash_password


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))

    # 配置门面读库用自己的会话：测试里指到测试库。
    factory = sessionmaker(bind=db_session.get_bind(), future=True)
    config_store.set_session_factory(factory)

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    UserRepository(db_session).create("alice", hash_password("correct-horse"), "admin")
    UserRepository(db_session).create("bob", hash_password("correct-horse"), "operator")
    yield TestClient(app)
    config_store.set_session_factory(None)
    config_store.invalidate()


def _auth(client, who: str = "alice"):
    tokens = client.post(
        "/api/v1/auth/login", json={"username": who, "password": "correct-horse"}
    ).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def test_reading_the_config_needs_a_token(client):
    assert client.get("/api/v1/config").status_code == 401


def test_reading_the_config_returns_values_and_sources(client):
    response = client.get("/api/v1/config", headers=_auth(client))
    assert response.status_code == 200
    data = response.json()["data"]
    items = {item["key"]: item for item in data["items"]}
    assert "console.lb_mode" in items
    assert items["console.lb_mode"]["source"] in ("db", "env")
    assert items["console.lb_mode"]["type"] == "str"
    assert "env" in items["console.lb_mode"]


def test_the_schema_endpoint_lists_the_registered_items(client):
    response = client.get("/api/v1/config/schema", headers=_auth(client))
    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert any(item["key"] == "allocator.mode" for item in items)
    restart = [item for item in items if item["key"] == "allocator.mode"][0]
    # 分配器模式是启动期语义：改完要重启。
    assert restart["restart_required"] is True
    assert restart["hot"] is False


def test_writing_the_config_needs_the_admin_role(client):
    response = client.put(
        "/api/v1/config", json={"values": {"console.lb_mode": "proxy"}}, headers=_auth(client, "bob")
    )
    assert response.status_code == 403


def test_an_illegal_value_is_rejected_and_nothing_is_written(client, db_session):
    response = client.put(
        "/api/v1/config",
        json={"values": {"console.lb_mode": "proxy", "allocator.probe_interval_s": "0"}},
        headers=_auth(client),
    )
    assert response.status_code == 400
    assert ConfigRepository(db_session).get("console.lb_mode") is None


def test_writing_the_config_takes_effect_and_is_audited(client, db_session):
    response = client.put(
        "/api/v1/config", json={"values": {"console.lb_mode": "proxy"}}, headers=_auth(client)
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert "console.lb_mode" in data["updated"]

    # 值落库了。
    row = ConfigRepository(db_session).get("console.lb_mode")
    assert row is not None and row.value == "proxy"

    # 审计只记字段名，不记值。
    audits, _total = AuditRepository(db_session).list(action="config.update")
    assert audits
    assert "console.lb_mode" in audits[0].fields
    assert "proxy" not in str(audits[0].fields)


def test_a_restart_required_key_is_flagged(client):
    response = client.put(
        "/api/v1/config", json={"values": {"allocator.mode": "local"}}, headers=_auth(client)
    )
    assert response.status_code == 200
    assert "allocator.mode" in response.json()["data"]["restartRequired"]  
