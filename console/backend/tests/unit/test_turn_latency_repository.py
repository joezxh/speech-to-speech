"""A.17's index: upsert keyed by (response_key, turn_revision), nearest-rank p95.

Two properties the panel depends on:
* a re-emitted turn overwrites its own row (a turn can be logged as `cancelled`
  and then really finish), so "the latest word about that turn" is the row;
* `null` never becomes 0 on the way in — an unmeasured `hold` must stay
  unmeasured, because 0 ms would read as "no wait at all".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from app.repositories import turn_latency_repository as repo

BASE = datetime(2026, 10, 24, 10, 0, tzinfo=UTC)


def _row(**overrides):
    row = {
        "response_key": "k1",
        "turn_revision": 0,
        "turn_id": "t1",
        "source": "realtime",
        "status": "cancelled",
        "smart_status": "hold",
        "e2e_ms": 6260,
        "stt_ms": 120,
        "llm_ms": 800,
        "tts_ttfa_ms": 300,
        "vad_decision_ms": 40,
        "hold_ms": None,
        "logged_at": BASE,
        "raw_offset": 0,
    }
    row.update(overrides)
    return row


def test_upsert_keeps_one_row_and_the_later_value(db_session):
    repo.upsert_many(db_session, [_row(status="cancelled")])
    repo.upsert_many(db_session, [_row(status="completed", e2e_ms=5000)])
    rows = repo.fetch(db_session, start=BASE - timedelta(minutes=1), end=BASE + timedelta(minutes=1))
    assert len(rows) == 1
    assert rows[0].status == "completed"
    assert rows[0].e2e_ms == 5000


def test_seconds_become_milliseconds_and_none_stays_none():
    assert repo.to_ms(6.26) == 6260
    assert repo.to_ms(None) is None
    assert repo.to_ms(0) == 0


@pytest.mark.parametrize("dialect", [sqlite.dialect(), postgresql.dialect()])
def test_the_upsert_compiles_for_both_dialect_inserts(dialect):
    # `alembic/sql/init-postgresql.sql` ships, so the statement cannot be built
    # from SQLite's insert and hoped to work: it has to compile on both.
    sql = str(repo.build_upsert(dialect.name, [_row()]).compile(dialect=dialect))
    assert "ON CONFLICT (response_key, turn_revision) DO UPDATE" in sql


def test_p95_is_nearest_rank_not_interpolated():
    values = [100 * (index + 1) for index in range(20)]  # 100 … 2000
    assert repo.percentile(values, 0.95) == 1900
    assert repo.percentile([], 0.95) is None


def test_prune_keeps_rows_after_the_cutoff(db_session):
    repo.upsert_many(
        db_session,
        [
            _row(response_key="old", logged_at=BASE - timedelta(hours=48)),
            _row(response_key="new", logged_at=BASE),
        ],
    )
    removed = repo.prune(db_session, before=BASE - timedelta(hours=24))
    assert removed == 1
    rows = repo.fetch(db_session, start=BASE - timedelta(days=7), end=BASE + timedelta(minutes=1))
    assert [row.response_key for row in rows] == ["new"]
