from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Always aware UTC: the API emits ISO 8601 with a Z suffix (A.0)."""
    return datetime.now(UTC)
