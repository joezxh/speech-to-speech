"""Chain A — spec §4.1 steps 1 to 8, in one place, for one profile.

The ordering is the design. Validation runs on the *rendered text*, not on the
patch, because a patch that is fine on its own can still produce a document the
runtime rejects. The version row is created before the files are written,
because the backup is named after it and because a failed write has to leave a
row marked `aborted` rather than no trace at all. The health check runs after
`compose up`, because a compose exit code says the container started, not that
the new YAML took effect.

Every failure after the files are touched restores both backups (the YAML and
the `.env` it may have come with) and re-runs the container, so the files on
disk and the process in memory agree at the end of every path through this
module. When even that fails the version is marked `failed`, the one state that
means a human has to look.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from param_platform import catalog, compose_runner, renderer, store, validator

logger = logging.getLogger("s2s.params")


class FlowError(Exception):
    """A refusal carrying the HTTP status and error code spec §13 A.0 asks for."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int = 400,
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or []


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


# ── locations ────────────────────────────────────────────────────────────────


def profile_path(profile: str) -> Path:
    return compose_runner.config_dir() / f"{profile}.yaml"


def env_path(profile: str) -> Path:
    """`config/<profile>.env`, the file `docker-compose.yml` names in `env_file`.

    Not `.env`: compose reads that from the project root for its own variable
    interpolation, and writing there would leave the container still reading the
    values this publish was supposed to replace.
    """
    return compose_runner.config_dir() / f"{profile}.env"


def entries() -> dict[str, Any]:
    loaded = catalog.load()
    if not loaded.available:
        raise FlowError("catalog_unavailable", loaded.hint, status=503)
    return loaded.by_key()


def live_version(profile: str) -> int:
    """0 when nothing has been published yet, which is what `If-Match` compares."""
    latest = store.latest_live(profile)
    return int(latest["version"]) if latest else 0


# ── rendering and validation (steps 2 to 4) ──────────────────────────────────


