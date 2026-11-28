"""Task 13（2026-11-17 原型对齐计划）——token 增量落库与窗口聚合（单通道=agent）。

单通道：instance_probe 对 /v1/usage 的既有轮询不落库（内存兜底），落库真值
唯一来源是 agent 心跳的 tokens{}。console 端只信差分增量并防御负值
（计数器归零时 agent 差分 delta=cur；若 agent 未做差分，钳到 0，库里无负行）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.models.token_metric import ParamTokenMetric
from app.repositories.token_metric_repository import TokenDelta, append_delta, window_sum
from app.services import agent_registry_service as svc
from app.services.machine_service import MachineCreate
from app.schemas.agent import AgentRegisterIn, HeartbeatIn


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


def test_append_delta_and_window_sum(db_session):
    base = datetime(2026, 11, 17, 10, 0, 0, tzinfo=UTC)
    append_delta(
        db_session, "node-a01", TokenDelta(input_tokens=100, output_tokens=40, responses=2, audio_duration_s=8.0, window_s=30),
        observed_at=base,
    )
    append_delta(
        db_session, "node-a01", TokenDelta(input_tokens=150, output_tokens=60, responses=3, audio_duration_s=12.0, window_s=30),
        observed_at=base + timedelta(seconds=30),
    )

    total = window_sum(db_session, "node-a01", base - timedelta(minutes=1), base + timedelta(minutes=1))
    assert (total.input_tokens, total.output_tokens, total.responses) == (250, 100, 5)
    assert total.audio_duration_s == 20.0
    assert total.window_s == 60  # 窗口秒数累加（时间覆盖口径）


def test_negative_delta_is_clamped_not_stored(db_session):
    base = datetime(2026, 11, 17, 10, 0, 0, tzinfo=UTC)
    # 计数器归零且 agent 没做差分 → 上报了负增量：钳到 0，库里无负行。
    append_delta(db_session, "node-a01", TokenDelta(input_tokens=-5, output_tokens=10, responses=1, window_s=30), observed_at=base)
    rows = db_session.scalars(select(ParamTokenMetric)).all()
    assert rows[0].input_tokens == 0
    assert rows[0].output_tokens == 10


def test_three_windows_sum_matches_cumulative_difference(db_session):
    base = datetime(2026, 11, 17, 10, 0, 0, tzinfo=UTC)
    cumulative = [100, 260, 610]  # /v1/usage 的累计值轨迹（输入）
    for index, value in enumerate(cumulative):
        delta = value - (cumulative[index - 1] if index else 0)
        append_delta(
            db_session, "node-a01",
            TokenDelta(input_tokens=delta, output_tokens=0, responses=0, window_s=30),
            observed_at=base + timedelta(seconds=30 * index),
        )
    total = window_sum(db_session, "node-a01", base - timedelta(seconds=1), base + timedelta(hours=1))
    # 计数器从 0 起：三窗增量之和 == 最终累计值（每窗 delta = cur - prev，首窗 delta = cur）。
    assert total.input_tokens == cumulative[-1] == 610


def test_window_sum_filters_by_machine_and_range(db_session):
    base = datetime(2026, 11, 17, 10, 0, 0, tzinfo=UTC)
    append_delta(db_session, "node-a01", TokenDelta(input_tokens=10, responses=1, window_s=30), observed_at=base)
    append_delta(db_session, "node-b02", TokenDelta(input_tokens=999, responses=9, window_s=30), observed_at=base)
    append_delta(
        db_session, "node-a01", TokenDelta(input_tokens=20, responses=2, window_s=30),
        observed_at=base + timedelta(hours=2),
    )

    only_a = window_sum(db_session, "node-a01", base - timedelta(seconds=1), base + timedelta(hours=1))
    assert only_a.input_tokens == 10
    all_machines = window_sum(db_session, None, base + timedelta(hours=1, seconds=1), base + timedelta(hours=3))
    assert all_machines.input_tokens == 20, "machine_id=None 聚合全部机器"


def test_heartbeat_tokens_ingest(db_session):
    _, code = MachineCreate, None
    from app.services import machine_service

    _, code = machine_service.create_machine(db_session, MachineCreate(machineId="node-a01"), actor="alice")
    svc.register(db_session, AgentRegisterIn(register_code=code, machine={"machine_id": "node-a01"}))
    svc.heartbeat(
        db_session,
        "node-a01",
        HeartbeatIn(
            protocol_version=1,
            machine={"machine_id": "node-a01"},
            tokens={"input_tokens": 42, "output_tokens": 17, "responses": 1, "audio_duration_s": 3.5, "window_s": 15},
        ),
    )
    rows = db_session.scalars(select(ParamTokenMetric).where(ParamTokenMetric.machine_id == "node-a01")).all()
    assert len(rows) == 1
    assert rows[0].input_tokens == 42
    assert rows[0].reported_by == "agent"


def _register_machine(db_session, machine_id="node-a01"):
    from app.services import machine_service

    _, code = machine_service.create_machine(db_session, MachineCreate(machineId=machine_id), actor="alice")
    svc.register(db_session, AgentRegisterIn(register_code=code, machine={"machine_id": machine_id}))


def test_heartbeat_backends_ingest(db_session):
    """心跳 tokens.backends{} 落 param_backend_metric：kind/计数/时延/engine/model 全部落位。"""
    from app.models.backend_metric import ParamBackendMetric

    _register_machine(db_session)
    svc.heartbeat(
        db_session,
        "node-a01",
        HeartbeatIn(
            protocol_version=1,
            machine={"machine_id": "node-a01"},
            tokens={
                "input_tokens": 10,
                "output_tokens": 5,
                "responses": 1,
                "window_s": 15,
                "backends": {
                    "stt": {"calls": 2, "errors": 0, "ms_sum": 480, "engine": "qwen3-asr", "model": "Qwen3-ASR-1.7B-hf"},
                    "llm": {"calls": 1, "errors": 1, "ms_sum": 900, "engine": "chat-completions", "model": "qwen-plus"},
                    "tts": {"calls": 1, "errors": 0, "ms_sum": 350, "engine": "", "model": ""},
                },
            },
        ),
    )
    rows = db_session.scalars(select(ParamBackendMetric).where(ParamBackendMetric.machine_id == "node-a01")).all()
    assert len(rows) == 3
    by_kind = {row.kind: row for row in rows}
    assert by_kind["stt"].calls == 2 and by_kind["stt"].errors == 0 and by_kind["stt"].latency_ms_sum == 480
    assert by_kind["stt"].engine == "qwen3-asr" and by_kind["stt"].model == "Qwen3-ASR-1.7B-hf"
    assert by_kind["llm"].errors == 1
    assert by_kind["tts"].engine == "" and by_kind["tts"].model == ""
    assert all(row.window_s == 15 and row.reported_by == "agent" for row in rows)


def test_backend_negative_delta_is_clamped_not_stored(db_session):
    """agent 未差分上报负增量：负值钳到 0，库里无负行（同批正值照常落库）。"""
    from app.models.backend_metric import ParamBackendMetric
    from app.repositories.backend_metric_repository import append_backend_deltas

    base = datetime(2026, 11, 17, 10, 0, 0, tzinfo=UTC)
    append_backend_deltas(
        db_session,
        "node-a01",
        {"stt": {"calls": -3, "errors": 2, "ms_sum": -100}},
        observed_at=base,
    )
    rows = db_session.scalars(select(ParamBackendMetric)).all()
    assert len(rows) == 1 and rows[0].kind == "stt"
    assert rows[0].calls == 0 and rows[0].errors == 2 and rows[0].latency_ms_sum == 0


def test_all_zero_backend_entries_are_skipped(db_session):
    """全零段不落库：心跳 15s 一次，零行会刷表。"""
    from app.models.backend_metric import ParamBackendMetric
    from app.repositories.backend_metric_repository import append_backend_deltas

    base = datetime(2026, 11, 17, 10, 0, 0, tzinfo=UTC)
    append_backend_deltas(
        db_session,
        "node-a01",
        {"stt": {"calls": 0, "errors": 0, "ms_sum": 0}, "llm": {"calls": 0, "errors": 0, "ms_sum": 0}},
        observed_at=base,
    )
    assert db_session.scalars(select(ParamBackendMetric)).all() == []


def test_heartbeat_without_backends_writes_no_backend_rows(db_session):
    """旧版 agent（无 backends 键）心跳照常受理，不产生 backend 行。"""
    from app.models.backend_metric import ParamBackendMetric

    _register_machine(db_session)
    svc.heartbeat(
        db_session,
        "node-a01",
        HeartbeatIn(
            protocol_version=1,
            machine={"machine_id": "node-a01"},
            tokens={"input_tokens": 1, "output_tokens": 1, "responses": 1, "window_s": 15},
        ),
    )
    assert db_session.scalars(select(ParamBackendMetric)).all() == []
