from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 200
    message: str = "success"
    data: T


def ok(data):
    """The only success envelope. /health and /api/config deliberately bypass it."""
    return {"code": 200, "message": "success", "data": data}


def iso_utc(value: datetime | None) -> str | None:
    """ISO 8601 in UTC with a `Z` suffix (A.0), whatever the column handed back.

    SQLite returns a naive datetime for a `DateTime(timezone=True)` column, so
    `isoformat()` alone would drop the offset and the client would have to guess
    a zone — and guess local. Every timestamp the API emits goes through here.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def json_safe(value: Any) -> Any:
    """Replace the two floats JSON cannot carry with `None`.

    YAML happily parses `.inf` / `.nan`, and `vad.max_speech_ms` really does
    default to `inf`. Starlette's `JSONResponse` refuses those values
    (`Out of range float values are not JSON compliant`) and the whole endpoint
    turns into a 500, so anything read from the catalog crosses this boundary.
    The human-readable catalog already documents `inf` as `null`-equivalent,
    which is exactly what the client can render.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    return value


class PageData(BaseModel, Generic[T]):
    # `list` is a builtin name but it is the contract the SPA consumes (A.0).
    list: list[T]
    total: int
    page: int
    pageSize: int
