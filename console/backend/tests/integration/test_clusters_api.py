from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import console as console_settings
from app.db.database import get_db
from app.main import create_app
from app.models.param_audit import ParamAudit
from app.models.param_cluster import ParamCluster
from app.models.param_instance import ParamInstance
from app.repositories.user_repository import UserRepository
from app.services import process_probe
from app.services.auth_service import hash_password


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))
    monkeypatch.setattr(console_settings, "param_catalog_path", str(tmp_path / "missing.yaml"))
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    UserRepository(db_session).create("alice", hash_password("correct-horse"), "admin")
    UserRepository(db_session).create("bob", hash_password("correct-horse"), "operator")
    UserRepository(db_session).create("carol", hash_password("correct-horse"), "client")
    process_probe.set_probe(process_probe.NullProbe("test has no supervisor"))
    yield TestClient(app)
    process_probe.set_probe(None)


def _auth(client, username, password="correct-horse"):
    tokens = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    ).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def _seed_cluster(db, name="default", registry="", policy="least", note=""):
    db.add(ParamCluster(name=name, registry=registry, policy=policy, note=note))
    db.commit()


def _audit_rows(db, action):
    return list(db.scalars(select(ParamAudit).where(ParamAudit.action == action)))


def test_list_returns_seeded_default_first(client, db_session):
    _seed_cluster(db_session)
    rows = client.get("/api/v1/clusters", headers=_auth(client, "alice")).json()["data"]
    assert rows[0]["name"] == "default"
    assert {"name", "registry", "policy", "note", "machines_total", "machines_online",
            "instances_total", "healthy", "updated_at", "updated_by"} <= set(rows[0])


def test_create_valid_cluster_writes_ok_audit(client, db_session):
    _seed_cluster(db_session)
    response = client.post(
        "/api/v1/clusters", headers=_auth(client, "alice"),
        json={"name": "gray-01", "registry": "consul://10.12.0.9:8500", "policy": "rr", "note": "canary"},
    )
    assert response.status_code == 200 and response.json()["data"]["name"] == "gray-01"
    rows = _audit_rows(db_session, "cluster.create")
    assert len(rows) == 1 and rows[0].result == "ok" and rows[0].profile == "gray-01"
    assert rows[0].actor == "alice"


def test_create_invalid_name_writes_error_audit(client, db_session):
    _seed_cluster(db_session)
    response = client.post(
        "/api/v1/clusters", headers=_auth(client, "alice"),
        json={"name": "BAD NAME", "registry": "h:8500", "policy": "least", "note": ""},
    )
    assert response.status_code == 400 and response.json()["code"] == "invalid_request"
    rows = _audit_rows(db_session, "cluster.create")
    assert len(rows) == 1 and rows[0].result == "error" and rows[0].error_code == "invalid_request"


def test_create_duplicate_registry_is_409_with_audit(client, db_session):
    _seed_cluster(db_session, name="gray-01", registry="consul://h:8500")
    response = client.post(
        "/api/v1/clusters", headers=_auth(client, "alice"),
        json={"name": "blue-01", "registry": "consul://h:8500", "policy": "least", "note": ""},
    )
    assert response.status_code == 409 and response.json()["code"] == "duplicate_registry"
    assert _audit_rows(db_session, "cluster.create")[0].error_code == "duplicate_registry"


def test_update_allows_own_registry_blocks_foreign(client, db_session):
    _seed_cluster(db_session, name="gray-01", registry="consul://h:8500")
    _seed_cluster(db_session, name="blue-01", registry="consul://h:8600")
    ok_response = client.put(
        "/api/v1/clusters/gray-01", headers=_auth(client, "alice"),
        json={"registry": "consul://h:8500", "policy": "lat", "note": "self-ok"},
    )
    assert ok_response.status_code == 200 and ok_response.json()["data"]["policy"] == "lat"
    bad = client.put(
        "/api/v1/clusters/gray-01", headers=_auth(client, "alice"),
        json={"registry": "consul://h:8600", "policy": "least", "note": ""},
    )
    assert bad.status_code == 409 and bad.json()["code"] == "duplicate_registry"


