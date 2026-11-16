from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.repositories.proxy_metric_repository import ProxyMetricRepository


def _row(**kwargs) -> dict:
    row = {
        "instance_id": "pipe-a",
        "service": "asr",
        "observed_at": datetime.now(UTC),
        "observed_by": "console-1",
        "ok": 1,
        "fail_count": 0,
        "fail_reason": "",
        "duration_ms": 120,
    }
    row.update(kwargs)
    return row


def test_rows_round_trip_and_window_filters(db_session):
    now = datetime.now(UTC)
    repo = ProxyMetricRepository(db_session)
    repo.insert_many(
        [
            _row(observed_at=now - timedelta(minutes=5), ok=3),
            _row(
                observed_at=now - timedelta(hours=2),
                ok=0,
                fail_count=1,
                fail_reason="upstream_timeout",
            ),
        ]
    )
    recent = repo.window("pipe-a", since=now - timedelta(hours=1))
    assert [r.service for r in recent] == ["asr"]
    assert recent[0].ok == 3
    assert recent[0].observed_by == "console-1"


def test_the_window_can_filter_by_service(db_session):
    now = datetime.now(UTC)
    repo = ProxyMetricRepository(db_session)
    repo.insert_many([_row(service="asr"), _row(service="tts")])
    rows = repo.window("pipe-a", since=now - timedelta(hours=1), service="tts")
    assert [r.service for r in rows] == ["tts"]


def test_prune_removes_only_the_old_rows(db_session):
    now = datetime.now(UTC)
    repo = ProxyMetricRepository(db_session)
    repo.insert_many(
        [
            _row(observed_at=now - timedelta(days=9)),
            _row(observed_at=now),
        ]
    )
    assert repo.prune_before(now - timedelta(days=7)) == 1
    assert len(repo.window("pipe-a", since=now - timedelta(days=30))) == 1


def test_the_counters_are_windowed_deltas_not_cumulative(db_session):
    from app.services import proxy_counters

    proxy_counters.reset()
    proxy_counters.bump("pipe-a", "asr", ok=True, duration_ms=100)
    proxy_counters.bump("pipe-a", "asr", ok=True, duration_ms=200)
    proxy_counters.bump("pipe-a", "asr", ok=False, fail_reason="upstream_timeout")
    rows = proxy_counters.drain()
    assert len(rows) == 1
    assert rows[0]["ok"] == 2
    assert rows[0]["fail_count"] == 1
    assert rows[0]["fail_reason"] == "upstream_timeout"
    assert rows[0]["duration_ms"] == 100  # 平均
    # 取走即清空：下一次窗口从零开始。
    assert proxy_counters.drain() == []
