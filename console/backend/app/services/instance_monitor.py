"""常驻巡检：一轮 gather 探全部实例，单台超时不阻塞其余（spec §9）。

跳变即时落 `state_change` 指标；30s 采样落 `sample`；读接口走 2s 防抖缓存
（与 runtime_service._TTL_S 同思路）；任务异常只记日志（同 _usage_sweeper）。
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from app.config import allocator
from app.config import console
from app.repositories.instance_metric_repository import InstanceMetricRepository
from app.repositories.instance_repository import InstanceRepository
from app.services import capability_probe, instance_probe, proxy_counters
from app.services.instance_registry import EVICTED, OFFLINE, ONLINE, RECOVERED, InstanceRegistry

_SNAPSHOT_TTL_S = 2.0
# 边沿事件 → 指标列名（Task 7 的 EVICTED/RECOVERED 是事件标签，落库键必须是 §5.2 的列）
_EDGE_COUNTERS = {EVICTED: "evict_count", RECOVERED: "recover_count"}

registry = InstanceRegistry(fail_threshold=allocator.fail_threshold, recover_threshold=allocator.recover_threshold)
_snapshot_cache: tuple[float, dict[str, Any]] | None = None


def reset_for_tests() -> None:
    """重新绑定模块级注册表。下游模块（allocator_store / allocator）必须采用
    `instance_monitor.registry` 的晚绑定形式，否则测试里拿到的还是旧对象。"""
    global registry, _snapshot_cache
    registry = InstanceRegistry(fail_threshold=allocator.fail_threshold, recover_threshold=allocator.recover_threshold)
    _snapshot_cache = None


def refresh_specs(session: Session) -> None:
    rows = InstanceRepository(session).list_all()
    registry.sync([(r.instance_id, r.base_url, r.weight, r.enabled, r.drain_requested) for r in rows])


def _write_metric(session: Session, instance_id: str, *, kind: str, counters: dict[str, int] | None = None) -> None:
    state = registry.get(instance_id)
    if state is None:
        return
    pool = state.pool
    row = {
        "instance_id": instance_id,
        "observed_at": datetime.now(UTC),
        "observed_by": allocator.resolved_console_id,
        "kind": kind,
        # NULL=不可得：offline 的实例绝不写 0（spec §5.2）。
        "size": pool.size if pool else None,
        "in_use": pool.in_use if pool else None,
        "free": state.effective_free if pool else None,
        "stuck": pool.stuck if pool else None,
        "status": state.status,
        "probe_ms": state.probe_ms,
    }
    row.update(counters or {})
    InstanceMetricRepository(session).insert_many([row])


def probe_all(session: Session) -> None:
    """一轮巡检：对每个已注册实例探测一次，状态跳变即时落指标。"""
    refresh_specs(session)
    for instance_id, state in list(registry.snapshot().items()):
        before = state.status
        try:
            probe = instance_probe.probe_pool(state.base_url, timeout=allocator.probe_timeout_s)
        except Exception as exc:  # noqa: BLE001 - 单台异常不能杀整轮（spec §9）
            logger.warning("probe {} raised: {}", instance_id, exc)
            state = registry.observe_failure(instance_id, f"{type(exc).__name__}: {exc}")
        else:
            if probe.ok and probe.state is not None:
                state = registry.observe_success(instance_id, probe.state, probe.probe_ms)
            else:
                state = registry.observe_failure(instance_id, probe.error)
        if state.status != before:
            # 边沿计数：摘除/恢复各 +1，只写进这一行 state_change（spec §10）
            counters: dict[str, int] = {}
            if state.status == OFFLINE and before != OFFLINE:
                counters[_EDGE_COUNTERS[EVICTED]] = 1
            elif state.status == ONLINE and before == OFFLINE:
                counters[_EDGE_COUNTERS[RECOVERED]] = 1
            _write_metric(session, instance_id, kind="state_change", counters=counters)
    _invalidate_cache()


def apply_capabilities(reports: dict[str, capability_probe.CapabilityReport]) -> None:
    """把能力指纹写进注册表（spec §5.1）。

    能力是派生状态：只驻留内存，不落 `param_instance_metric`——那张表的列语义是
    槽位（size/in_use/free/stuck），塞进代理/能力信息会让两套口径混在一张表里。
    """
    for instance_id, report in reports.items():
        state = registry.get(instance_id)
        if state is None:
            continue
        state.capabilities = report.available
        state.capability_issues = dict(report.issues)
    _invalidate_cache()


async def probe_capabilities_round() -> None:
    """能力轮：与容量轮分开的一轮（spec §5.1）。

    容量轮是同步串行的（probe_all），再加两个同步探测会让一轮耗时变成
    N × (2s + 声纹 + 情感)，一台慢就推迟其余。能力探测走异步并发，单台超时独立，
    且不写指标表。
    """
    base_urls = [
        (instance_id, state.base_url) for instance_id, state in registry.snapshot().items()
    ]
    if not base_urls:
        return
    reports = await capability_probe.probe_all_capabilities(
        base_urls, timeout=console.lb_capability_probe_timeout_s
    )
    apply_capabilities(reports)


def sample_metrics(session: Session, counters: dict[str, int] | None = None) -> None:
    """30s 采样：usage 顺带刷新（失败不判健康，spec §9）。

    counters 由调用方从 allocator.drain_counters() 取来（P1.4 接线）：
    全局键 `alloc_fail_no_instance` 写进每行；`alloc_ok:{id}` /
    `alloc_fail_instance_503:{id}` 只写对应实例（spec §10：窗口增量非累计）。
    """
    for instance_id, state in list(registry.snapshot().items()):
        if state.pool is not None:
            usage = instance_probe.probe_usage(state.base_url, timeout=allocator.probe_timeout_s)
            if usage is None and state.usage is not None:
                logger.warning("usage_unavailable: {}", instance_id)
            state.usage = usage
    deltas = counters or {}
    for instance_id in registry.snapshot():
        _write_metric(session, instance_id, kind="sample", counters=_counters_for(instance_id, deltas))
    _flush_proxy_metrics(session)
    _invalidate_cache()


def _flush_proxy_metrics(session: Session) -> None:
    """把代理侧的窗口计数落到 param_proxy_metric（spec §7）。

    代理每请求 bump 一次内存计数，真正落库在这里做——每请求写一次 DB 太重，
    而 30s 窗口增量正好和这张表的语义一致。
    """
    from app.repositories.proxy_metric_repository import (  # noqa: PLC0415 - 避免 import 环
        ProxyMetricRepository,
    )

    rows = proxy_counters.drain()
    if not rows:
        return
    now = datetime.now(UTC)
    prepared = [{**row, "observed_at": now, "observed_by": allocator.resolved_console_id} for row in rows]
    ProxyMetricRepository(session).insert_many(prepared)


def _counters_for(instance_id: str, deltas: dict[str, int]) -> dict[str, int] | None:
    out: dict[str, int] = {}
    if "alloc_fail_no_instance" in deltas:
        out["alloc_fail_no_instance"] = deltas["alloc_fail_no_instance"]
    if f"alloc_ok:{instance_id}" in deltas:
        out["alloc_ok"] = deltas[f"alloc_ok:{instance_id}"]
    if f"alloc_fail_instance_503:{instance_id}" in deltas:
        out["alloc_fail_instance_503"] = deltas[f"alloc_fail_instance_503:{instance_id}"]
    return out or None


def prune_metrics(session: Session) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=allocator.metric_retention_days)
    return InstanceMetricRepository(session).prune_before(cutoff)


def _invalidate_cache() -> None:
    global _snapshot_cache
    _snapshot_cache = None


def invalidate() -> None:
    """发布成功后调用，让面板立即反映新状态（spec §9.1）。"""
    _invalidate_cache()


def snapshot() -> dict[str, Any]:
    """读接口的 2s 防抖入口；巡检写入时已失效，这里只防读侧风暴。"""
    global _snapshot_cache
    now = time.monotonic()
    if _snapshot_cache and now - _snapshot_cache[0] < _SNAPSHOT_TTL_S:
        return _snapshot_cache[1]
    data = registry.snapshot()
    _snapshot_cache = (now, data)
    return data


async def run_forever() -> None:
    """lifespan 启停（与 turn_latency_indexer.run_forever 同模式）。

    每 tick：probe_all；每 lb_capability_interval_s 一次能力轮；每 usage_interval_s
    一次 sample_metrics；每小时一次 prune。任何异常只记日志，循环不死（spec §9/§15 P1.2）。
    """
    from app.db.database import SessionLocal  # noqa: PLC0415 - 避免 import 环

    ticks = 0
    pruned_after_s = 3600
    last_prune = time.monotonic()
    last_capability = time.monotonic()
    while True:
        await asyncio.sleep(allocator.probe_interval_s)
        session = SessionLocal()
        try:
            await asyncio.to_thread(probe_all, session)
            # 能力轮独立于容量轮：慢的一台不许拖住整轮（spec §5.1）。
            if time.monotonic() - last_capability >= console.lb_capability_interval_s:
                last_capability = time.monotonic()
                await probe_capabilities_round()
            ticks += 1
            if ticks * allocator.probe_interval_s >= allocator.usage_interval_s:
                ticks = 0
                # P1.4 交付后 allocator 已存在：窗口增量从计数器取（spec §10）。
                from app.services import allocator as allocator_service  # noqa: PLC0415

                deltas = allocator_service.drain_counters()
                await asyncio.to_thread(sample_metrics, session, deltas)
            if time.monotonic() - last_prune >= pruned_after_s:
                last_prune = time.monotonic()
                await asyncio.to_thread(prune_metrics, session)
        except Exception as exc:  # noqa: BLE001
            logger.warning("instance monitor tick failed: {}", exc)
            session.rollback()
        finally:
            session.close()
