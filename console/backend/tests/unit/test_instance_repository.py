from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.repositories.instance_metric_repository import InstanceMetricRepository
from app.repositories.instance_repository import InstanceRepository


def _row(instance_id="pipe-a", **kw):
    return {
        "instance_id": instance_id,
        "observed_at": datetime.now(UTC),
        "observed_by": "console-1",
        "kind": "sample",
        "size": 4,
        "in_use": 1,
        "free": 3,
        "stuck": None,
        "status": "online",
        "probe_ms": 12,
        **kw,
    }


def test_set_drain_roundtrip_and_updated_by(db_session):
    repo = InstanceRepository(db_session)
    repo.upsert_seed(base_url="http://h:8765", instance_id="pipe-a", weight=1,
                     max_sessions_hint=None, labels={})
    row = repo.set_drain("pipe-a", drain=True, updated_by="alice")
    assert row is not None and row.drain_requested is True and row.updated_by == "alice"
    assert repo.set_drain("pipe-a", drain=False, updated_by="alice").drain_requested is False


def test_metric_window_filters_by_instance_and_since(db_session):
    metrics = InstanceMetricRepository(db_session)
    old = datetime.now(UTC) - timedelta(days=2)
    metrics.insert_many([_row(observed_at=old), _row(), _row(instance_id="pipe-b")])
    cutoff = datetime.now(UTC) - timedelta(hours=1)
    rows = metrics.window("pipe-a", since=cutoff)
    assert len(rows) == 1 and rows[0].observed_by == "console-1"


def test_prune_before_deletes_only_expired(db_session):
    metrics = InstanceMetricRepository(db_session)
    old = datetime.now(UTC) - timedelta(days=30)
    metrics.insert_many([_row(observed_at=old), _row()])
    cutoff = datetime.now(UTC) - timedelta(days=7)
    assert metrics.prune_before(cutoff) == 1
    assert metrics.latest_observed_at() > cutoff
