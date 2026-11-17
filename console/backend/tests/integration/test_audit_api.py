"""Task 25（R5/R6）——全局审计查询与 CSV 导出。

category 由 action 前缀推导（machine./lb./deploy./release./voice./cluster.）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.database import get_db
from app.main import create_app
from app.repositories.audit_repository import AuditRepository
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
    UserRepository(db_session).create("op", hash_password("correct-horse"), "operator")
    yield TestClient(app)


def _auth(client, username="alice"):
    tokens = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "correct-horse"}
    ).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def _seed(db_session):
    repo = AuditRepository(db_session)
    repo.record(actor="alice", role="admin", action="machine.create", profile="node-a", fields=["machineId"])
    repo.record(actor="alice", role="admin", action="machine.create", profile="node-b", fields=["machineId"])
    repo.record(actor="bob", role="operator", action="lb.rule.create", profile="canary-a", fields=["priority"])
    repo.record(actor="bob", role="operator", action="publish", profile="prod", fields=["version"], result="error", error_code="hash_mismatch")


def test_filter_combinations(client, db_session):
    _seed(db_session)
    by_actor = client.get("/api/v1/audit", params={"actor": "alice"}, headers=_auth(client)).json()["data"]
    assert by_actor["total"] == 2
    by_action = client.get("/api/v1/audit", params={"action": "lb.rule.create"}, headers=_auth(client)).json()["data"]
    assert by_action["total"] == 1
    by_result = client.get("/api/v1/audit", params={"result": "error"}, headers=_auth(client)).json()["data"]
    assert by_result["total"] == 1
    by_field = client.get("/api/v1/audit", params={"field": "priority"}, headers=_auth(client)).json()["data"]
    assert by_field["total"] == 1
    by_category = client.get("/api/v1/audit", params={"category": "machine"}, headers=_auth(client)).json()["data"]
    assert by_category["total"] == 2
    assert by_category["items"][0]["category"] == "machine"


def test_pagination_bounds(client, db_session):
    _seed(db_session)
    page_one = client.get("/api/v1/audit", params={"page": 1, "pageSize": 2}, headers=_auth(client)).json()["data"]
    page_two = client.get("/api/v1/audit", params={"page": 2, "pageSize": 2}, headers=_auth(client)).json()["data"]
    assert len(page_one["items"]) == 2
    assert len(page_two["items"]) == 2
    assert page_one["total"] == page_two["total"] == 4
    assert page_one["items"][0]["id"] != page_two["items"][0]["id"]
    empty = client.get("/api/v1/audit", params={"page": 9, "pageSize": 50}, headers=_auth(client)).json()["data"]
    assert empty["items"] == []


def test_csv_export_headers_and_rows(client, db_session):
    _seed(db_session)
    response = client.get("/api/v1/audit/export", headers=_auth(client))
    assert response.status_code == 200
    assert "attachment" in response.headers.get("content-disposition", "")
    lines = response.text.strip().splitlines()
    assert lines[0].startswith("id,at,actor"), "首行表头"
    assert len(lines) == 5, "表头 + 4 条筛选行"

    filtered = client.get("/api/v1/audit/export", params={"category": "machine"}, headers=_auth(client))
    assert len(filtered.text.strip().splitlines()) == 3


def test_operator_can_query_but_not_export(client):
    assert client.get("/api/v1/audit", headers=_auth(client, "op")).status_code == 200
    assert client.get("/api/v1/audit/export", headers=_auth(client, "op")).status_code == 403
