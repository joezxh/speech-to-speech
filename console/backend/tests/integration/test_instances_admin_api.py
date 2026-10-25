from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import console as console_settings
from app.db.database import get_db
from app.main import create_app
from app.models.param_instance import ParamInstance
from app.repositories.audit_repository import AuditRepository
from app.repositories.instance_repository import InstanceRepository
from app.repositories.user_repository import UserRepository
from app.services import instance_monitor
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
    UserRepository(db_session).create("op", hash_password("correct-horse"), "operator")
    UserRepository(db_session).create("ad", hash_password("correct-horse"), "admin")
    db_session.add(
        ParamInstance(
            instance_id="pipe-a",
            base_url="http://a:8765",
            weight=1,
            labels_json={},
            enabled=True,
            drain_requested=False,
        )
    )
    db_session.commit()
    instance_monitor.reset_for_tests()
    instance_monitor.refresh_specs(db_session)
    yield TestClient(app)
    instance_monitor.reset_for_tests()


def _auth(client, user="op"):
    tokens = client.post("/api/v1/auth/login", json={"username": user, "password": "correct-horse"}).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def test_drain_persists_flags_and_audits(client, db_session):
    response = client.post("/api/v1/instances/pipe-a/drain", headers=_auth(client))
    assert response.status_code == 200
    assert response.json()["data"]["drain_requested"] is True
    assert InstanceRepository(db_session).get_by_instance_id("pipe-a").drain_requested is True
    assert instance_monitor.registry.get("pipe-a").status == "draining"
    rows, _ = AuditRepository(db_session).list(action="instance.drain", profile="pipe-a")
    assert len(rows) == 1 and rows[0].actor == "op" and rows[0].fields == ["drain_requested"]


def test_undrain_restores_allocatability(client):
    client.post("/api/v1/instances/pipe-a/drain", headers=_auth(client))
    client.post("/api/v1/instances/pipe-a/undrain", headers=_auth(client))
    # 从未探测过 → 回 unknown，等首轮巡检（spec §6.2）
    assert instance_monitor.registry.get("pipe-a").status == "unknown"


def test_unknown_instance_is_404(client):
    assert client.post("/api/v1/instances/nope/drain", headers=_auth(client)).status_code == 404


def test_bad_window_is_400(client):
    body = client.get("/api/v1/instances/pipe-a/metrics?window=30m", headers=_auth(client)).json()
    assert body["code"] != 200


def test_detail_route_returns_probe_history(client, db_session):
    from app.services.pool import PoolState

    instance_monitor.registry.observe_success("pipe-a", PoolState(reachable=True, size=2, units=()), 8)
    data = client.get("/api/v1/instances/pipe-a", headers=_auth(client)).json()["data"]
    assert data["instance_id"] == "pipe-a" and data["probeHistory"][-1] == 8
