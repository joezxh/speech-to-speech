from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Insert

from app.models.turn_latency import TurnLatencyRow

# `alembic/sql/init-postgresql.sql` exists, so the upsert has to compile for
# both. The construct is dialect-bound (compiling SQLite's under PostgreSQL
# raises AttributeError), so the choice is made before the statement is built.
_DIALECT_INSERTS = {"postgresql": postgres_insert, "sqlite": sqlite_insert}


def build_upsert(dialect: str, rows: list[dict[str, Any]]) -> Insert:
    """Insert or overwrite by (response_key, turn_revision), in one statement.

    A turn legitimately logs twice — `cancelled` and then, when a tool call keeps
    it alive, `completed`. Overwriting keeps "one row per turn revision", so the
    panel's count is turns, not log lines.
    """
    insert = _DIALECT_INSERTS.get(dialect, sqlite_insert)
    statement = insert(TurnLatencyRow).values(rows)
    return statement.on_conflict_do_update(
        index_elements=[TurnLatencyRow.response_key, TurnLatencyRow.turn_revision],
        set_={
            column: statement.excluded[column] for column in rows[0] if column not in ("response_key", "turn_revision")
        },
    )


def upsert_many(session: Session, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    session.execute(build_upsert(session.get_bind().dialect.name, rows))
    session.commit()
    return len(rows)


def to_ms(seconds: float | int | None) -> int | None:
    """Seconds in the log line, milliseconds in the table; `None` stays `None`.

    Writing 0 for an unmeasured stage would make "no hold happened" and "we never
    saw a hold" the same number (§3.9.4, third boundary).
    """
    if seconds is None:
        return None
    return int(round(float(seconds) * 1000))


def percentile(values: list[int], p: float) -> int | None:
    """Nearest-rank: never interpolates, so the answer is a measurement."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(1, math.ceil(p * len(ordered))) - 1]


def fetch(
    session: Session,
    *,
    start: datetime,
    end: datetime,
    status: list[str] | None = None,
    limit: int = 100,
) -> list[TurnLatencyRow]:
    statement = select(TurnLatencyRow).where(TurnLatencyRow.logged_at >= start, TurnLatencyRow.logged_at <= end)
    if status:
        statement = statement.where(TurnLatencyRow.status.in_(list(status)))
    statement = statement.order_by(TurnLatencyRow.logged_at.desc()).limit(limit)
    return list(session.scalars(statement).all())


def count_in_window(session: Session, *, start: datetime, end: datetime, status: list[str] | None = None) -> int:
    statement = (
        select(func.count())
        .select_from(TurnLatencyRow)
        .where(TurnLatencyRow.logged_at >= start, TurnLatencyRow.logged_at <= end)
    )
    if status:
        statement = statement.where(TurnLatencyRow.status.in_(list(status)))
    return int(session.scalar(statement) or 0)


def latest_ingested_at(session: Session) -> datetime | None:
    """The high-water mark of the indexer: how far behind the log it is."""
    return session.scalar(select(func.max(TurnLatencyRow.ingested_at)))


def prune(session: Session, *, before: datetime) -> int:
    """Retention for the index only — the log files keep their own rotation."""
    result = session.execute(delete(TurnLatencyRow).where(TurnLatencyRow.logged_at < before))
    session.commit()
    return int(result.rowcount or 0)
