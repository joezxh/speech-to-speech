from __future__ import annotations

import pytest

from app.core.errors import ApiError
from app.models.param_cluster import ParamCluster
from app.models.param_instance import ParamInstance
from app.services import cluster_service


def _seed(db, name="default", registry="", policy="least", note=""):
    row = ParamCluster(name=name, registry=registry, policy=policy, note=note)
    db.add(row)
    db.commit()
    return row


def test_create_valid_cluster(db_session):
    _seed(db_session)
    row = cluster_service.create_cluster(
        db_session, name="gray-01", registry="consul://10.12.0.9:8500",
        policy="rr", note="canary pool", actor="alice",
    )
    assert row.name == "gray-01" and row.updated_by == "alice"


@pytest.mark.parametrize("bad", ["a", "A", "-x", "x" * 41, "has_dot", "under_score", "中文名"])
def test_create_rejects_bad_name(db_session, bad):
    _seed(db_session)
    with pytest.raises(ApiError) as excinfo:
        cluster_service.create_cluster(db_session, name=bad, registry="h:8500", policy="least", note="", actor="a")
    assert excinfo.value.code == "invalid_request"


def test_create_rejects_duplicate_name(db_session):
    _seed(db_session, name="gray-01", registry="h1:8500")
    with pytest.raises(ApiError) as excinfo:
        cluster_service.create_cluster(
            db_session, name="gray-01", registry="h2:8500", policy="least", note="", actor="a"
        )
    assert excinfo.value.code == "duplicate_name" and excinfo.value.status == 409


@pytest.mark.parametrize("bad", ["", "ftp://host", "host", "host:", "http://h:1", "tcp://h:65536x"])
def test_create_rejects_bad_registry(db_session, bad):
    _seed(db_session)
    with pytest.raises(ApiError) as excinfo:
        cluster_service.create_cluster(db_session, name="new-01", registry=bad, policy="least", note="", actor="a")
    assert excinfo.value.code == "invalid_request"


def test_registry_match_is_case_insensitive_scheme(db_session):
    _seed(db_session)
    row = cluster_service.create_cluster(
        db_session, name="new-01", registry="CONSUL://Host:8500", policy="least", note="", actor="a"
    )
    assert row.registry == "CONSUL://Host:8500"


def test_create_rejects_duplicate_registry(db_session):
    _seed(db_session, name="gray-01", registry="consul://h:8500")
    with pytest.raises(ApiError) as excinfo:
        cluster_service.create_cluster(
            db_session, name="new-02", registry="consul://h:8500", policy="least", note="", actor="a"
        )
    assert excinfo.value.code == "duplicate_registry" and excinfo.value.status == 409


def test_create_rejects_bad_policy(db_session):
    _seed(db_session)
    with pytest.raises(ApiError) as excinfo:
        cluster_service.create_cluster(db_session, name="new-03", registry="h:8500", policy="fifo", note="", actor="a")
    assert excinfo.value.code == "invalid_request"


def test_update_keeps_name_and_allows_own_registry(db_session):
    _seed(db_session, name="gray-01", registry="consul://h:8500")
    row = cluster_service.update_cluster(
        db_session, name="gray-01", registry="consul://h:8500", policy="lat", note="edited", actor="alice"
    )
    assert row.policy == "lat" and row.note == "edited"


def test_update_rejects_registry_owned_by_other(db_session):
    _seed(db_session, name="gray-01", registry="consul://h:8500")
    _seed(db_session, name="blue-01", registry="consul://h:8600")
    with pytest.raises(ApiError) as excinfo:
        cluster_service.update_cluster(
            db_session, name="gray-01", registry="consul://h:8600", policy="least", note="", actor="a"
        )
    assert excinfo.value.code == "duplicate_registry"


def test_update_unknown_cluster_is_404(db_session):
    _seed(db_session)
    with pytest.raises(ApiError) as excinfo:
        cluster_service.update_cluster(db_session, name="ghost", registry="h:1", policy="least", note="", actor="a")
    assert excinfo.value.code == "cluster_not_found" and excinfo.value.status == 404


def test_delete_blocked_by_instances(db_session):
    _seed(db_session)
    _seed(db_session, name="gray-01", registry="h:8500")
    db_session.add(ParamInstance(instance_id="pipe-a", base_url="http://a:8765", weight=1,
                                 labels_json={}, enabled=True, drain_requested=False, cluster_id="gray-01"))
    db_session.commit()
    with pytest.raises(ApiError) as excinfo:
        cluster_service.delete_cluster(db_session, name="gray-01", actor="a")
    assert excinfo.value.code == "cluster_not_empty" and "1" in excinfo.value.message


def test_delete_blocked_on_last_cluster(db_session):
    _seed(db_session)
    with pytest.raises(ApiError) as excinfo:
        cluster_service.delete_cluster(db_session, name="default", actor="a")
    assert excinfo.value.code == "last_cluster"


def test_delete_ok_when_empty(db_session):
    _seed(db_session)
    _seed(db_session, name="gray-01", registry="h:8500")
    cluster_service.delete_cluster(db_session, name="gray-01", actor="a")
    assert [c.name for c in cluster_service.list_clusters(db_session)] == ["default"]