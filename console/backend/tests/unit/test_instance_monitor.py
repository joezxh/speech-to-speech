from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.config import allocator as allocator_settings
from app.repositories.instance_metric_repository import InstanceMetricRepository
from app.repositories.instance_repository import InstanceRepository
from app.services import instance_monitor, instance_probe
from app.services.pool import PoolState


@pytest.fixture
def two_instances(db_session, monkeypatch):
    monkeypatch.setattr(allocator_settings, "metric_retention_days", 7)
    repo = InstanceRepository(db_session)
    repo.upsert_seed(instance_id="pipe-a", base_url="http://a:8765", weight=1,
                     max_sessions_hint=None, labels={})
    repo.upsert_seed(instance_id="pipe-b", base_url="http://b:8765", weight=1,
                     max_sessions_hint=None, labels={})
    instance_monitor.reset_for_tests()
    instance_monitor.refresh_specs(db_session)
    return db_session


def _healthy(timeout=True):
    return instance_probe.PoolProbe(
        ok=True, probe_ms=10,
        state=PoolState(reachable=True, size=2, in_use=0,
                        units=({"index": 0, "state": "idle"}, {"index": 1, "state": "idle"})),
    )


def _down(timeout=True):
    return instance_probe.PoolProbe(ok=False, probe_ms=50, state=None, error="refused")


def test_three_failures_evict_within_the_probe_budget(two_instances, monkeypatch):
    # spec §15 P1.2：连续 3 次失败 ≈ 15s 摘除（5s 间隔 × 3）
    monkeypatch.setattr(instance_probe, "probe_pool", lambda base_url, timeout=2.0: _down())
    for _ in range(2):
        instance_monitor.probe_all(two_instances)
        assert instance_monitor.registry.get("pipe-a").status != "offline"
    instance_monitor.probe_all(two_instances)
    assert instance_monitor.registry.get("pipe-a").status == "offline"


def test_state_change_writes_an_immediate_metric_row(two_instances, monkeypatch):
    monkeypatch.setattr(instance_probe, "probe_pool", lambda base_url, timeout=2.0: _healthy())
    instance_monitor.probe_all(two_instances)
    rows = InstanceMetricRepository(two_instances).window(
        "pipe-a", since=datetime.now(tz=UTC).replace(year=datetime.now(UTC).year - 1))
    assert len(rows) == 1 and rows[0].kind == "state_change" and rows[0].status == "online"
    assert rows[0].observed_by == allocator_settings.resolved_console_id


def test_sample_metrics_writes_null_for_unreachable_not_zero(two_instances, monkeypatch):
    # spec §5.2 "no data != zero"：offline 的实例采样行 size/in_use 必须是 NULL
    monkeypatch.setattr(instance_probe, "probe_pool", lambda base_url, timeout=2.0: _down())
    for _ in range(3):
        instance_monitor.probe_all(two_instances)
    instance_monitor.sample_metrics(two_instances)
    rows = InstanceMetricRepository(two_instances).window(
        "pipe-a", since=datetime.now(tz=UTC).replace(year=datetime.now(UTC).year - 1))
    sample = [r for r in rows if r.kind == "sample"]
    assert len(sample) == 1 and sample[0].size is None and sample[0].in_use is None
    assert sample[0].status == "offline"


def test_prune_metrics_honours_retention(two_instances, monkeypatch):
    metrics = InstanceMetricRepository(two_instances)
    metrics.insert_many([
        {"instance_id": "pipe-a", "observed_at": datetime.now(UTC), "observed_by": "c",
         "kind": "sample", "status": "online"},
        {"instance_id": "pipe-a", "observed_at": datetime(2020, 1, 1, tzinfo=UTC),
         "observed_by": "c", "kind": "sample", "status": "online"},
    ])
    monkeypatch.setattr(allocator_settings, "metric_retention_days", 7)
    assert instance_monitor.prune_metrics(two_instances) == 1


def test_probe_exception_in_one_instance_does_not_break_the_round(two_instances, monkeypatch):
    def flaky(base_url, timeout=2.0):
        if base_url.endswith("b:8765"):
            raise RuntimeError("boom")
        return _healthy()

    monkeypatch.setattr(instance_probe, "probe_pool", flaky)
    instance_monitor.probe_all(two_instances)  # 不抛
    assert instance_monitor.registry.get("pipe-a").status == "online"
    assert instance_monitor.registry.get("pipe-b").status == "unknown"
