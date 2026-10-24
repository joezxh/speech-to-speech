"""Steps 2–9 of chain A: render, validate, write, restart, probe, revert.

`render` (steps 2–4) is pure. `publish`/`rollback` below own the writes, which
is what keeps the rollback ordering reviewable in one place (A.5/A.6).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn

import yaml
from loguru import logger

from app.config import console
from app.core.errors import ApiError
from app.repositories.audit_repository import AuditRepository
from app.repositories.draft_repository import DraftRepository
from app.repositories.version_repository import VersionRepository
from app.services import (
    catalog_service,
    pool,
    renderer_service,
    restart_runner,
    validator_service,
)


@dataclass(frozen=True)
class Rendered:
    """What a set of values turns into, before anything is written."""

    text: str
    values: dict[str, Any]
    applied: list[str] = field(default_factory=list)
    env_text: str | None = None
    expected_size: int | None = None
    resolved: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)


def profile_path(profile: str) -> Path:
    return Path(console.param_config_dir) / f"{profile}.yaml"


def env_path(profile: str) -> Path:
    """`config/<profile>.env`, the file compose names in `env_file`.

    Not `.env`: compose reads that from the project root for its own variable
    interpolation, and writing there would leave the container still reading
    the values this publish was supposed to replace.
    """
    return Path(console.param_config_dir) / f"{profile}.env"


def require_profile(profile: str) -> Path:
    path = profile_path(profile)
    if not path.is_file():
        raise ApiError("unknown_profile", f"{path.name} does not exist", 404)
    return path


def entries() -> dict[str, catalog_service.Entry]:
    loaded = catalog_service.load()
    if not loaded.available:
        raise ApiError("catalog_unavailable", loaded.hint or "catalog not mounted", 503)
    return loaded.by_key()


def live_version(profile: str, versions) -> int:
    """0 when nothing has been published yet, which is what `If-Match` compares."""
    latest = versions.latest_live(profile)
    return int(latest.version) if latest else 0


def render(profile: str, values: dict[str, Any], *, environ: dict[str, str] | None = None) -> Rendered:
    """`config/<profile>.yaml` plus `values`, validated. Nothing is written.

    A refused key aborts the render: publishing the half of a patch that
    happened to apply is how a deployed file ends up different from the one
    that was reviewed.
    """
    path = require_profile(profile)
    known = entries()
    base = renderer_service.load_base(path)
    yaml_patches, env_patches = renderer_service.split_patches(values, known)
    text, applied, refused = renderer_service.render_yaml(base, profile, yaml_patches, known)
    if refused:
        raise ApiError(
            "invalid_parameter",
            "some parameters have no place in this profile's YAML",
            400,
            detail=refused,
        )

    env_text: str | None = None
    if env_patches:
        existing = env_path(profile).read_text(encoding="utf-8") if env_path(profile).is_file() else ""
        env_text, _ = renderer_service.render_env(existing, env_patches)

    # The rendered `.env` wins over the process environment: it is the file the
    # container will actually read.
    merged = {**os.environ, **renderer_service.parse_env(env_text or ""), **(environ or {})}
    result = validator_service.validate(
        text, profile, entries=known, patches=values, environ=merged, vram_gb=vram_budget()
    )
    if not result["ok"]:
        raise ApiError(
            validation_code(result["errors"]),
            "the rendered profile does not pass validation",
            422,
            detail=result["errors"],
        )

    return Rendered(
        text=text,
        values=values,
        applied=applied,
        env_text=env_text,
        expected_size=expected_size(result, text, profile),
        resolved=result["resolved"],
        warnings=result["warnings"],
    )


def validation_code(errors: list[dict[str, Any]]) -> str:
    """A budget failure is a different answer than a typo; A.5 separates them."""
    for error in errors:
        if error.get("field") == "runtime.num_pipelines" and error.get("details"):
            return "vram_budget_exceeded"
    return "validation_failed"


def expected_size(result: dict[str, Any], text: str, profile: str) -> int | None:
    """How many units the new YAML asks for, or None when that cannot be known.

    `{env: N}` for `num_pipelines` only resolves at startup, so the pool is then
    judged on reachability alone — inventing a size and failing on it would
    refuse a config that is actually correct.
    """
    count = (result.get("resolved") or {}).get("num_pipelines")
    if type(count) is int:
        return count
    try:
        document = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return None
    pipeline = (document.get("pipelines") or {}).get(profile)
    if not isinstance(pipeline, dict):
        return None
    count = pipeline.get("num_pipelines", 1)
    return count if type(count) is int else None


def _float_env(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        from loguru import logger

        logger.warning("ignoring {}={!r}: not a number", name, raw)
        return None


def vram_budget() -> float | None:
    return _float_env("PARAM_VRAM_GB")


def health_timeout() -> float:
    return _float_env("PARAM_HEALTH_TIMEOUT") or 180.0


# ── chain A steps 5–9 ───────────────────────────────────────────────────────

# Only these two states are valid rollback targets (§4.3).
ROLLBACKABLE = frozenset({"live", "rolled_back"})

# The two logs supervisor writes (§10.3): read-only, tailed 200 lines.
PIPELINE_LOGS = (
    "/var/log/supervisor/pipeline-stdout.log",
    "/var/log/supervisor/pipeline-stderr.log",
)

# One publish at a time. The lock is per process, which is why the console must
# run a single worker (A.5): two workers would each hold their own lock.
_lock = threading.Lock()


def _exclusive() -> None:
    if not _lock.acquire(blocking=False):
        raise ApiError(
            code="publish_in_progress",
            message="another publish or rollback is running for this deployment",
            status=409,
        )


def _finish(
    repo: VersionRepository,
    row,
    status: str,
    *,
    error_code: str | None = None,
    duration_s: float | None = None,
):
    """`set_status` rewrites every field, so `rolled_back_to` must be passed back.

    Otherwise a rollback version turned `live` forgets which version it came
    from, and the audit trail loses the one fact that explains it.
    """
    return repo.set_status(
        row,
        status,
        error_code=error_code,
        duration_s=duration_s,
        rolled_back_to=row.rolled_back_to,
    )


def _audit(
    db,
    action: str,
    profile: str,
    *,
    actor: str,
    role: str,
    version: int,
    result: str,
    fields: list[str],
    error_code: str | None = None,
    duration_s: float | None = None,
    request_id: str = "",
):
    return AuditRepository(db).record(
        actor=actor,
        role=role,
        action=action,
        profile=profile,
        fields=list(fields),
        result=result,
        version=version,
        error_code=error_code,
        duration_s=duration_s,
        request_id=request_id,
    )


def publish(
    db,
    profile: str,
    *,
    base_version: int | None = None,
    note: str = "",
    actor: str = "",
    role: str = "",
    request_id: str = "",
) -> dict[str, Any]:
    """A.5. No parameters ride along: patches only reach disk via A.3 first."""
    started = time.monotonic()
    _exclusive()
    try:
        require_profile(profile)
        known = entries()
        drafts = DraftRepository(db)
        draft = drafts.get(profile)
        if draft is None or not draft.patch:
            raise ApiError(code="no_draft", message="there is nothing to publish", status=404)

        versions = VersionRepository(db)
        current = live_version(profile, versions)
        if base_version is not None and base_version != current:
            raise ApiError(
                code="version_conflict",
                message=f"the live version moved to {current}",
                status=409,
                detail=[{"expected": current, "got": base_version}],
            )

        # Step 5: refuse before writing anything, and before versioning (§4.2).
        # An `.env` value cannot take effect without recreating the container,
        # so accepting it here would leave a `publishing` row nothing can make
        # live.
        _, env_patches = renderer_service.split_patches(draft.patch, known)
        if env_patches:
            raise ApiError(
                code="env_requires_recreate",
                message="these variables only take effect in a recreated container",
                status=409,
                detail=[{"var": name} for name in sorted(env_patches)],
            )

        rendered = render(profile, draft.patch)  # 422 is raised here; the draft stays

        row = versions.create(
            profile,
            status="publishing",
            yaml_text=rendered.text,
            env_sha256=_sha(rendered.env_text or ""),
            note=note,
            author=actor,
        )
        result = _deploy(
            db,
            profile,
            rendered,
            row,
            actor=actor,
            role=role,
            note=note,
            started=started,
            request_id=request_id,
        )
        drafts.drop(profile)
        return result
    finally:
        _lock.release()


def rollback(
    db,
    profile: str,
    *,
    target_version: int,
    note: str = "",
    actor: str = "",
    role: str = "",
    request_id: str = "",
) -> dict[str, Any]:
    """A.6: a rollback creates a new version, it never deletes the old one.

    What is written to disk is the target's stored bytes, not “re-render its
    patch”: re-rendering applies an old patch to a new file, producing a config
    that never ran anywhere.
    """
    started = time.monotonic()
    _exclusive()
    try:
        require_profile(profile)
        versions = VersionRepository(db)
        target = versions.get(profile, target_version)
        if target is None:
            raise ApiError(
                code="unknown_version",
                message=f"version {target_version} does not exist",
                status=404,
            )
        if target.status not in ROLLBACKABLE:
            raise ApiError(
                code="version_not_rollbackable",
                message=f"version {target_version} is {target.status}, not a rollback target",
                status=409,
                detail=[{"status": target.status, "allowed": sorted(ROLLBACKABLE)}],
            )
        if not target.yaml_text:
            raise ApiError(
                code="version_not_rollbackable",
                message=f"version {target_version} has no stored rendering",
                status=409,
            )

        # Re-validating is not paranoia: after a move the paths may be gone, a
        # model may have been deleted, `{env:}` may have been rotated.
        known = entries()
        result = validator_service.validate(
            target.yaml_text, profile, entries=known, environ=os.environ, vram_gb=vram_budget()
        )
        if not result["ok"]:
            raise ApiError(
                code=validation_code(result["errors"]),
                message=f"version {target_version} no longer validates on this machine",
                status=422,
                detail=result["errors"],
            )

        row = versions.create(
            profile,
            status="publishing",
            yaml_text=target.yaml_text,
            env_sha256=target.env_sha256,
            note=note or f"rollback to v{target_version}",
            author=actor,
        )
        versions.set_status(row, "publishing", rolled_back_to=target_version)
        rendered = Rendered(
            text=target.yaml_text,
            values={},
            applied=[],
            expected_size=expected_size(result, target.yaml_text, profile),
            resolved=result["resolved"],
            warnings=result["warnings"],
        )
        outcome = _deploy(
            db,
            profile,
            rendered,
            row,
            actor=actor,
            role=role,
            note=note,
            started=started,
            request_id=request_id,
        )
        outcome["rolledBackTo"] = target_version
        return outcome
    finally:
        _lock.release()


def _deploy(
    db,
    profile: str,
    rendered: Rendered,
    row,
    *,
    actor: str,
    role: str,
    note: str,
    started: float,
    request_id: str,
) -> dict[str, Any]:
    """Steps 6–8. The caller holds `_lock`."""
    versions = VersionRepository(db)
    snapshot = _backup(profile, rendered, row.version)

    try:
        _write(profile_path(profile), rendered.text)
        if rendered.env_text is not None:
            _write(env_path(profile), rendered.env_text)
    except OSError as exc:
        _undo(snapshot, profile)
        _finish(versions, row, "aborted", error_code="render_failed")
        _audit(
            db,
            "publish.aborted",
            profile,
            actor=actor,
            role=role,
            version=row.version,
            result="aborted",
            fields=sorted(rendered.values),
            error_code="render_failed",
            duration_s=round(time.monotonic() - started, 3),
            request_id=request_id,
        )
        raise ApiError(
            code="render_failed",
            message="the rendered profile could not be written",
            status=500,
        ) from exc

    expected = rendered.expected_size
    if expected is None:
        # `num_pipelines` is `{env: N}` — the real size only exists after the
        # restart. Using the current size as the baseline at least never fails
        # on a number invented here.
        running = pool.read_pool()
        expected = running.size if running.reachable else 1

    try:
        restart_runner.restart()
    except ApiError as exc:
        _revert(
            db,
            profile,
            row,
            snapshot,
            actor=actor,
            role=role,
            started=started,
            request_id=request_id,
            code="restart_unavailable",
            status=502,
            reason=exc.message,
            expected=expected,
        )

    health = pool.wait_healthy(expected, timeout=health_timeout())
    if not health.ok:
        _revert(
            db,
            profile,
            row,
            snapshot,
            actor=actor,
            role=role,
            started=started,
            request_id=request_id,
            code="healthcheck_timeout",
            status=504,
            reason=health.reason,
            expected=expected,
        )

    duration = round(time.monotonic() - started, 1)
    _finish(versions, row, "live", duration_s=duration)
    audit = _audit(
        db,
        "publish.live",
        profile,
        actor=actor,
        role=role,
        version=row.version,
        result="live",
        fields=rendered.applied,
        duration_s=duration,
        request_id=request_id,
    )
    return {
        "version": row.version,
        "status": "live",
        "healthcheck": {
            "poolSize": health.pool.size if health.pool else None,
            "inUse": health.pool.in_use if health.pool else None,
            "attempts": health.attempts,
            "notes": health.notes,
        },
        "durationS": duration,
        "applied": rendered.applied,
        "warnings": rendered.warnings,
        "auditId": str(audit.id),
    }


def _revert(
    db,
    profile: str,
    row,
    snapshot: _Snapshot,
    *,
    actor: str,
    role: str,
    started: float,
    request_id: str,
    code: str,
    status: int,
    reason: str,
    expected: int,
) -> NoReturn:
    """Step 9. Never returns: reports either `rolled_back` or `rollback_failed`.

    `rollback_failed` is reserved for the case where the files could not even be
    restored — that is the only state where what runs on disk is unverified and
    needs a human (§4.1 step 9). A restore that succeeded but could not be
    re-probed is still a completed rollback: the bytes are the ones that ran
    before, `verified: false` says nobody watched them come back up.
    """
    versions = VersionRepository(db)
    restored = _undo(snapshot, profile)
    restored_ok = all(restored.values())
    log_tail = _tail_logs()
    duration = round(time.monotonic() - started, 3)

    if not restored_ok:
        _finish(
            versions,
            row,
            "failed",
            error_code="rollback_failed",
            duration_s=round(time.monotonic() - started, 1),
        )
        _audit(
            db,
            "publish.failed",
            profile,
            actor=actor,
            role=role,
            version=row.version,
            result="failed",
            fields=[],
            error_code="rollback_failed",
            duration_s=duration,
            request_id=request_id,
        )
        raise ApiError(
            code="rollback_failed",
            message=f"{reason}; the automatic revert also failed — this needs a human",
            status=500,
            detail=[{"reason": reason, "restored": restored, "logs": log_tail}],
        )

    verified = False
    try:
        restart_runner.restart()
        verified = pool.wait_healthy(expected, timeout=health_timeout()).ok
    except ApiError as exc:
        logger.warning("revert restart for {} v{} failed: {}", profile, row.version, exc.message)

    _finish(
        versions,
        row,
        "rolled_back",
        error_code=code,
        duration_s=round(time.monotonic() - started, 1),
    )
    _audit(
        db,
        "publish.rolled_back",
        profile,
        actor=actor,
        role=role,
        version=row.version,
        result="rolled_back",
        fields=[],
        error_code=code,
        duration_s=duration,
        request_id=request_id,
    )
    raise ApiError(
        code=code,
        message=reason,
        status=status,
        detail=[{"status": "rolled_back", "version": row.version, "verified": verified, **restored}],
    )


def recover_pending(db) -> list[dict[str, Any]]:
    """Startup self-check (§4.1 tail): finish publishes cut off between 6 and 9."""
    versions = VersionRepository(db)
    outcomes: list[dict[str, Any]] = []
    for row in versions.dangling():
        path = profile_path(row.profile)
        on_disk = path.read_text(encoding="utf-8") if path.is_file() else ""
        state = pool.read_pool()

        if state.reachable and not state.stuck and _sha(on_disk) == row.yaml_sha256:
            _finish(versions, row, "live")
            outcomes.append({"profile": row.profile, "version": row.version, "status": "live"})
            continue

        restored = restore(_backup_path(row.profile, row.version), path)
        try:
            restart_runner.restart()
        except ApiError as exc:
            logger.warning(
                "recovery restart for {} v{} failed: {}", row.profile, row.version, exc.message
            )
        _finish(versions, row, "rolled_back", error_code="restart_interrupted")
        outcomes.append(
            {
                "profile": row.profile,
                "version": row.version,
                "status": "rolled_back",
                "restored": restored,
            }
        )
    return outcomes


# ── file layer ──────────────────────────────────────────────────────────────


def _sha(text: str) -> str:
    """Must match the algorithm `version_repository` uses for `yaml_sha256`."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _backup_path(profile: str, version: int) -> Path:
    path = profile_path(profile)
    return path.with_suffix(path.suffix + f".bak.{version}")