def test_update_unknown_is_404(client, db_session):
    _seed_cluster(db_session)
    response = client.put(
        "/api/v1/clusters/ghost", headers=_auth(client, "alice"),
        json={"registry": "h:8500", "policy": "least", "note": ""},
    )
    assert response.status_code == 404 and response.json()["code"] == "cluster_not_found"


def test_delete_blocked_by_instances_then_ok(client, db_session):
    _seed_cluster(db_session)
    _seed_cluster(db_session, name="gray-01", registry="h:8500")
    inst = ParamInstance(instance_id="pipe-a", base_url="http://a:8765", weight=1, labels_json={},
                         enabled=True, drain_requested=False, cluster_id="gray-01")
    db_session.add(inst)
    db_session.commit()
    blocked = client.delete("/api/v1/clusters/gray-01", headers=_auth(client, "alice"))
    assert blocked.status_code == 409 and blocked.json()["code"] == "cluster_not_empty"
    assert _audit_rows(db_session, "cluster.delete")[0].error_code == "cluster_not_empty"
    db_session.delete(inst)
    db_session.commit()
    done = client.delete("/api/v1/clusters/gray-01", headers=_auth(client, "alice"))
    assert done.status_code == 200
    assert {r.result for r in _audit_rows(db_session, "cluster.delete")} == {"error", "ok"}


def test_delete_last_cluster_is_blocked(client, db_session):
    _seed_cluster(db_session)
    response = client.delete("/api/v1/clusters/default", headers=_auth(client, "alice"))
    assert response.status_code == 409 and response.json()["code"] == "last_cluster"


def test_switch_records_audit_for_existing_and_missing(client, db_session):
    _seed_cluster(db_session)
    headers = _auth(client, "bob")  # operator 也必须能切
    assert client.post("/api/v1/clusters/default/switch", headers=headers).status_code == 200
    missing = client.post("/api/v1/clusters/ghost/switch", headers=headers)
    assert missing.status_code == 404
    rows = _audit_rows(db_session, "cluster.switch")
    assert {r.result for r in rows} == {"ok", "error"}
    assert next(r for r in rows if r.result == "error").error_code == "cluster_not_found"


def test_operator_can_query_switch_but_not_write(client, db_session):
    _seed_cluster(db_session)
    headers = _auth(client, "bob")
    assert client.get("/api/v1/clusters", headers=headers).status_code == 200
    denied = client.post(
        "/api/v1/clusters", headers=headers,
        json={"name": "nope-01", "registry": "h:8500", "policy": "least", "note": ""},
    )
    assert denied.status_code == 403 and denied.json()["code"] == "forbidden"


def test_client_role_cannot_even_query(client, db_session):
    _seed_cluster(db_session)
    assert client.get("/api/v1/clusters", headers=_auth(client, "carol")).status_code == 403


def test_unauthenticated_is_401_and_no_audit(client, db_session):
    _seed_cluster(db_session)
    assert client.get("/api/v1/clusters").status_code == 401
    assert client.post("/api/v1/clusters/default/switch").status_code == 401
    assert _audit_rows(db_session, "cluster.switch") == []  # 401 发生在解析操作人之前（spec §4.3）


def test_events_returns_latest_cluster_actions(client, db_session):
    _seed_cluster(db_session)
    for i in range(5):
        client.post(
            "/api/v1/clusters", headers=_auth(client, "alice"),
            json={"name": f"c{i:02d}", "registry": f"h{i}:8500", "policy": "least", "note": ""},
        )
    data = client.get("/api/v1/clusters/events?limit=4", headers=_auth(client, "bob")).json()["data"]
    assert len(data) == 4
    assert all(row["action"].startswith("cluster.") for row in data)
    assert {"at", "actor", "role", "action", "result", "errorCode", "profile"} <= set(data[0])