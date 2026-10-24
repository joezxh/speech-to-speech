"""The admin API: spec §13 appendix A, endpoints A.1 to A.7.

Everything here is a thin HTTP layer — parse, authorize, call one flow function,
shape the response. The publish flow lives in `param_platform.publish_flow`, and
the reason is not tidiness: the eight steps have to stay in one place or the
rollback ordering stops being reviewable.

Two rules the handlers keep deliberately:

* They are `def`, not `async def`. A publish blocks for forty seconds on
  `docker compose` and the pool probe, and an `async def` handler would hold the
  event loop for all of it. FastAPI runs plain `def` handlers in a threadpool.
* Nothing is answered optimistically. A publish that has not been verified
  against `/v1/pool` says so; a catalog that is missing says so; a disabled
  admin token says so. A console that trusts a lie is worse than one that shows
  an error.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse
from param_platform import catalog, compose_runner, drafts, hot_update, publish_flow, store
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger("s2s.params")

router = APIRouter(prefix="/admin", tags=["admin"])

# Profile names become file names, so they must not be able to leave the config
# directory.
_PROFILE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")

# A.0: secrets are `***` on the way out. The catalog has no `secret` flag, so
# the name is the only signal there is; `api_key` / `token` / `secret` /
# `password` at the end of a parameter name is what those fields all share.
_SECRET_NAME = re.compile(r"(api_key|_key|token|secret|password)$", re.IGNORECASE)

# §10.1's two roles. `operator` may draft `basic` and `advanced` fields; every
# other exposure — `expert` costs an OOM if it is wrong, `ops` crosses a
# security, privacy or environment boundary — needs `admin`.
ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"
OPERATOR_EXPOSURE = frozenset({"basic", "advanced"})


# ── installation ─────────────────────────────────────────────────────────────


def install(app) -> None:
    """Mount the router and the one exception type that carries a status code."""
    app.include_router(router)
    app.add_exception_handler(publish_flow.FlowError, _flow_error)


async def _flow_error(_: Request, exc: Exception) -> JSONResponse:
    error = exc if isinstance(exc, publish_flow.FlowError) else publish_flow.FlowError(
        "internal_error", str(exc), status=500
    )
    # A.0: `message` never echoes an input value, so a secret cannot leak through
    # an error. The messages raised in publish_flow are all written that way.
    return JSONResponse(
        status_code=error.status,
        content={"error": {"code": error.code, "message": error.message, "details": error.details}},
    )


# ── request plumbing ─────────────────────────────────────────────────────────


def _admin_token() -> str:
    return os.environ.get("ADMIN_TOKEN", "").strip()


def _operator_token() -> str:
    """§10.1's second role. Unset means "this deployment has no operators"."""
    return os.environ.get("OPERATOR_TOKEN", "").strip()


def _matches(presented: str, configured: str) -> bool:
    """Constant-time: a token is a secret, and its length is part of it."""
    return bool(configured) and secrets.compare_digest(
        presented.encode("utf-8"), configured.encode("utf-8")
    )


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else ""


@dataclass(frozen=True)
class _Caller:
    """Who is asking, once the token check has said they may."""

    role: str
    actor: str

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN


def _guard(request: Request, *, write: bool) -> _Caller:
    """The caller's role and audit name, after the A.0 token check.

    A configured `ADMIN_TOKEN` gates everything. An unconfigured one gates
    writes only: a deployment that forgot to set it should refuse to change
    itself, while still letting a console render the catalog — which is public
    both in git and in content, since every secret in the YAML is a
    `{env: NAME}` reference rather than a value.

    `OPERATOR_TOKEN` is optional. With it unset there is one role, which is the
    single-operator deployment this platform mostly runs as; with it set, the
    write endpoints start telling the two apart.
    """
    configured = _admin_token()
    if not configured:
        if not write:
            return _Caller(ROLE_ADMIN, "anonymous")
        raise publish_flow.FlowError(
            "admin_disabled",
            "ADMIN_TOKEN is not configured, so the write endpoints are disabled",
            status=503,
        )

    presented = _bearer(request)
    if _matches(presented, configured):
        role = ROLE_ADMIN
    elif _matches(presented, _operator_token()):
        role = ROLE_OPERATOR
    else:
        raise publish_flow.FlowError("unauthorized", "a valid Bearer token is required", status=401)

    # `X-Operator` names the human; without it the role is the only name there
    # is, and an audit line reading "operator" beats a blank one.
    return _Caller(role, request.headers.get("x-operator", "").strip() or role)


