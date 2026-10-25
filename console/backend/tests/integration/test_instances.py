from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import console as console_settings
from app.db.database import get_db
from app.main import create_app
from app.repositories.user_repository import UserRepository
from app.services import pool, process_probe
from app.services.auth_service import hash_password


class _RunningProbe:
    def state(self, name):
        return process_probe.ProcessInfo(name=name, running=True, pid=42, state="RUNNING")


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
    process_probe.set_probe(process_probe.NullProbe("test has no supervisor"))
    yield TestClient(app)
    process_probe.set_probe(None)


def _auth(client):
    tokens = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "correct-horse"}
    ).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def test_instances_keeps_200_when_the_pool_is_down(client, monkeypatch):
    monkeypatch.setattr(
        pool, "read_pool", lambda timeout=5.0: pool.PoolState(reachable=False, error="refused")
    )
    response = client.get("/api/v1/instances", headers=_auth(client))
    assert response.status_code == 200
    data = response.json()["data"]
    # A.10: a degraded read is the whole point of this page.
    assert data["pool"] is None
    assert "pool_unreachable" in data["alerts"]
    assert "pipeline_stopped" in data["alerts"]
    assert data["container"]["name"] == console_settings.supervisor_program


def test_instances_exposes_units_and_usage(client, monkeypatch):
    state = pool.PoolState(
        reachable=True,
        size=2,
        in_use=1,
        units=(
            {"index": 0, "state": "active", "session_id": "s1"},
            {"index": 1, "state": "idle", "session_id": None},
        ),
    )
    monkeypatch.setattr(pool, "read_pool", lambda timeout=5.0: state)
    monkeypatch.setattr(pool, "read_usage", lambda timeout=5.0: {"turns": 3})

    data = client.get("/api/v1/instances", headers=_auth(client)).json()["data"]
    assert data["pool"] == {
        "size": 2,
        "inUse": 1,
        "units": [
            {"index": 0, "state": "active", "sessionId": "s1"},
            {"index": 1, "state": "idle", "sessionId": None},
        ],
    }
    assert data["usage"] == {"turns": 3}
    assert data["alerts"] == ["pipeline_stopped"]


def test_status_reports_the_environment_it_is_running_in(client, monkeypatch):
    monkeypatch.delenv("S2S_INTERNAL_TOKEN", raising=False)
    monkeypatch.setattr(
        pool, "read_pool", lambda timeout=5.0: pool.PoolState(reachable=False, error="refused")
    )
    data = client.get("/api/v1/status", headers=_auth(client)).json()["data"]
    assert data["db"] == "ok"
    assert data["pipeline"] == "unreachable"
    assert data["internalTokenConfigured"] is False
    assert data["validatorMode"] in ("runtime", "structural")
    assert data["profile"] == "prod"


def test_status_sees_a_configured_internal_token(client, monkeypatch):
    monkeypatch.setenv("S2S_INTERNAL_TOKEN", "tok")
    monkeypatch.setattr(
        pool, "read_pool", lambda timeout=5.0: pool.PoolState(reachable=True, size=1)
    )
    process_probe.set_probe(_RunningProbe())
    data = client.get("/api/v1/status", headers=_auth(client)).json()["data"]
    assert data["internalTokenConfigured"] is True
    assert data["pipeline"] == "ok"


def test_status_trusts_a_serving_pool_when_there_is_no_supervisor(client, monkeypatch):
    # 开发机上 `RESTART_MODE=noop`，探针只能答 unknown；这时 /v1/pool 能应答
    # 就是“pipeline 正在服务”的唯一证据，顶栏不能因为缺 supervisor 而报不可达。
    monkeypatch.setattr(
        pool, "read_pool", lambda timeout=5.0: pool.PoolState(reachable=True, size=1)
    )
    process_probe.set_probe(process_probe.NullProbe("no supervisor on a dev box"))

    data = client.get("/api/v1/status", headers=_auth(client)).json()["data"]

    assert data["pipeline"] == "ok"


def test_instances_aggregates_registry_rows(client, db_session, monkeypatch):
    from app.models.param_instance import ParamInstance
    from app.services import instance_monitor
    from app.services.instance_registry import RuntimeState
    from app.services.pool import PoolState

    db_session.add(ParamInstance(instance_id="pipe-a", base_url="http://a:8765", weight=1,
                                 labels_json={}, enabled=True, drain_requested=False))
    db_session.add(ParamInstance(instance_id="pipe-b", base_url="http://b:8765", weight=1,
                                 labels_json={}, enabled=True, drain_requested=True))
    db_session.commit()
    state_a = RuntimeState(instance_id="pipe-a", base_url="http://a:8765")
    instance_monitor.registry._states["pipe-a"] = state_a
    instance_monitor.registry.observe_success("pipe-a",
        PoolState(reachable=True, size=4, in_use=2, units=()), 12)
    instance_monitor.registry._states["pipe-b"] = RuntimeState(instance_id="pipe-b", base_url="http://b:8765")
    instance_monitor.registry.set_drain("pipe-b", True)
    # 注册表路径下不得回退到 legacy 直连读，否则 monkeypatch 基线会被误触发
    monkeypatch.setattr(pool, "read_pool",
                        lambda timeout=5.0, base_url=None: pytest.fail("legacy read_pool called"))

    data = client.get("/api/v1/instances", headers=_auth(client)).json()["data"]
    assert data["summary"]["instances_total"] == 2
    assert data["summary"]["draining"] == 1
    ids = {row["instance_id"] for row in data["instances"]}
    assert ids == {"pipe-a", "pipe-b"}
    row_a = next(r for r in data["instances"] if r["instance_id"] == "pipe-a")
    assert row_a["status"] == "online" and row_a["free"] == 2
    assert data["pool"] is None  # 本机不在注册表视图里 → 降级语义不变
    assert "pool_unreachable:pipe-b:not_observed" in data["alerts"]
    instance_monitor.reset_for_tests()


def test_status_exposes_allocator_state(client, monkeypatch):
    from app.config import allocator as allocator_settings

    monkeypatch.setattr(allocator_settings, "mode", "local")
    data = client.get("/api/v1/status", headers=_auth(client)).json()["data"]
    assert data["allocatorMode"] == "local"
    assert data["instancesRegistered"] == 0
    assert data["seedConfigured"] is False
    assert isinstance(data["consoleId"], str) and data["consoleId"]
    # 本机可见性：四个密钥是否全部配置；测试环境不保证，只要求类型正确（spec §12）
    assert data["secretsConsistent"] in (True, False)
