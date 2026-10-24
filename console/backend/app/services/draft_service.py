"""The draft: the only mutable state in the platform (A.2–A.4).

A draft is a patch, not a document. It holds the keys an operator touched and
the live version it was started against, so once someone publishes, every other
draft is stale and its next save is refused with a 409 instead of quietly
diffing against a config that no longer exists.
"""

from __future__ import annotations

import time
from typing import Any

from app.core.errors import ApiError
from app.core.exposure import MASK, is_secret, mask
from app.repositories.audit_repository import AuditRepository
from app.repositories.draft_repository import DraftRepository
from app.repositories.version_repository import VersionRepository
from app.schemas.common import iso_utc
from app.services import publish_flow_service


def _iso(value) -> str | None:
    return iso_utc(value)


def read_draft(db, profile: str) -> dict[str, Any]:
    """The stored draft, or an empty one carrying the current live version."""
    publish_flow_service.require_profile(profile)
    row = DraftRepository(db).get(profile)
    if row is None:
        return {
            "profile": profile,
            "baseVersion": publish_flow_service.live_version(profile, VersionRepository(db)),
            "draft": {},
            "masked": [],
            "updatedAt": None,
            "updatedBy": "",
        }
    return {
        "profile": profile,
        "baseVersion": row.base_version,
        "draft": mask(row.patch),
        "masked": sorted(key for key in row.patch if is_secret(key)),
        "updatedAt": _iso(row.updated_at),
        "updatedBy": row.updated_by,
    }


def save_draft(
    db,
    profile: str,
    patch: dict[str, Any],
    *,
    base_version: int | None,
    actor: str,
    role: str,
    request_id: str = "",
) -> dict[str, Any]:
    """Merge `patch` onto the stored draft, validate, then persist.

    Validation runs before the write on purpose: the draft is what publish
    reads, so an unpublishable draft is only a way to lose work later. `null`
    is a value here — "drop this key and fall back to the default" — and has to
    survive the merge.
    """
    publish_flow_service.require_profile(profile)
    versions = VersionRepository(db)
    live = publish_flow_service.live_version(profile, versions)
    if base_version is not None and base_version != live:
        raise ApiError(
            "version_conflict",
            f"the live version moved to {live}",
            409,
            detail=[{"expected": live, "got": base_version}],
        )

    stored = DraftRepository(db).get(profile)
    existing = dict(stored.patch) if stored is not None else {}
    skipped = [key for key, value in patch.items() if value == MASK]
    merged = {**existing, **{key: value for key, value in patch.items() if value != MASK}}
    # `null` means "back to the catalog default" (A.3). A draft is a patch, so a
    # stored `key: null` would be a key that reads as default yet still counts as
    # "in draft": the page keeps its badge on, sees no dirty field, and the row
    # can never be cleared again.
    merged = {key: value for key, value in merged.items() if value is not None}

    started = time.monotonic()
    rendered = publish_flow_service.render(profile, merged)

    DraftRepository(db).put(profile, base_version=live, patch=merged, actor=actor)
    audit = AuditRepository(db).record(
        actor=actor,
        role=role,
        action="draft.patch",
        profile=profile,
        fields=sorted(patch),
        version=live,
        duration_s=round(time.monotonic() - started, 3),
        request_id=request_id,
    )
    return {
        "draft": mask(merged),
        "baseVersion": live,
        "skippedMasked": skipped,
        "validation": {
            "ok": True,
            # Structural mode means the runtime package was absent, so the UI
            # can say "checked for shape only" rather than implying more.
            "mode": "runtime" if rendered.resolved else "structural",
            "resolvedPipelines": rendered.resolved.get("pipelines", []),
            "expectedPoolSize": rendered.expected_size,
            "warnings": rendered.warnings,
        },
        "auditId": str(audit.id),
    }


def discard_draft(db, profile: str, *, actor: str, role: str, request_id: str = "") -> dict[str, Any]:
    """Discarding produces no version: `live` is untouched (A.4)."""
    publish_flow_service.require_profile(profile)
    live = publish_flow_service.live_version(profile, VersionRepository(db))
    if not DraftRepository(db).drop(profile):
        raise ApiError("no_draft", f"profile {profile!r} has no draft to discard", 404)
    audit = AuditRepository(db).record(
        actor=actor,
        role=role,
        action="draft.discard",
        profile=profile,
        fields=[],
        version=live,
        request_id=request_id,
    )
    return {
        "discarded": True,
        "revertedTo": "catalog-defaults" if live == 0 else f"v{live}",
        "auditId": str(audit.id),
    }