def _require_admin(caller: _Caller, action: str) -> None:
    """A publish or a rollback restarts the deployment; that is the admin's."""
    if caller.is_admin:
        return
    raise publish_flow.FlowError(
        "forbidden",
        f"only an admin may {action}",
        status=403,
        details=[{"role": caller.role, "required": ROLE_ADMIN}],
    )


def _roles() -> list[str]:
    """The roles this deployment can hand out; empty when nobody may write."""
    roles = [ROLE_ADMIN] if _admin_token() else []
    if _operator_token():
        roles.append(ROLE_OPERATOR)
    return roles


def _refuse_protected(caller: _Caller, patch: dict[str, Any]) -> None:
    """A.3's `403 forbidden`: an operator may change `basic` and `advanced`.

    Checked against the request, not the merged draft: an operator patching a
    basic field onto a draft an admin already put an `ops` value in has changed
    nothing they are not allowed to change. The whole patch is refused rather
    than the offending keys dropped, for the same reason a refused key fails a
    render — half a patch shipped is worse than none.
    """
    if caller.is_admin:
        return
    known = publish_flow.entries()
    blocked = [
        {"field": key, "exposure": known[key].exposure}
        for key in patch
        if key in known and known[key].exposure not in OPERATOR_EXPOSURE
    ]
    if not blocked:
        return
    raise publish_flow.FlowError(
        "forbidden",
        "only an admin may change these parameters",
        status=403,
        details=blocked,
    )


def _if_match(request: Request) -> int | None:
    """`If-Match: <version>`, or None when the caller did not claim one.

    Absent is allowed on purpose: a single-operator console has nothing to
    compare against on its first save. Present-but-stale is always a 409.
    """
    raw = request.headers.get("if-match", "").strip().strip('"')
    if not raw or raw == "*":
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise publish_flow.FlowError(
            "invalid_parameter", f"If-Match must be an integer version, got {raw!r}", status=400
        ) from exc


def _profile(profile: str) -> str:
    if not _PROFILE_RE.match(profile):
        raise publish_flow.FlowError(
            "invalid_parameter", f"invalid profile name {profile!r}", status=400
        )
    return profile


def _is_secret(key: str) -> bool:
    return bool(_SECRET_NAME.search(key.rsplit(".", 1)[-1]))


def _mask(values: dict[str, Any]) -> dict[str, Any]:
    """`{key: "***"}` for names that look like credentials, values otherwise."""
    return {key: drafts.MASK if _is_secret(key) and value not in (None, "") else value
            for key, value in values.items()}


def _load_catalog() -> catalog.Catalog:
    loaded = catalog.load()
    if not loaded.available:
        raise publish_flow.FlowError("catalog_unavailable", loaded.hint, status=503)
    return loaded


# ── A.1 catalog ──────────────────────────────────────────────────────────────


@router.get("/catalog")
def get_catalog(
    request: Request,
    exposure: str | None = None,
    stage: str | None = None,
    backend: str | None = None,
) -> dict[str, Any]:
    """The parameter tree.

    `exposure=basic,advanced` is A.1's form. The ladder is cumulative, so the
    highest level named is the level shown: asking for basic and advanced and
    getting expert as well would defeat the point of the ladder.
    """
    _guard(request, write=False)
    loaded = _load_catalog()
    levels = [part.strip() for part in (exposure or "").split(",") if part.strip()]
    try:
        entries = loaded.filtered(exposure=levels[-1] if levels else None, stage=stage)
    except catalog.CatalogError as exc:
        raise publish_flow.FlowError("invalid_parameter", str(exc), status=400) from exc
    if backend:
        entries = [entry for entry in entries if entry.backend in (None, backend)]

    counts: dict[str, int] = {}
    for entry in loaded.entries:
        counts[entry.exposure] = counts.get(entry.exposure, 0) + 1

    return {
        "schema": loaded.schema,
        "generated_from": loaded.generated_from,
        "generated_at": loaded.generated_at,
        "total": len(loaded.entries),
        "returned": len(entries),
        "exposure_levels": list(catalog.EXPOSURE_LEVELS),
        "exposure_counts": counts,
        # `<stage>.<name>` that several backends define differently. The console
        # needs these to label a row with the backend the profile really serves.
        "variant_keys": loaded.variant_keys,
        "parameters": [entry.as_json() for entry in entries],
    }


