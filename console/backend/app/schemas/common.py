from __future__ import annotations

from datetime import UTC, datetime
from typing import Generic, TypeVar

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


class PageData(BaseModel, Generic[T]):
    # `list` is a builtin name but it is the contract the SPA consumes (A.0).
    list: list[T]
    total: int
    page: int
    pageSize: int