def backup(path: Path, version: int) -> Path | None:
    if not path.is_file():
        return None
    target = path.with_suffix(path.suffix + f".bak.{version}")
    shutil.copy2(path, target)
    return target


def restore(source: Path | None, target: Path) -> bool:
    if source is None or not source.is_file():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def _write(path: Path, text: str) -> None:
    """One-step replace, so a crash never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


@dataclass(frozen=True)
class _Snapshot:
    yaml: Path | None
    env: Path | None
    env_written: bool = False


def _backup(profile: str, rendered: Rendered, version: int) -> _Snapshot:
    writes_env = rendered.env_text is not None
    return _Snapshot(
        yaml=backup(profile_path(profile), version),
        env=backup(env_path(profile), version) if writes_env else None,
        env_written=writes_env,
    )


def _undo(snapshot: _Snapshot, profile: str) -> dict[str, bool]:
    """Both restore, or neither counts as restored."""
    yaml_ok = restore(snapshot.yaml, profile_path(profile))
    env_ok = _restore_env(snapshot, profile)
    # A missing backup is not a failure when there was nothing to back up: the
    # file did not exist before the publish, so “the old state” is still there.
    return {"yaml": yaml_ok or not snapshot.yaml, "env": env_ok}


def _restore_env(snapshot: _Snapshot, profile: str) -> bool:
    if not snapshot.env_written:
        return True
    if snapshot.env is not None:
        return restore(snapshot.env, env_path(profile))
    # The publish created this file; undoing means removing it, otherwise the
    # secrets it carries outlive the version that failed.
    try:
        env_path(profile).unlink(missing_ok=True)
    except OSError as exc:
        logger.error("could not remove {}: {}", env_path(profile), exc)
        return False
    return True


def _tail_logs(lines: int = 200) -> list[str]:
    out: list[str] = []
    for name in PIPELINE_LOGS:
        path = Path(name)
        if not path.is_file():
            continue
        try:
            out.extend(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
        except OSError:
            continue
    return out
