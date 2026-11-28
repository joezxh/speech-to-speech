"""Per-backend 调用统计四维聚合 + 流量延迟统计（P95 TTFT/错误率）。

公式只在后端算；无数据一律 None/空，绝不编 0（与 token_analytics 同约定）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.models.param_instance_metric import ParamInstanceMetric
from app.models.turn_latency import TurnLatencyRow
from app.repositories.backend_metric_repository import (
    append_backend_deltas,
    by_kind,
    by_machine,
    by_model,
    trend,
)
from app.services import traffic_latency_service

NOW = datetime(2026, 11, 17, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    session = factory()
    try:
        yield session
    finally:
        session.close()


def _seed_backends(db_session):
    base = NOW - timedelta(minutes=5)
    append_backend_deltas(
        db_session, "node-a01",
        {
            "stt": {"calls": 4, "errors": 1, "ms_sum": 800, "engine": "qwen3-asr", "model": "Qwen3-ASR-1.7B-hf"},
            "llm": {"calls": 2, "errors": 0, "ms_sum": 600, "engine": "chat-completions", "model": "qwen-plus"},
        },
        window_s=300, observed_at=base,
    )
    append_backend_deltas(
        db_session, "node-b02",
        {"stt": {"calls": 6, "errors": 0, "ms_sum": 1200}},
        window_s=300, observed_at=base + timedelta(minutes=1),
    )


def test_by_kind_aggregates_calls_errors_and_avg_ms(db_session):
    _seed_backends(db_session)
    rows = {row["kind"]: row for row in by_kind(db_session, "1h", now=NOW)}
    assert rows["stt"] == {"kind": "stt", "calls": 10, "errors": 1, "avg_ms": 200.0}
    assert rows["llm"] == {"kind": "llm", "calls": 2, "errors": 0, "avg_ms": 300.0}


def test_by_model_splits_engine_and_model(db_session):
    _seed_backends(db_session)
    rows = by_model(db_session, "1h", now=NOW)
    stt_named = [row for row in rows if row["kind"] == "stt" and row["model"]]
    assert len(stt_named) == 1
    assert stt_named[0]["engine"] == "qwen3-asr" and stt_named[0]["calls"] == 4
    # node-b02 的 stt 无 engine/model → 空串组
    stt_anon = [row for row in rows if row["kind"] == "stt" and not row["model"]]
    assert stt_anon[0]["calls"] == 6


def test_by_machine_share_pct_normalized(db_session):
    _seed_backends(db_session)
    rows = by_machine(db_session, "1h", now=NOW)
    by_id = {row["machine_id"]: row for row in rows}
    assert by_id["node-b02"]["calls"] == 6 and by_id["node-a01"]["calls"] == 6
    assert sum(row["share_pct"] for row in rows) == pytest.approx(100, abs=0.5)


def test_trend_buckets_sum_to_window_calls(db_session):
    _seed_backends(db_session)
    points = trend(db_session, "1h", buckets=30, now=NOW)
    assert len(points) == 30
    assert sum(p["calls"] for p in points) == 12


def test_empty_window_yields_empty_rows(db_session):
    assert by_kind(db_session, "1h", now=NOW) == []
    assert by_model(db_session, "1h", now=NOW) == []
    assert by_machine(db_session, "1h", now=NOW) == []
    assert all(p["calls"] == 0 for p in trend(db_session, "1h", buckets=3, now=NOW))


def _seed_latency(db_session):
    base = NOW - timedelta(minutes=5)

    def _row(response_key, machine_id, instance_id, ttfa, e2e, audio, status="completed"):
        db_session.add(
            TurnLatencyRow(
                response_key=response_key, turn_revision=0, machine_id=machine_id,
                instance_id=instance_id, tts_ttfa_ms=ttfa, e2e_ms=e2e,
                audio_duration_s=audio, status=status, logged_at=base,
            )
        )

    _row("r1", "node-a01", "pipe-a", 500, 2000, 2.0)
    _row("r2", "node-a01", "pipe-a", 900, 3000, 3.0)
    _row("r3", "node-a01", "pipe-a", 700, 1000, 1.0)
    _row("r4", "node-a01", None, None, None, None, status="cancelled")
    _row("r5", "node-b02", "pipe-b", 300, 1500, 1.5)
    # 窗口外的旧行不应计入
    db_session.add(
        TurnLatencyRow(
            response_key="old", turn_revision=0, machine_id="node-a01", instance_id="pipe-a",
            tts_ttfa_ms=90000, e2e_ms=90000, audio_duration_s=90.0,
            logged_at=NOW - timedelta(hours=2),
        )
    )
    db_session.commit()


def test_percentile_p95():
    values = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
    assert traffic_latency_service.percentile(values, 0.95) == 955


def test_latency_stats_p95_and_by_machine(db_session):
    _seed_latency(db_session)
    stats = traffic_latency_service.latency_stats(db_session, "1h", now=NOW)
    # 窗口内 ttfa 排序 [300,500,700,900]，线性插值 P95 = 700 + 0.85*(900-700) = 870
    assert stats["p95_ttft_ms"] == 870
    by_machine = {row["machine_id"]: row for row in stats["by_machine_ttft"]}
    assert by_machine["node-a01"]["turns"] == 4
    # [500,700,900] → 700 + 0.9*200 = 880
    assert by_machine["node-a01"]["p95_ttft_ms"] == 880
    # RTF = audio_duration_s*1000/e2e_ms：2/2+3/3+1/1 → 均值 1.0
    assert by_machine["node-a01"]["rtf"] == pytest.approx(1.0)


def test_latency_stats_error_rate_and_top_instance(db_session):
    _seed_latency(db_session)
    base = NOW - timedelta(minutes=5)
    db_session.add(
        ParamInstanceMetric(
            instance_id="pipe-a", observed_at=base, observed_by="console",
            kind="sample", status="ok", alloc_ok=8,
            alloc_fail_no_instance=1, alloc_fail_instance_503=1,
        )
    )
    db_session.add(
        ParamInstanceMetric(
            instance_id="pipe-b", observed_at=base, observed_by="console",
            kind="sample", status="ok", alloc_ok=10, alloc_fail_no_instance=0, alloc_fail_instance_503=0,
        )
    )
    db_session.commit()

    stats = traffic_latency_service.latency_stats(db_session, "1h", now=NOW)
    assert stats["err_rate"] == pytest.approx(0.1)  # 2 fails / 20 total
    assert stats["top_err_instance"] == {
        "instance_id": "pipe-a", "errors": 2, "err_rate": 0.2,
    }
    by_instance = {row["instance_id"]: row for row in stats["instances"]}
    assert by_instance["pipe-a"]["err_rate"] == 0.2
    assert by_instance["pipe-a"]["ttft_ms"] is not None
    assert by_instance["pipe-b"]["ttft_ms"] == 300


def test_latency_stats_empty_window_all_none(db_session):
    stats = traffic_latency_service.latency_stats(db_session, "1h", now=NOW)
    assert stats["p95_ttft_ms"] is None
    assert stats["by_machine_ttft"] == []
    assert stats["err_rate"] is None
    assert stats["top_err_instance"] is None
    assert stats["instances"] == []
