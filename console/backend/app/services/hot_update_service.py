"""Chain B: push a session patch to live connections, touching no files (A.9).

The console does not re-implement `handle_session_update`: it trims the payload
against A.9's whitelist and forwards it, so language checks and
`invalid_session_type` stay in exactly one place (spec §3.2.3).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from app.config import console
from app.core.errors import ApiError
from app.repositories.audit_repository import AuditRepository

TIMEOUT_S = 10.0
SCOPES = frozenset({"all", "pipeline", "session"})
HINT = (
    "只影响当前活跃连接；空闲 unit 与新连接仍读 init_chat_prompt，"
    "改默认人设需要同时发布配置并重启 pipeline。"
)

# A.9's whitelist as a tree; `None` means “this whole node is allowed”.
# `audio.input.turn_detection` is a leaf on purpose: A.9 whitelists the object,
# and which of its keys actually change behaviour (§2.2) is the pipeline's call.
WHITELIST: dict[str, Any] = {
    "instructions": None,
    "extensions": None,
    "audio": {"input": {"turn_detection": None, "transcription": {"language": None}}},
}


def prune(session: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Keep A.9's four paths and name everything else."""
    clean: dict[str, Any] = {}
    rejected: list[str] = []
    _walk(session, WHITELIST, "", clean, rejected)
    return clean, rejected


def _walk(
    node: Any, tree: dict[str, Any], prefix: str, out: dict[str, Any], rejected: list[str]
) -> None:
    if not isinstance(node, dict):
        rejected.append(prefix or "<root>")
        return
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if key not in tree:
            # Name the leaves, not the branch: “audio.output” tells an operator
            # nothing about which field to remove, and the branch may hold several.
            if isinstance(value, dict):
                rejected.extend(_paths(value, path) or [path])
            else:
                rejected.append(path)
            continue
        branch = tree[key]
        if branch is None:
            out[key] = value
            continue
        if not isinstance(value, dict):
            rejected.append(path)
            continue
        child: dict[str, Any] = {}
        _walk(value, branch, path, child, rejected)
        if child:
            out[key] = child


def _paths(node: dict[str, Any], prefix: str = "") -> list[str]:
    """Dotted leaf names for the audit row: names only, never values (§10.1)."""
    out: list[str] = []
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.extend(_paths(value, path) or [path])
        else:
            out.append(path)
    return out


def update(
    db,
    profile: str,
    *,
    scope: str,
    target: Any,
    session: dict[str, Any],
    actor: str,
    role: str,
    request_id: str = "",
) -> dict[str, Any]:
    """Trim, forward, audit. Partial failure is normal (A.9: idempotent overwrite)."""
    if scope not in SCOPES:
        raise ApiError("invalid_parameter", f"unknown scope {scope!r}", 400)
    if scope == "pipeline" and not isinstance(target, int):
        raise ApiError("invalid_parameter", "scope=pipeline needs an integer target", 400)
    if scope == "session" and not isinstance(target, str):
        raise ApiError("invalid_parameter", "scope=session needs a session id", 400)
    if scope == "all" and target is not None:
        raise ApiError("invalid_parameter", "scope=all takes no target", 400)

    clean, rejected = prune(session)
    if rejected:
        raise ApiError(
            "unsupported_field",
            "these fields cannot be changed on a live session",
            400,
            detail=[{"field": path} for path in rejected],
        )
    if not clean:
        raise ApiError("invalid_parameter", "the session patch is empty", 400)

    fields = sorted(_paths(clean))
    try:
        body = _forward(scope, target, clean)
    except ApiError as exc:
        _audit(db, profile, actor, role, request_id, fields, "failed", exc.code)
        raise

    audit = _audit(db, profile, actor, role, request_id, fields, "ok", None)
    return {
        "updated": [str(item) for item in body.get("updated") or []],
        "failed": [
            {"sessionId": str(item.get("session_id", "")), "error": str(item.get("error", ""))}
            for item in body.get("failed") or []
            if isinstance(item, dict)
        ],
        "auditId": str(audit.id),
        "hint": HINT,
    }


def _forward(scope: str, target: Any, session: dict[str, Any]) -> dict[str, Any]:
    token = os.environ.get("S2S_INTERNAL_TOKEN", "").strip()
    if not token:
        # The console is misconfigured, not the pipeline. A.11 greys the button
        # out for the same reason; this is that fact arriving via the write path.
        raise ApiError(
            "internal_token_missing",
            "S2S_INTERNAL_TOKEN is not configured for the console",
            502,
            detail=[{"env": "S2S_INTERNAL_TOKEN"}],
        )

    url = f"{console.pipeline_base_url.rstrip('/')}/internal/sessions/update"
    try:
        response = httpx.post(
            url,
            json={"scope": scope, "target": target, "session": session},
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT_S,
        )
    except httpx.HTTPError as exc:
        raise ApiError(
            "pipeline_unavailable", f"the pipeline is not reachable: {type(exc).__name__}", 502
        ) from exc

    if response.status_code == 404:
        # A.12: a pipeline build that predates Task 1. Tell the operator to use
        # chain A instead of leaking a bare 404 from loopback.
        raise ApiError(
            "not_implemented",
            "this pipeline has no /internal/sessions/update yet; publish instead",
            501,
        )
    if response.status_code in (401, 503):
        raise ApiError(
            "pipeline_token_missing",
            "the pipeline rejected the internal token; check S2S_INTERNAL_TOKEN in config/prod.env",
            502,
        )

    body = _json(response)
    if response.status_code >= 400:
        # 400 invalid_request_error / 422 invalid_session_type are the pipeline's
        # verdicts about *this* patch: pass the code and status through (§A.12).
        if response.status_code not in (400, 422):
            raise ApiError("pipeline_unavailable", f"pipeline returned {response.status_code}", 502)
        error = body.get("error") if isinstance(body.get("error"), dict) else {}
        raise ApiError(
            str(error.get("code") or "invalid_parameter"),
            str(error.get("message") or "the pipeline rejected this session update"),
            response.status_code,
        )
    return body


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _audit(db, profile, actor, role, request_id, fields, result, error_code):
    return AuditRepository(db).record(
        actor=actor,
        role=role,
        action="session.update",
        profile=profile,
        fields=fields,
        result=result,
        error_code=error_code,
        request_id=request_id,
    )
