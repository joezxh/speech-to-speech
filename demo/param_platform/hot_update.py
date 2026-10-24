"""Chain B — spec §5: change the conversation that is running, without a restart.

Only four of §2.2's fields take effect on a live session; everything else is a
publish (chain A). This module decides whether a request is one of the four,
hands it to the pipeline service, and shapes the answer.

The validation itself is deliberately not here. `SessionHandler.handle_session_update`
already merges partial updates, rejects `transcription` sessions and checks a
language against the backends that are actually loaded; a second copy of those
rules would drift from the first within a release. This module refuses only what
§2.2 says cannot go hot at all, so the operator gets a 400 naming the field
instead of a per-connection error nobody reads.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from param_platform import compose_runner, publish_flow, renderer, store

# Everything a `session.update` may carry that survives the next sentence the
# caller speaks. `model` and `voice` are the two an operator reaches for first
# and neither moves without a restart (§2.2), so they are refused by name.
HOT_PATHS = frozenset(
    {
        "instructions",
        "audio.input.turn_detection",
        "audio.input.transcription.language",
        "extensions",
    }
)

# Retried by the caller, not here: a fanout is idempotent (it overwrites session
# fields), so a retry after a timeout is harmless but a retry loop inside a
# request that is already holding a connection open is not.
TIMEOUT_S = 10.0


def refused_paths(payload: dict[str, Any], prefix: str = "") -> list[str]:
    """Every leaf the payload sets that §2.2 does not let go hot.

    A dict that merely *contains* an allowed path (`audio`, `audio.input`) is
    walked into; a leaf that is not one of the four is reported by its full
    path, so the console can point at the offending field rather than at the
    whole panel.
    """
    refused: list[str] = []
    for key, value in payload.items():
        path = f"{prefix}{key}"
        if path in HOT_PATHS:
            continue
        if any(allowed.startswith(f"{path}.") for allowed in HOT_PATHS) and isinstance(value, dict):
            refused.extend(refused_paths(value, f"{path}."))
            continue
        refused.append(path)
    return refused


def _service_token(profile: str) -> str:
    """The token this deployment already gives the pipeline service (§5.2).

    Read from the platform's own environment first, then from the profile's
    `.env` — the file the publish flow writes and `env_file:` hands to the
    container. One place for the secret means nobody has to copy it between the
    two sides and get it wrong.
    """
    configured = os.environ.get("S2S_ADMIN_TOKEN", "").strip()
    if configured:
        return configured
    try:
        text = publish_flow.env_path(profile).read_text(encoding="utf-8")
    except OSError:
        return ""
    return renderer.parse_env(text).get("S2S_ADMIN_TOKEN", "").strip()


def _endpoint() -> str:
    """The pipeline service's own admin route, on the port `/v1/pool` answers on."""
    return f"{compose_runner.pool_url().rstrip('/')}/admin/sessions/update"


def _error_payload(response: httpx.Response) -> dict[str, Any]:
    """A refused call's body, in the shape A.0 promises, whatever came back."""
    try:
        body = response.json()
    except ValueError:
        return {"code": "hot_update_failed", "message": f"HTTP {response.status_code}", "details": []}
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return {"code": "hot_update_failed", "message": f"HTTP {response.status_code}", "details": []}
    return {
        "code": str(error.get("code") or "hot_update_failed"),
        "message": str(error.get("message") or ""),
        "details": list(error.get("details") or []),
    }


def push(
    profile: str,
    *,
    scope: str,
    target: Any,
    session: dict[str, Any],
    actor: str,
) -> dict[str, Any]:
    """Fan a session change out to the connections that exist right now.

    Partial failure is a 200 with a non-empty `failed`: a fanout overwrites
    session fields, so the connections that did accept the change keep it. There
    is nothing to roll back and rolling back would undo the successes.
    """
    started = time.monotonic()
    refused = refused_paths(session)
    if refused:
        raise publish_flow.FlowError(
            "unsupported_field",
            "these fields cannot be changed on a running session; publish instead",
            status=400,
            details=[{"field": path} for path in sorted(refused)],
        )

    token = _service_token(profile)
    if not token:
        # Fail closed, like the service side: an unset token must not become an
        # unauthenticated admin route.
        raise publish_flow.FlowError(
            "hot_update_disabled",
            "S2S_ADMIN_TOKEN is not configured for this deployment, so chain B is unavailable",
            status=503,
        )

    url = _endpoint()
    try:
        response = httpx.post(
            url,
            json={"scope": scope, "target": target, "session": session},
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT_S,
        )
    except httpx.HTTPError as exc:
        raise publish_flow.FlowError(
            "pool_unreachable", f"hot update could not reach {url}: {exc}", status=502
        ) from exc

    if response.status_code in (404, 405):
        # A.6: the route only exists once §5.1 shipped in the image that is running.
        raise publish_flow.FlowError(
            "not_implemented",
            "this pipeline service has no /admin/sessions/update; use chain A (publish)",
            status=501,
        )
    if response.status_code == 401:
        raise publish_flow.FlowError(
            "hot_update_unauthorized",
            "the pipeline service rejected this platform's S2S_ADMIN_TOKEN",
            status=502,
        )
    if response.status_code >= 400:
        payload = _error_payload(response)
        code = "hot_update_disabled" if response.status_code == 503 else payload["code"]
        raise publish_flow.FlowError(
            code, payload["message"], status=response.status_code, details=payload["details"]
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise publish_flow.FlowError(
            "hot_update_failed", "the pipeline service answered with something that is not JSON", status=502
        ) from exc

    updated = [str(item) for item in body.get("updated") or []]
    failed = [dict(item) for item in body.get("failed") or []]
    if not updated and len(failed) == 1 and failed[0].get("error") == "invalid_session_type":
        # A.6 lists this as a 422 rather than a per-connection failure. With a
        # single target there is nothing partial about it, and the console that
        # probed one session deserves the status the appendix promises.
        raise publish_flow.FlowError(
            "invalid_session_type",
            "the targeted session is a transcription session, which cannot be updated",
            status=422,
            details=failed,
        )

    audit_id = store.record_audit(
        "sessions.update",
        profile=profile,
        actor=actor,
        result="ok" if not failed else "partial",
        # Field names only. The payload is a prompt, and a prompt is not
        # something to keep a copy of in an audit table.
        detail={
            "scope": scope,
            "target": target,
            "fields": sorted(session),
            "updated": updated,
            "failed": failed,
        },
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return {
        "updated": updated,
        "failed": failed,
        "scope": scope,
        "audit_id": audit_id,
    }
