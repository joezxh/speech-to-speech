"""A.11: what the console needs before it renders anything at all."""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import text

from app.config import allocator, auth, console
from app.repositories.instance_repository import InstanceRepository
from app.repositories.version_repository import VersionRepository
from app.services import catalog_service, pool, process_probe, validator_service


def _db_ok(db) -> bool:
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


def _pipeline_ok(info, reachable: bool) -> bool:
    """The top bar's one word. `running` comes from supervisor, which only exists
    inside the deployment container; on a dev box (`RESTART_MODE=noop`) the probe
    answers `unknown`, and then `/v1/pool` is the honest witness: if it answers,
    the pipeline is serving the exact endpoint the voice link dials.
    """
    if not reachable:
        return False
    return info.running or info.state == "unknown"


def snapshot(db, profile: str) -> dict[str, Any]:
    """Never raises for a downstream failure: A.11 wants a 200 with the facts."""
    db_ok = _db_ok(db)
    latest = VersionRepository(db).latest_live(profile) if db_ok else None
    info = process_probe.get_probe().state(console.supervisor_program)
    reachable = pool.read_pool().reachable
    # P1.3 (spec §12): allocator/seed state, guarded so a dead DB still yields a 200.
    instances_registered = len(InstanceRepository(db).list_all()) if db_ok else 0
    secrets_consistent = all(
        (
            auth.jwt_secret_key,
            os.environ.get("USAGE_HASH_SECRET", ""),
            os.environ.get("S2S_ADMIN_TOKEN", ""),
            os.environ.get("S2S_INTERNAL_TOKEN", ""),
        )
    )
    return {
        "profile": profile,
        "version": int(latest.version) if latest else None,
        "status": latest.status if latest else "unknown",
        "catalogCommit": catalog_service.load().generated_from,
        "validatorMode": validator_service.mode(),
        "db": "ok" if db_ok else "unavailable",
        "pipeline": "ok" if _pipeline_ok(info, reachable) else "unreachable",
        "internalTokenConfigured": bool(os.environ.get("S2S_INTERNAL_TOKEN", "").strip()),
        "allocatorMode": allocator.mode,
        "instancesRegistered": instances_registered,
        "seedConfigured": bool(allocator.seed_path.strip()),
        "consoleId": allocator.resolved_console_id,
        "secretsConsistent": bool(secrets_consistent),
    }
