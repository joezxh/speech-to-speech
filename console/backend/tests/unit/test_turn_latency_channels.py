"""Task 8（2026-11-17 原型对齐计划）——A5 agent 上报与索引器单通道让位。

单通道约定（spec §5.3.5）：同一台机器的 turn_latency 行只有一个写入方——
agent 生效（注册成功）后索引器对该机让位；索引器只在无 agent 部署形态工作。
重建重放（可重建索引的契约）只还原本机行（machine_id 为空），远端行不被覆盖。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.models.machine import ParamMachine
from app.models.turn_latency import TurnLatencyRow
from app.repositories.turn_latency_repository import rebuild_many, upsert_many
from app.services import turn_latency_indexer
from app.services.agent_latency_service import report_rows


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


def _agent_row(response_key: str = "r1", e2e_ms: int = 1500, machine_id: str = "node-a01") -> dict:
    return {
        "response_key": response_key,
        "turn_revision": 0,
        "status": "completed",
        "e2e_ms": e2e_ms,
        "machine_id": machine_id,
        "instance_id": None,
        "raw_offset": 0,
        "logged_at": datetime(2026, 11, 17, 10, 0, 0, tzinfo=UTC),
    }


def _local_row(response_key: str = "r1", e2e_ms: int = 2000) -> dict:
    row = _agent_row(response_key=response_key, e2e_ms=e2e_ms, machine_id=None)
    return row


def test_agent_rows_upsert_without_duplicate_pk(db_session):
    first = report_rows(db_session, "node-a01", [_agent_row(e2e_ms=1500)])
    assert first == {"accepted": True, "count": 1}

    # 同 PK 二次上报：覆盖旧值（如 cancelled → completed），不产生重复行
    second = _agent_row(e2e_ms=1800)
    second["status"] = "completed"
    report_rows(db_session, "node-a01", [second])

    rows = db_session.scalars(select(TurnLatencyRow)).all()
    assert len(rows) == 1
    assert rows[0].e2e_ms == 1800
    assert rows[0].machine_id == "node-a01"
    assert rows[0].instance_id is None
    assert rows[0].raw_offset == 0, "agent 行没有本机日志偏移语义，恒置 0"
    assert rows[0].logged_at.replace(tzinfo=UTC) == datetime(2026, 11, 17, 10, 0, 0, tzinfo=UTC)


def test_report_rows_accepts_iso_logged_at(db_session):
    count = report_rows(
        db_session,
        "node-a01",
        [{"response_key": "r2", "logged_at": "2026-11-17T10:05:00Z", "e2e_ms": 900}],
    )
    assert count["count"] == 1
    row = db_session.scalar(select(TurnLatencyRow).where(TurnLatencyRow.response_key == "r2"))
    assert row.logged_at.replace(tzinfo=UTC) == datetime(2026, 11, 17, 10, 5, 0, tzinfo=UTC)


def test_indexer_yields_when_agent_is_active(db_session, tmp_path):
    log_dir = tmp_path / "logs"
    data_dir = tmp_path / "data"
    log_dir.mkdir()
    data_dir.mkdir()
    (log_dir / "pipeline-stdout.log").write_text(
        "2026-11-17T10:00:00Z INFO TURN_LATENCY {\"response_key\": \"r1\", \"e2e_s\": 2.0}\n",
        encoding="utf-8",
    )
    # 同容器 agent 注册成功（token 已签发）→ 索引器让位
    db_session.add(ParamMachine(machine_id="node-a01", token_hash="hash", last_seen_at=datetime.now(UTC)))
    db_session.commit()

    result = turn_latency_indexer.ingest_once(db_session, log_dir=log_dir, data_dir=data_dir)
    assert result.get("yielded") is True
    assert db_session.scalars(select(TurnLatencyRow)).all() == []


def test_indexer_works_without_agent(db_session, tmp_path):
    log_dir = tmp_path / "logs"
    data_dir = tmp_path / "data"
    log_dir.mkdir()
    data_dir.mkdir()
    (log_dir / "pipeline-stdout.log").write_text(
        "2026-11-17T10:00:00Z INFO TURN_LATENCY {\"response_key\": \"r1\", \"e2e_s\": 2.0}\n",
        encoding="utf-8",
    )

    result = turn_latency_indexer.ingest_once(db_session, log_dir=log_dir, data_dir=data_dir)
    assert result["ingested"] == 1
    row = db_session.scalar(select(TurnLatencyRow))
    assert row.machine_id is None, "无 agent 形态的落行 machine_id 置空（语义=本机）"
    assert row.e2e_ms == 2000


def test_rebuild_replays_local_rows_only(db_session):
    # 远端行（agent 上报）先落库；随后用本机日志重放同 PK 的本机行
    upsert_many(db_session, [_agent_row(e2e_ms=1500, machine_id="node-a01")])
    rebuild_many(db_session, [_local_row(e2e_ms=2000)])

    row = db_session.scalar(select(TurnLatencyRow).where(TurnLatencyRow.response_key == "r1"))
    assert row.e2e_ms == 1500, "重放不得覆盖远端机器的行"
    assert row.machine_id == "node-a01"

    # 本机行（machine_id 空）被重放正常还原/覆盖
    upsert_many(db_session, [])
    rebuild_many(db_session, [_local_row(e2e_ms=2100)])
    db_session.add(
        TurnLatencyRow(
            response_key="local",
            turn_revision=0,
            machine_id=None,
            e2e_ms=1,
            logged_at=datetime(2026, 11, 17, 10, 0, 0, tzinfo=UTC),
        )
    )
    db_session.commit()
    rebuild_many(db_session, [_local_row(response_key="local", e2e_ms=999)])
    local = db_session.scalar(select(TurnLatencyRow).where(TurnLatencyRow.response_key == "local"))
    assert local.e2e_ms == 999, "本机行参与重放还原"