# ── A.2 / A.3 draft ──────────────────────────────────────────────────────────


@router.get("/profiles/{profile}/draft")
def get_draft(profile: str, request: Request) -> dict[str, Any]:
    _guard(request, write=False)
    current = drafts.read_draft(_profile(profile))
    return {
        "profile": profile,
        "base_version": current["base_version"],
        "draft": _mask(current["values"]),
        "masked": sorted(key for key in current["values"] if _is_secret(key)),
        "updated_at": current["updated_at"],
        "updated_by": current["updated_by"],
    }


@router.post("/profiles/{profile}/draft")
def post_draft(
    profile: str,
    request: Request,
    body: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Apply a patch to the draft. `null` unsets a key; `***` leaves it alone."""
    caller = _guard(request, write=True)
    name = _profile(profile)
    patch = body.get("patch")
    if not isinstance(patch, dict) or not patch:
        raise publish_flow.FlowError(
            "invalid_parameter", "body must be {\"patch\": {...}, \"base_version\": n}", status=400
        )
    _refuse_protected(caller, patch)
    base_version = body.get("base_version", _if_match(request))
    result = drafts.save_draft(name, patch, base_version=base_version, actor=caller.actor)
    result["draft"] = _mask(result["draft"])
    return result


@router.delete("/profiles/{profile}/draft")
def delete_draft(profile: str, request: Request) -> dict[str, Any]:
    """Not in appendix A, but a draft with no way to abandon it is a trap."""
    caller = _guard(request, write=True)
    return drafts.discard_draft(_profile(profile), actor=caller.actor)


# ── A.4 / A.5 publish and rollback ───────────────────────────────────────────


@router.post("/profiles/{profile}/publish")
async def post_publish(profile: str, request: Request) -> dict[str, Any]:
    """Steps 2 to 8 of §4.1. Returns `live`, or raises with the version rolled back.

    Async on purpose *only* to get the flow off the event loop: the body is
    blocking, and `run_in_threadpool` is the one safe way to say so.
    """
    caller = _guard(request, write=True)
    _require_admin(caller, "publish")
    name = _profile(profile)
    body = await _json_body(request)
    return await run_in_threadpool(
        publish_flow.publish,
        name,
        base_version=body.get("base_version", _if_match(request)),
        note=str(body.get("note", ""))[:500],
        actor=caller.actor,
    )


@router.post("/profiles/{profile}/rollback")
async def post_rollback(profile: str, request: Request) -> dict[str, Any]:
    caller = _guard(request, write=True)
    _require_admin(caller, "roll back")
    name = _profile(profile)
    body = await _json_body(request)
    target = body.get("target_version")
    if not isinstance(target, int) or isinstance(target, bool):
        raise publish_flow.FlowError(
            "invalid_parameter", "body must be {\"target_version\": <int>}", status=400
        )
    return await run_in_threadpool(
        publish_flow.rollback,
        name,
        target_version=target,
        note=str(body.get("note", ""))[:500],
        actor=caller.actor,
    )


async def _json_body(request: Request) -> dict[str, Any]:
    """An empty body is a valid publish when `If-Match` carries the version."""
    raw = await request.body()
    if not raw.strip():
        return {}
    try:
        body = json.loads(raw)
    except ValueError as exc:
        raise publish_flow.FlowError(
            "invalid_parameter", f"body is not JSON: {exc}", status=400
        ) from exc
    if not isinstance(body, dict):
        raise publish_flow.FlowError("invalid_parameter", "body must be a JSON object", status=400)
    return body


# ── A.6 hot update ──────────────────────────────────────────────────────────


@router.post("/sessions/update")
async def post_sessions_update(request: Request, profile: str = "prod") -> dict[str, Any]:
    """Chain B: change the sessions that are open, without a restart.

    Admin-only for the same reason a publish is: it changes what a caller on the
    far end of a live line hears, and unlike a draft there is no copy to review
    it in first. `scope=all` is the default because that is what an operator
    means by "apply".
    """
    caller = _guard(request, write=True)
    _require_admin(caller, "change a running session")
    name = _profile(profile)
    body = await _json_body(request)
    session = body.get("session")
    if not isinstance(session, dict) or not session:
        raise publish_flow.FlowError(
            "invalid_parameter", "body must be {\"scope\": ..., \"session\": {...}}", status=400
        )
    return await run_in_threadpool(
        hot_update.push,
        name,
        scope=str(body.get("scope") or "all"),
        target=body.get("target"),
        session=session,
        actor=caller.actor,
    )


# ── versions and audit (the console's history view) ──────────────────────────


@router.get("/profiles/{profile}/versions")
def get_versions(profile: str, request: Request, limit: int = 50) -> dict[str, Any]:
    """Version history without the renderings.

    `rendered` is the whole YAML file. Sending it for fifty versions would be
    megabytes the history list never shows, so it is reported by size and kept
    for the rollback that needs the exact bytes.
    """
    _guard(request, write=False)
    name = _profile(profile)
    versions = []
    for version in store.list_versions(name, limit=max(1, min(limit, 200))):
        rendered = version.pop("rendered", "") or ""
        versions.append({**version, "rendered_bytes": len(rendered.encode("utf-8"))})
    latest = store.latest_live(name)
    return {
        "profile": name,
        "live_version": int(latest["version"]) if latest else 0,
        "versions": versions,
    }


@router.get("/profiles/{profile}/audit")
def get_audit(profile: str, request: Request, limit: int = 50) -> dict[str, Any]:
    _guard(request, write=False)
    return {
        "profile": _profile(profile),
        "entries": store.list_audit(profile, limit=max(1, min(limit, 200))),
    }


# ── A.7 instance view ────────────────────────────────────────────────────────


@router.get("/instances")
def get_instances(request: Request, profile: str = "prod") -> dict[str, Any]:
    """What is actually running, as opposed to what the console believes.

    A degraded read is still a 200: a container that will not start and a pool
    that will not answer are the two facts an operator most needs to see, and
    turning them into an error status hides them behind a generic failure.
    """
    _guard(request, write=False)
    name = _profile(profile)
    pool = compose_runner.read_pool()
    alerts: list[str] = []
    if not pool.reachable:
        alerts.append(f"pool unreachable: {pool.error}")
    if pool.stuck:
        alerts.append(f"{pool.stuck} unit(s) stuck")
    container = compose_runner.container_status()
    if container.get("status") not in ("running", None):
        alerts.append(f"container is {container.get('status')}")

    latest = store.latest_live(name)
    return {
        "profile": name,
        "version": int(latest["version"]) if latest else None,
        "container": container,
        "pool": {
            "reachable": pool.reachable,
            "size": pool.size,
            "in_use": pool.in_use,
            "units": list(pool.units),
        },
        "alerts": alerts,
    }


# ── service status ───────────────────────────────────────────────────────────


@router.get("/status")
def get_status() -> dict[str, Any]:
    """What the console needs before it renders anything at all."""
    directory = compose_runner.config_dir()
    profiles = sorted(path.stem for path in directory.glob("*.yaml")) if directory.is_dir() else []
    loaded = catalog.load()
    usable, reason = compose_runner.available()
    return {
        "writes_enabled": bool(_admin_token()),
        "roles": _roles(),
        "catalog": {
            "available": loaded.available,
            "hint": loaded.hint,
            "path": loaded.path,
            "total": len(loaded.entries),
            "variant_keys": loaded.variant_keys,
        },
        "config_dir": str(directory),
        "profiles": profiles,
        "compose": {
            "available": usable,
            "detail": reason,
            "file": str(compose_runner.compose_file()),
            "service": compose_runner.compose_service() or None,
            "pool_url": compose_runner.pool_url(),
        },
        "store": str(store.resolve_db_path()),
    }
