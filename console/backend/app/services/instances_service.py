"""A.10: one read-only aggregate so the instance page calls one endpoint (B1).

P1.3 (spec §11): once the registry has rows the aggregate switches to the
monitor's cached view and gains ``summary``/``instances``; with an empty
registry the legacy direct-read path runs verbatim, so every pre-registry
field and monkeypatch seam keeps working unchanged.
"""

from __future__ import annotations

import os
from typing import Any

from app.config import allocator, console
from app.repositories.instance_repository import InstanceRepository
from app.services import instance_monitor, pool, process_probe


def collect(profile: str, version: int | None, *, db) -> dict[str, Any]:
    rows = InstanceRepository(db).list_all()
    if rows:
        return _collect_registry(profile, version, rows)
    return _collect_legacy(profile, version)


def _container_block(info: process_probe.ProcessInfo) -> dict[str, Any]:
    # Still called `container`: one container, one pipeline process inside it.
    # startedAt/image come from the image label when the deploy sets it;
    # the console cannot ask docker (no socket, §10.1).
    return {
        "name": info.name,
        "status": "running" if info.running else (info.state or "unknown"),
        "startedAt": None,
        "image": os.environ.get("S2S_IMAGE", "").strip(),
        "pid": info.pid,
        "detail": info.detail,
    }


def _collect_legacy(profile: str, version: int | None) -> dict[str, Any]:
    state = pool.read_pool()
    usage = pool.read_usage() if state.reachable else None
    info = process_probe.get_probe().state(console.supervisor_program)

    alerts: list[str] = []
    if not state.reachable:
        alerts.append("pool_unreachable")
    if state.stuck:
        alerts.append("pool_stuck")
    if not info.running:
        alerts.append("pipeline_stopped")
    if state.reachable and usage is None:
        alerts.append("usage_unavailable")

    return {
        "profile": profile,
        "version": version,
        "container": _container_block(info),
        "pool": None
        if not state.reachable
        else {
            "size": state.size,
            "inUse": state.in_use,
            "units": [
                {
                    "index": unit.get("index"),
                    "state": unit.get("state"),
                    "sessionId": unit.get("session_id"),
                }
                for unit in state.units
            ],
        },
        "usage": usage,
        "alerts": alerts,
    }


def _collect_registry(
    profile: str, version: int | None, rows: list[Any]
) -> dict[str, Any]:
    view = instance_monitor.snapshot()
    local_key = next(
        (
            r.instance_id
            for r in rows
            if r.base_url.rstrip("/") == console.pipeline_base_url.rstrip("/")
        ),
        "",
    )
    local = view.get(local_key)
    info = process_probe.get_probe().state(console.supervisor_program)
    alerts: list[str] = []
    instances: list[dict[str, Any]] = []
    for row in rows:
        state = view.get(row.instance_id)
        reachable = state is not None and state.pool is not None
        if not reachable:
            error = state.pool.error if state is not None and state.pool else "not_observed"
            alerts.append(f"pool_unreachable:{row.instance_id}:{error}")
        elif state.pool.stuck:
            alerts.append(f"pool_stuck:{row.instance_id}")
        if row.max_sessions_hint and reachable and state.pool.size != row.max_sessions_hint:
            alerts.append(f"instance_capacity_mismatch:{row.instance_id}")  # spec §6.2
        instances.append(
            {
                "instance_id": row.instance_id,
                "base_url": row.base_url,
                "status": state.status if state else "unknown",
                "weight": row.weight,
                "enabled": row.enabled,
                "drain_requested": row.drain_requested,
                "size": state.pool.size if reachable else None,
                "in_use": state.pool.in_use if reachable else None,
                "free": state.effective_free if reachable else None,
                "stuck": state.pool.stuck if reachable else None,
                "probe_ms": state.probe_ms if state else None,
                "p95_probe_ms": state.p95_probe_ms if state else None,
                "units": [
                    {"index": u.get("index"), "state": u.get("state"), "sessionId": u.get("session_id")}
                    for u in (state.pool.units if reachable else ())
                ],
                "last_error": state.last_error if state else "",
                "observed_by": allocator.resolved_console_id,
                "declared_mismatch": bool(row.max_sessions_hint)
                and reachable
                and state.pool.size != row.max_sessions_hint,
            }
        )
    if not info.running:
        alerts.append("pipeline_stopped")
    # pending_grants 在 P1.4 Task 13 接 allocator.pending_count()；本阶段先置 0 保留键位
    # （前端 Task 15 已按可缺省字段处理）。
    summary = {
        "instances_total": len(instances),
        "online": sum(1 for i in instances if i["status"] == "online"),
        "offline": sum(1 for i in instances if i["status"] == "offline"),
        "degraded": sum(1 for i in instances if i["status"] == "degraded"),
        "draining": sum(1 for i in instances if i["status"] == "draining"),
        "slots_total": sum(i["size"] or 0 for i in instances),
        "slots_in_use": sum(i["in_use"] or 0 for i in instances),
        "slots_free": sum(i["free"] or 0 for i in instances),
        "pending_grants": 0,  # Task 13 接线：改 allocator.pending_count() 并删上行注释
    }
    legacy_pool = local.pool if local is not None and local.pool else None
    return {
        "profile": profile,
        "version": version,
        "container": _container_block(info),
        "pool": None
        if legacy_pool is None
        else {
            "size": legacy_pool.size,
            "inUse": legacy_pool.in_use,
            "units": [
                {
                    "index": u.get("index"),
                    "state": u.get("state"),
                    "sessionId": u.get("session_id"),
                }
                for u in legacy_pool.units
            ],
        },
        "usage": local.usage if local else None,
        "alerts": alerts,
        "summary": summary,
        "instances": instances,
    }
