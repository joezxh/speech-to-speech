"""A.10: one read-only aggregate so the instance page calls one endpoint (B1)."""

from __future__ import annotations

import os
from typing import Any

from app.config import console
from app.services import pool, process_probe


def collect(profile: str, version: int | None) -> dict[str, Any]:
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
        # Still called `container`: one container, one pipeline process inside it.
        # startedAt/image come from the image label when the deploy sets it;
        # the console cannot ask docker (no socket, §10.1).
        "container": {
            "name": info.name,
            "status": "running" if info.running else (info.state or "unknown"),
            "startedAt": None,
            "image": os.environ.get("S2S_IMAGE", "").strip(),
            "pid": info.pid,
            "detail": info.detail,
        },
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
