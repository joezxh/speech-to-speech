from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import console as console_settings
from app.db.database import get_db
from app.main import create_app
from app.models.param_cluster import ParamCluster
from app.models.param_instance import ParamInstance
from app.models.param_instance_metric import ParamInstanceMetric
from app.repositories.user_repository import UserRepository
from app.services import instance_monitor, pool, process_probe
from app.services.auth_service import hash_password
from app.services.instance_registry import RuntimeState
from app.services.pool import PoolState


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
    # 与 test_instances.py 同惯例：隔离本机真实 pool，legacy 路径形状才可断言。
    monkeypatch.setattr(
        pool, "read_pool", lambda timeout=5.0, base_url=None: pool.PoolState(reachable=False, error="refused")
    )
    process_probe.set_probe(process_probe.NullProbe("test"))
    yield TestClient(app)
    process_probe.set_probe(None)
    instance_monitor.reset_for_tests()


def _auth(client):
    tokens = client.post("/api/v1/auth/login", json={"username": "alice", "password": "correct-horse"}).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def _seed_registry(db):
    db.add(ParamCluster(name="default"))
    db.add(ParamCluster(name="gray-01", registry="h:8500"))
    db.add(ParamInstance(instance_id="pipe-a", base_url="http://host1:8765", weight=1, labels_json={},
                         enabled=True, drain_requested=False, cluster_id="default"))
    db.add(ParamInstance(instance_id="pipe-b", base_url="http://host2:8765", weight=1, labels_json={},
                         enabled=True, drain_requested=False, cluster_id="gray-01"))
    db.commit()
    for iid, url in (("pipe-a", "http://host1:8765"), ("pipe-b", "http://host2:8765")):
        instance_monitor.registry._states[iid] = RuntimeState(instance_id=iid, base_url=url)
        instance_monitor.registry.observe_success(iid, PoolState(reachable=True, size=2, in_use=1, units=()), 10)


def test_no_cluster_param_keeps_legacy_shape(client, db_session):
    # 存量红线：注册表为空 + 不带参数 → 与改造前逐字段一致（不含 summary/新键）
    data = client.get("/api/v1/instances", headers=_auth(client)).json()["data"]
    assert "summary" not in data
    assert data["pool"] is None


def test_cluster_filter_selects_rows_and_machines(client, db_session):
    _seed_registry(db_session)
    data = client.get("/api/v1/instances", params={"cluster": "gray-01"}, headers=_auth(client)).json()["data"]
    assert [r["instance_id"] for r in data["instances"]] == ["pipe-b"]
    assert data["summary"]["instances_total"] == 1
    assert data["summary"]["machines_total"] == 1
    assert data["summary"]["machines_online"] == 1


def test_summary_without_cluster_counts_all_hosts_deduped(client, db_session):
    _seed_registry(db_session)
    db_session.add(ParamInstance(instance_id="pipe-c", base_url="http://host1:9999", weight=1, labels_json={},
                                 enabled=True, drain_requested=False, cluster_id="gray-01"))
    db_session.commit()
    data = client.get("/api/v1/instances", headers=_auth(client)).json()["data"]
    # host1 两个实例（不同端口）= 同一台机器
    assert data["summary"]["machines_total"] == 2
    assert data["summary"]["instances_total"] == 3


def test_error_rate_derived_from_deltas(client, db_session):
    _seed_registry(db_session)
    db_session.add_all([
        # gray-01 窗口内：2 成功、1 个 503、1 个 no_instance → rate = 2/4 = 0.5
        ParamInstanceMetric(instance_id="pipe-b", observed_by="c1", kind="sample", status="online",
                            alloc_ok=2, alloc_fail_instance_503=1, alloc_fail_no_instance=1),
        # default 窗口内的样本不得泄漏进 gray-01 的口径
        ParamInstanceMetric(instance_id="pipe-a", observed_by="c1", kind="sample", status="online",
                            alloc_fail_instance_503=9),
    ])
    db_session.commit()
    data = client.get("/api/v1/instances", params={"cluster": "gray-01"}, headers=_auth(client)).json()["data"]
    assert data["summary"]["error_rate_5m"] == pytest.approx(0.5)
    assert data["summary"]["top_error_instance"] == "pipe-b"


def test_error_rate_null_when_no_samples(client, db_session):
    _seed_registry(db_session)
    data = client.get("/api/v1/instances", params={"cluster": "gray-01"}, headers=_auth(client)).json()["data"]
    # 无样本 = null，绝不 0（需求确认点 4）
    assert data["summary"]["error_rate_5m"] is None
    assert data["summary"]["top_error_instance"] is None


def test_top_error_instance_tie_breaks_lexicographically(client, db_session):
    _seed_registry(db_session)
    db_session.add(ParamInstance(instance_id="pipe-b2", base_url="http://host3:8765", weight=1, labels_json={},
                                 enabled=True, drain_requested=False, cluster_id="gray-01"))
    db_session.add_all([
        ParamInstanceMetric(
            instance_id="pipe-b", observed_by="c1", kind="sample", status="online", alloc_fail_instance_503=3
        ),
        ParamInstanceMetric(
            instance_id="pipe-b2", observed_by="c1", kind="sample", status="online", alloc_fail_instance_503=3
        ),
    ])
    db_session.commit()
    data = client.get("/api/v1/instances", params={"cluster": "gray-01"}, headers=_auth(client)).json()["data"]
    assert data["summary"]["top_error_instance"] == "pipe-b"  # 并列取字典序最小