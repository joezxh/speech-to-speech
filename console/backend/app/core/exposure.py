"""The two rules every read and write of a parameter obeys (§10.1)."""

from __future__ import annotations

import re
from typing import Any

from app.core.errors import ApiError

# The mask A.0 promises for secret fields. A console that posts its whole form
# back would send this string as the value, so it is read as "unchanged" rather
# than written: saving it literally is how a masked field becomes the literal
# password `***` on the next publish.
MASK = "***"

# The catalog has no `secret` flag, so the name is the only signal there is.
SECRET_NAME = re.compile(r"(api_key|_key|token|secret|password)$", re.IGNORECASE)

# Profile names become file names, so they must not leave the config directory.
PROFILE_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")

# `operator` may draft `basic` and `advanced`; everything else needs `admin`.
OPERATOR_EXPOSURE = frozenset({"basic", "advanced"})


def is_secret(key: str) -> bool:
    return bool(SECRET_NAME.search(key.rsplit(".", 1)[-1]))


def mask(values: dict[str, Any]) -> dict[str, Any]:
    """`{key: "***"}` for names that look like credentials, values otherwise."""
    return {key: MASK if is_secret(key) and value not in (None, "") else value for key, value in values.items()}


def validate_profile_name(profile: str) -> str:
    if not PROFILE_NAME.match(profile):
        raise ApiError("invalid_parameter", f"invalid profile name {profile!r}", 400)
    return profile


def refuse_protected(role: str, patch: dict[str, Any], known: dict[str, Any]) -> None:
    """A.3's `403 forbidden`.

    Checked against the request, not the merged draft: an operator patching a
    basic field onto a draft an admin already put an `ops` value in has changed
    nothing they are not allowed to change. The whole patch is refused rather
    than the offending keys dropped — half a patch shipped is worse than none.
    """
    if role == "admin":
        return
    blocked = [
        {"field": key, "exposure": known[key].exposure}
        for key in patch
        if key in known and known[key].exposure not in OPERATOR_EXPOSURE
    ]
    if blocked:
        raise ApiError("forbidden", "only an admin may change these parameters", 403, detail=blocked)


def if_match(raw: str) -> int | None:
    """`If-Match: <version>`, or None when the caller did not claim one.

    Absent is allowed on purpose: a single-operator console has nothing to
    compare against on its first save. Present-but-stale is always a 409.
    """
    value = (raw or "").strip().strip('"')
    if not value or value == "*":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ApiError("invalid_parameter", f"If-Match must be an integer version, got {value!r}", 400) from exc
