"""Step 1 of chain A: the draft, which is the only mutable state.

A draft is a patch, not a document. It holds the keys an operator touched and
the live version it was started against; the rendered file is derived from the
file on disk plus this patch every time someone asks. That is why a manual edit
to `config/<profile>.yaml` shows up in the next preview instead of being silently
overwritten by a stale copy.

`base_version` is what makes two operators safe. It is the live version the
draft was opened against, so once someone publishes, every other draft is
stale and its next save or publish is refused with a 409 instead of quietly
diffing against a config that no longer exists.
"""

from __future__ import annotations

import time
from typing import Any

from param_platform import store
from param_platform.publish_flow import FlowError, live_version, profile_path, render

# The mask A.0 promises for secret fields. A console that posts its whole form
# back would send this string as the value, so it is read as "unchanged" rather
# than written into the draft: saving it literally is how a masked field becomes
# the literal password `***` on the next publish.
MASK = "***"


def read_draft(profile: str) -> dict[str, Any]:
    """The stored draft, or an empty one carrying the current live version."""
    if not profile_path(profile).is_file():
        raise FlowError("unknown_profile", f"no profile named {profile!r}", status=404)
    draft = store.get_draft(profile)
    if draft is not None:
        return draft
    return {
        "profile": profile,
        "values": {},
        "base_version": live_version(profile),
        "updated_at": None,
        "updated_by": "",
    }


def save_draft(
    profile: str,
    patch: dict[str, Any],
    *,
    base_version: int | None = None,
    actor: str = "",
) -> dict[str, Any]:
    """Merge `patch` onto the stored draft, then validate the merged result.

    Merging rather than replacing is what makes a per-field save work: the
    console sends one field and the draft keeps the other nine. `null` is a
    value here — it means "drop this key and fall back to the catalog default",
    which is a different intent from "leave it alone" and has to survive.

    The save is refused when the merged draft does not validate (A.3). That
    makes a half-edited draft unsaveable, which is deliberate: the draft is what
    publish reads, so an unpublishable draft is only a way to lose work later.
    """
    started = time.monotonic()
    current = live_version(profile)
    if base_version is not None and base_version != current:
        raise FlowError(
            "version_conflict",
            f"the live version moved to {current}",
            status=409,
            details=[{"expected": current, "got": base_version}],
        )

    existing = store.get_draft(profile) or {"values": {}}
    masked = [key for key, value in patch.items() if value == MASK]
    merged = {**existing.get("values", {}), **{k: v for k, v in patch.items() if v != MASK}}
    rendered = render(profile, merged)

    store.put_draft(profile, merged, current, actor)
    audit_id = store.record_audit(
        "draft.save",
        profile=profile,
        actor=actor,
        result="ok",
        detail={"keys": sorted(patch), "masked_skipped": masked},
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return {
        "draft": merged,
        "base_version": current,
        "skipped_masked": masked,
        "validation": {
            "ok": True,
            # Structural mode means the container had no runtime package, so the
            # console can say "checked for shape only" rather than implying more.
            "mode": "runtime" if rendered.resolved else "structural",
            "resolved_pipelines": rendered.resolved.get("pipelines", []),
            "expected_pool_size": rendered.expected_size,
            "warnings": rendered.warnings,
        },
        "audit_id": audit_id,
    }


def discard_draft(profile: str, *, actor: str = "") -> dict[str, Any]:
    store.drop_draft(profile)
    audit_id = store.record_audit("draft.discard", profile=profile, actor=actor, result="ok")
    return {"profile": profile, "discarded": True, "audit_id": audit_id}
