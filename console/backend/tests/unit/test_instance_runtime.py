"""运行时注册表落库（spec 2026-11-17 §2.1）。

守住这几条不变量：
- 探测之后状态写进 `param_instance_runtime`（重启不丢）；
- 控制台重启后 `refresh_specs` 能从库里恢复健康状态与能力指纹；
- 离线时槽位写 NULL（不可得 ≠ 0）；
- 巡检不覆盖选台占着的 `reserved` 列。
"""

from __future__ import annotations

import pytest

from app.repositories.instance_repository import InstanceRepository
from app.repositories.instance_runtime_repository import InstanceRuntimeRepository
from app.services import instance_monitor, instance_probe
from app.services.instance_registry import OFFLINE, ONLINE
from app.services.pool import PoolState


@pytest.fixture
def one_instance(db_session):
    InstanceRepository(db_session).upsert_seed(
        instance_id="pipe-a",
        base_url="http://a:8765",
        weight=1,
        max_sessions_hint=None,
        labels={},
    )
    instance_monitor.reset_for_tests()
    instance_monitor.refresh_specs(db_session)
    return db_session


def _healthy():
    return instance_probe.PoolProbe(
        ok=True,
        probe_ms=10,
        state=PoolState(
            reachable=True,
            size=2,
            in_use=1,
            units=({"index": 0, "state": "idle"}, {"index": 1, "state": "active"}),
        ),
    )


def _down():
    return instance_probe.PoolProbe(ok=False, probe_ms=50, state=None, error="refused")


def test_a_probe_writes_the_runtime_row(one_instance, monkeypatch):
    monkeypatch.setattr(instance_probe, "probe_pool", lambda base_url, timeout=2.0: _healthy())
    instance_monitor.probe_all(one_instance)
    row = InstanceRuntimeRepository(one_instance).get("pipe-a")
    assert row is not None
    assert row.status == ONLINE
    assert row.pool_size == 2
    assert row.in_use == 1
    assert row.stuck == 0
    assert row.probe_ms == 10
    assert row.observed_by


def test_an_unreachable_instance_stores_null_slots(one_instance, monkeypatch):
    monkeypatch.setattr(instance_probe, "probe_pool", lambda base_url, timeout=2.0: _down())
    for _ in range(3):
        instance_monitor.probe_all(one_instance)
    row = InstanceRuntimeRepository(one_instance).get("pipe-a")
    assert row is not None
    assert row.status == OFFLINE
    # 不可得 ≠ 0（spec §5.2）
    assert row.pool_size is None
    assert row.in_use is None


def test_the_registry_restores_the_last_known_state(one_instance, monkeypatch):
    """重启场景：新的注册表从库里恢复状态与能力指纹，不必等首轮探测。"""
    monkeypatch.setattr(instance_probe, "probe_pool", lambda base_url, timeout=2.0: _healthy())
    instance_monitor.probe_all(one_instance)

    # 换一个新的注册表（模拟控制台重启），只靠库里的数据恢复。
    instance_monitor.reset_for_tests()
    instance_monitor.refresh_specs(one_instance)
    state = instance_monitor.registry.get("pipe-a")
    assert state is not None
    assert state.status == ONLINE
    assert state.pool is not None
    assert state.pool.size == 2
    assert state.pool.in_use == 1
    assert state.effective_free == 1


def test_capabilities_land_in_the_runtime_row(one_instance, monkeypatch):
    class _Report:
        available = frozenset({"realtime", "asr"})
        issues = {"voiceprint": "not registered"}

    instance_monitor.apply_capabilities({"pipe-a": _Report()}, one_instance)
    row = InstanceRuntimeRepository(one_instance).get("pipe-a")
    assert row is not None
    assert sorted(row.capabilities) == ["asr", "realtime"]
    assert row.capability_issues == {"voiceprint": "not registered"}


def test_the_probe_never_touches_the_reserved_column(one_instance, monkeypatch):
    monkeypatch.setattr(instance_probe, "probe_pool", lambda base_url, timeout=2.0: _healthy())
    instance_monitor.probe_all(one_instance)
    runtime = InstanceRuntimeRepository(one_instance)
    runtime.upsert(
        instance_id="pipe-a",
        observed_by="test",
        status=ONLINE,
        pool_size=2,
        in_use=0,
        stuck=0,
    )
    runtime.reserve("pipe-a")
    assert runtime.reserved_count("pipe-a") == 1
    # 再探一轮：状态照写，占位计数不动（归选台所有）。
    instance_monitor.probe_all(one_instance)
    assert runtime.reserved_count("pipe-a") == 1  
