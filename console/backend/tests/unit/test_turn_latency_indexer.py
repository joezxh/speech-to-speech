"""A.17's indexer: only machine lines, byte-offset cursor, bounded per tick.

The four cases are the four ways an index like this silently lies: it ingests
the human line too (counts double), it keeps an offset across a rotation (the
new file looks already read), one bad line aborts the batch, or the 2000-line
cap drops the tail instead of deferring it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.repositories import turn_latency_repository as repo
from app.services import turn_latency_indexer as indexer

NOW = datetime.now(UTC)


def _machine(key: str, *, status: str = "completed", e2e_s: float = 6.26) -> str:
    return (
        "TURN_LATENCY "
        f'{{"response_key":"{key}","turn_revision":0,"status":"{status}","e2e_s":{e2e_s}}}'
    )


def _rows(session):
    return repo.fetch(session, start=NOW - timedelta(hours=1), end=NOW + timedelta(hours=1))


def test_only_machine_lines_are_ingested(tmp_path, db_session):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / indexer.TARGET).write_text(
        "Turn t1 rev=0 latency: stt=0.10s llm=0.80s\n" + _machine("k1") + "\n",
        encoding="utf-8",
    )
    result = indexer.ingest_once(db_session, log_dir=log_dir, data_dir=tmp_path)
    assert result["ingested"] == 1
    rows = _rows(db_session)
    assert [row.response_key for row in rows] == ["k1"]
    assert rows[0].e2e_ms == 6260


def test_a_rotated_file_is_read_from_the_start(tmp_path, db_session):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    target = log_dir / indexer.TARGET
    target.write_text(_machine("k1") + "\n", encoding="utf-8")
    indexer.ingest_once(db_session, log_dir=log_dir, data_dir=tmp_path)

    target.unlink()
    target.write_text(_machine("k2") + "\n", encoding="utf-8")
    result = indexer.ingest_once(db_session, log_dir=log_dir, data_dir=tmp_path)
    assert result["reset"] is True
    assert result["ingested"] == 1
    assert sorted(row.response_key for row in _rows(db_session)) == ["k1", "k2"]


def test_a_broken_line_is_skipped_without_losing_the_batch(tmp_path, db_session):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / indexer.TARGET).write_text(
        "\n".join([_machine("k1"), "TURN_LATENCY {", _machine("k2")]) + "\n",
        encoding="utf-8",
    )
    result = indexer.ingest_once(db_session, log_dir=log_dir, data_dir=tmp_path)
    assert result["skipped"] == 1
    assert result["ingested"] == 2
    assert sorted(row.response_key for row in _rows(db_session)) == ["k1", "k2"]


def test_the_tick_cap_defers_the_tail_to_the_next_tick(tmp_path, db_session):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / indexer.TARGET).write_text(
        "\n".join(_machine(f"k{index}") for index in range(2500)) + "\n", encoding="utf-8"
    )
    first = indexer.ingest_once(db_session, log_dir=log_dir, data_dir=tmp_path)
    assert first["ingested"] == indexer.MAX_LINES_PER_TICK
    assert repo.count_in_window(
        db_session, start=NOW - timedelta(hours=1), end=NOW + timedelta(hours=1)
    ) == indexer.MAX_LINES_PER_TICK

    second = indexer.ingest_once(db_session, log_dir=log_dir, data_dir=tmp_path)
    assert second["ingested"] == 500
    assert second["reset"] is False
