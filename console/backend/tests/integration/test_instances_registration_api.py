"""实例在线纳管（spec 2026-11-17 §5.4）。

以前纳管一台机器只能改 `instances.yaml` 再重启控制台；现在直接写库：
- POST /api/v1/instances 新增（管理员）；
- DELETE /api/v1/instances/{id} 摘除，占位、运行时状态、声明数据一起清。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.database import get_db
from app.main import create_app
from app.repositories.allocator_lease_repository import AllocatorLeaseRepository
from app.repositories.audit_repository import AuditRepository
from app.repositories.instance_repository import InstanceRepository
from app.repositories.instance_runtime_repository import InstanceRuntimeRepository
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


def _auth(client):
    tokens = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "correct-horse"}
    ).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def test_registering_an_instance_writes_the_declaration_row(client, db_session):
    response = client.post(
        "/api/v1/instances",
        json={"instance_id": "pipe-b", "base_url": "http://b:8765", "weight": 2},
        headers=_auth(client),
    )
    assert response.status_code == 200
    row = InstanceRepository(db_session).get_by_instance_id("pipe-b")
    assert row is not None
    assert row.base_url == "http://b:8765"
    assert row.weight == 2
    assert row.enabled is True


def test_registering_the_same_instance_twice_is_a_conflict(client):
    payload = {"instance_id": "pipe-b", "base_url": "http://b:8765"}
    assert client.post("/api/v1/instances", json=payload, headers=_auth(client)).status_code == 200
    second = client.post("/api/v1/instances", json=payload, headers=_auth(client))
    assert second.status_code == 409


def test_registering_an_instance_is_audited(client, db_session):
    client.post(
        "/api/v1/instances",
        json={"instance_id": "pipe-b", "base_url": "http://b:8765"},
        headers=_auth(client),
    )
    audits, _total = AuditRepository(db_session).list(action="instance.register")
    assert audits
    assert audits[0].profile == "pipe-b"


def test_removing_an_instance_clears_its_leases_and_runtime_state(client, db_session):
    client.post(
        "/api/v1/instances",
        json={"instance_id": "pipe-b", "base_url": "http://b:8765"},
        headers=_auth(client),
    )
    InstanceRuntimeRepository(db_session).upsert(
        instance_id="pipe-b", observed_by="test", status="online", pool_size=2, in_use=0, stuck=0
    )
    AllocatorLeaseRepository(db_session).insert(
        lease_key="s1", instance_id="pipe-b", state="pending", console_id="c"
    )

    response = client.delete("/api/v1/instances/pipe-b", headers=_auth(client))
    assert response.status_code == 200
    assert InstanceRepository(db_session).get_by_instance_id("pipe-b") is None
    assert InstanceRuntimeRepository(db_session).get("pipe-b") is None
    assert AllocatorLeaseRepository(db_session).get("s1") is None  