def render(
    profile: str,
    values: dict[str, Any],
    *,
    environ: dict[str, str] | None = None,
) -> Rendered:
    """`config/<profile>.yaml` plus `values`, validated. Nothing is written.

    A refused key aborts the render: publishing the half of a patch that
    happened to apply is how a file ends up different from the one that was
    reviewed.
    """
    path = profile_path(profile)
    if not path.is_file():
        raise FlowError(
            "unknown_profile",
            f"{path} does not exist; create the profile before editing it",
            status=404,
        )

    known = entries()
    base = renderer.load_base(path)
    yaml_patches, env_patches = renderer.split_patches(values, known)
    text, applied, refused = renderer.render_yaml(base, profile, yaml_patches, known)
    if refused:
        raise FlowError(
            "invalid_parameter",
            "some parameters have no place in this profile's YAML",
            status=400,
            details=refused,
        )

    env_text: str | None = None
    if env_patches:
        existing = env_path(profile).read_text(encoding="utf-8") if env_path(profile).is_file() else ""
        env_text, _ = renderer.render_env(existing, env_patches)

    # The rendered `.env` wins over the process environment: it is the file the
    # container will actually read.
    merged = {**os.environ, **renderer.parse_env(env_text or ""), **(environ or {})}
    result = validator.validate(
        text,
        profile,
        entries=known,
        patches=values,
        environ=merged,
        vram_gb=vram_budget(),
    )
    if not result["ok"]:
        raise FlowError(
            validation_code(result["errors"]),
            "the rendered profile does not pass validation",
            status=422,
            details=result["errors"],
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
    """A budget failure is a different answer than a typo; A.4 separates them."""
    for error in errors:
        if error.get("field") == "runtime.num_pipelines" and error.get("details"):
            return "vram_budget_exceeded"
    return "validation_failed"


def expected_size(result: dict[str, Any], text: str, profile: str) -> int | None:
    """How many units the new YAML asks for, or None when that cannot be known.

    `{env: N}` for `num_pipelines` only resolves at startup, so in that case the
    pool is judged on reachability alone — inventing a size and failing on it
    would refuse a config that is actually correct.
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


# ── publish and rollback ─────────────────────────────────────────────────────

_guard = threading.Lock()


def _exclusive() -> None:
    """A second write gets a 409 instead of racing the first one's backup."""
    if not _guard.acquire(blocking=False):
        raise FlowError(
            "publish_in_progress",
            "another publish or rollback is running for this deployment",
            status=409,
        )


def publish(
    profile: str,
    *,
    base_version: int | None = None,
    note: str = "",
    actor: str = "",
) -> dict[str, Any]:
    started = time.monotonic()
    _exclusive()
    try:
        draft = store.get_draft(profile)
        if draft is None or not draft.get("values"):
            raise FlowError("no_draft", "there is nothing to publish", status=404)

        current = live_version(profile)
        if base_version is not None and base_version != current:
            raise FlowError(
                "version_conflict",
                f"the live version moved to {current}",
                status=409,
                details=[{"expected": current, "got": base_version}],
            )

        rendered = render(profile, draft["values"])
        version = store.create_version(
            profile,
            rendered.values,
            rendered=rendered.text,
            note=note,
            actor=actor,
            base_version=current,
        )
        result = _deploy(profile, rendered, version, actor, note, started)
        store.drop_draft(profile)
        return result
    finally:
        _guard.release()


def rollback(
    profile: str,
    *,
    target_version: int,
    note: str = "",
    actor: str = "",
) -> dict[str, Any]:
    """Restore a past version as a *new* version, per A.5.

    The stored text is written verbatim rather than re-rendered from its
    patches: re-rendering would apply an old patch on top of a newer file and
    produce a config that never ran.
    """
    started = time.monotonic()
    _exclusive()
    try:
        target = store.get_version(target_version)
        if target is None or target["profile"] != profile:
            raise FlowError(
                "unknown_version", f"version {target_version} does not exist", status=404
            )
        if target["status"] not in store.ROLLBACKABLE:
            raise FlowError(
                "version_not_rollbackable",
                f"version {target_version} is {target['status']}, not a rollback target",
                status=409,
                details=[{"status": target["status"], "allowed": list(store.ROLLBACKABLE)}],
            )
        if not target["rendered"]:
            raise FlowError(
                "version_not_rollbackable",
                f"version {target_version} has no stored rendering; republish it instead",
                status=409,
            )

        # Re-validating is not paranoia: the machine may have moved, a model may
        # be gone, an `{env:}` value may have been rotated. Restoring a config
        # that cannot start is worse than refusing.
        result = validator.validate(
            target["rendered"],
            profile,
            entries=entries(),
            environ=os.environ,
            vram_gb=vram_budget(),
        )
        if not result["ok"]:
            raise FlowError(
                validation_code(result["errors"]),
                f"version {target_version} no longer validates on this machine",
                status=422,
                details=result["errors"],
            )

        version = store.create_version(
            profile,
            target["values"],
            rendered=target["rendered"],
            note=note or f"rollback to v{target_version}",
            actor=actor,
            base_version=live_version(profile),
            rolled_back_to=target_version,
        )
        rendered = Rendered(
            text=target["rendered"],
            values=target["values"],
            applied=sorted(target["values"]),
            expected_size=expected_size(result, target["rendered"], profile),
            resolved=result["resolved"],
        )
        return _deploy(profile, rendered, version, actor, note, started)
    finally:
        _guard.release()


# ── steps 5 to 8 (caller holds the guard) ────────────────────────────────────


def _deploy(
    profile: str,
    rendered: Rendered,
    version: int,
    actor: str,
    note: str,
    started: float,
) -> dict[str, Any]:
    usable, reason = compose_runner.available()
    if not usable:
        # Refused before the files are touched, so nothing has to be undone.
        store.set_status(version, "aborted", reason)
        _audit("publish.aborted", profile, actor, version, "aborted", {"reason": reason}, started)
        raise FlowError("compose_unavailable", reason, status=503)

    # Both files are copied before either is written. A publish that changed
    # `.env` and then failed its health check must not leave the new secrets
    # sitting next to the old YAML, where the next `compose up` would read the
    # pair nobody validated.
    snapshot = _backup(profile, rendered, version)
    began = time.monotonic()

    try:
        _write(profile_path(profile), rendered.text)
        if rendered.env_text is not None:
            _write(env_path(profile), rendered.env_text)
    except OSError as exc:
        _undo(snapshot, profile)
        store.set_status(version, "aborted", f"write failed: {exc}")
        _audit("publish.aborted", profile, actor, version, "aborted", {"reason": str(exc)}, started)
        raise FlowError("write_failed", str(exc), status=500) from exc

    store.set_status(version, "publishing")
    expected = rendered.expected_size
    if expected is None:
        # `num_pipelines` is an `{env:}` reference, so the size it resolves to is
        # not knowable here; whatever is running now is the only size to hold
        # the publish to, and a stuck unit still fails it.
        running = compose_runner.read_pool()
        expected = running.size if running.reachable else 1

    compose = compose_runner.recreate()
    if not compose.ok:
        return _revert(
            profile, version, snapshot, actor, started,
            code="compose_failed",
            status=502,
            reason=f"compose exited {compose.returncode}: {compose.stderr.strip()[:400]}",
            expected=expected,
        )

    health = compose_runner.wait_healthy(expected, timeout=health_timeout())
    if not health.ok:
        return _revert(
            profile, version, snapshot, actor, started,
            code="healthcheck_timeout",
            status=504,
            reason=health.reason,
            expected=expected,
        )

    store.set_status(version, "live")
    audit_id = _audit(
        "publish.live",
        profile,
        actor,
        version,
        "live",
        {
            "note": note,
            "applied": rendered.applied,
            "deploy_s": round(time.monotonic() - began, 1),
            "pool_size": health.pool.size if health.pool else None,
            "warnings": rendered.warnings,
        },
        started,
    )
    return {
        "version": version,
        "status": "live",
        "healthcheck": {
            "pool_size": health.pool.size if health.pool else None,
            "in_use": health.pool.in_use if health.pool else None,
            "attempts": health.attempts,
            "notes": health.notes,
        },
        "duration_s": round(time.monotonic() - started, 1),
        "applied": rendered.applied,
        "warnings": rendered.warnings,
        "audit_id": audit_id,
    }


def _revert(
    profile: str,
    version: int,
    snapshot: _Snapshot,
    actor: str,
    started: float,
    *,
    code: str,
    status: int,
    reason: str,
    expected: int,
) -> dict[str, Any]:
    """Step 8. Never returns a success: it either re-raises or reports a revert."""
    store.set_status(version, "rolled_back", reason)
    restored = _undo(snapshot, profile)
    detail: dict[str, Any] = {
        "reason": reason,
        "backup": str(snapshot.yaml) if snapshot.yaml else None,
        "env_backup": str(snapshot.env) if snapshot.env else None,
        "restored": all(restored.values()),
        "restored_files": restored,
        "logs": compose_runner.logs(tail=80),
    }

    if detail["restored"]:
        compose = compose_runner.recreate()
        health = compose_runner.wait_healthy(expected, timeout=health_timeout())
        detail["revert_compose_ok"] = compose.ok
        detail["revert_health"] = health.reason
        if compose.ok and health.ok:
            _audit("publish.rolled_back", profile, actor, version, "rolled_back", detail, started)
            raise FlowError(
                code,
                reason,
                status=status,
                details=[{"status": "rolled_back", "version": version, **detail}],
            )

    # The publish failed and so did the revert: the container is running
    # something nobody verified, and only a human can settle which.
    store.set_status(version, "failed", f"{reason}; revert failed")
    _audit("publish.failed", profile, actor, version, "failed", detail, started)
    raise FlowError(
        "rollback_failed",
        f"{reason}; the automatic revert also failed — this needs a human",
        status=500,
        details=[detail],
    )


# ── small helpers ────────────────────────────────────────────────────────────


def _write(path: Path, text: str) -> None:
    """Replace `path` in one step so a crash cannot leave half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


@dataclass(frozen=True)
class _Snapshot:
    """The files a publish replaces, as they were before it ran."""

    yaml: Path | None
    env: Path | None
    env_written: bool = False


def _backup(profile: str, rendered: Rendered, version: int) -> _Snapshot:
    """Copy every file this publish will touch, under the version's name.

    The `.env` is only copied when the publish actually rewrites it: an
    untouched file needs no backup, and a rollback (which never writes one)
    must not claim to have restored what it never changed.
    """
    writes_env = rendered.env_text is not None
    return _Snapshot(
        yaml=compose_runner.backup(profile_path(profile), version),
        env=compose_runner.backup(env_path(profile), version) if writes_env else None,
        env_written=writes_env,
    )


def _undo(snapshot: _Snapshot, profile: str) -> dict[str, bool]:
    """Put both files back. Both, always — half a restore is a new config."""
    return {
        "yaml": _restore(snapshot.yaml, profile_path(profile)),
        "env": _restore_env(snapshot, profile),
    }


def _restore(previous: Path | None, path: Path) -> bool:
    return compose_runner.restore(previous, path) if previous else False


def _restore_env(snapshot: _Snapshot, profile: str) -> bool:
    if not snapshot.env_written:
        return True
    if snapshot.env is not None:
        return compose_runner.restore(snapshot.env, env_path(profile))
    # The publish created the file, so undoing it means removing it again —
    # otherwise the secrets it introduced outlive the version that failed.
    try:
        env_path(profile).unlink(missing_ok=True)
    except OSError as exc:
        logger.error("could not remove %s: %s", env_path(profile), exc)
        return False
    return True


def _audit(
    action: str,
    profile: str,
    actor: str,
    version: int,
    result: str,
    detail: dict[str, Any],
    started: float,
) -> int:
    return store.record_audit(
        action,
        profile=profile,
        actor=actor,
        version=version,
        result=result,
        detail=detail,
        duration_ms=_elapsed_ms(started),
    )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _float_env(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else None
    except ValueError:
        logger.warning("ignoring %s=%r: not a number", name, raw)
        return None


def vram_budget() -> float | None:
    return _float_env("PARAM_VRAM_GB")


def health_timeout() -> float:
    return _float_env("PARAM_HEALTH_TIMEOUT") or compose_runner.DEFAULT_TIMEOUT
