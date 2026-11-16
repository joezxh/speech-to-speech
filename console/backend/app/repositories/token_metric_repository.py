"""Token 增量落库（Task 13，单通道=agent；spec 2026-11-17 §5.2）。

instance_probe 对 /v1/usage 的既有轮询不落库（保持内存兜底）；落库真值唯一
来源是 agent 心跳的 tokens{}——本仓储是它唯一的写入方。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.token_metric import ParamTokenMetric


@dataclass
class TokenDelta:
    input_tokens: int = 0
    output_tokens: int = 0
    responses: int = 0
    audio_duration_s: float | None = None
    window_s: int = 0


@dataclass
class TokenSum:
    input_tokens: int
    output_tokens: int
    responses: int
    audio_duration_s: float
    window_s: int


def _clamp(value: int) -> int:
    """负增量 = agent 没做差分（计数器归零被原样上报）：钳到 0，库里无负行。"""
    return max(0, value)


def append_delta(
    db: Session,
    machine_id: str,
    delta: TokenDelta,
    *,
    workload_id: int | None = None,
    observed_at: datetime | None = None,
    reported_by: str = "agent",
) -> None:
    db.add(
        ParamTokenMetric(
            machine_id=machine_id,
            workload_id=workload_id,
            observed_at=observed_at or utcnow(),
            input_tokens=_clamp(delta.input_tokens),
            output_tokens=_clamp(delta.output_tokens),
            responses=_clamp(delta.responses),
            audio_duration_s=delta.audio_duration_s if delta.audio_duration_s is not None and delta.audio_duration_s >= 0 else None,
            window_s=max(0, delta.window_s),
            reported_by=reported_by,
        )
    )
    db.commit()


def window_sum(db: Session, machine_id: str | None, since: datetime, until: datetime) -> TokenSum:
    """时间窗 [since, until) 内的增量聚合；machine_id=None 聚合全部机器。"""
    conditions = [ParamTokenMetric.observed_at >= since, ParamTokenMetric.observed_at < until]
    if machine_id is not None:
        conditions.append(ParamTokenMetric.machine_id == machine_id)
    row = db.execute(
        select(
            func.coalesce(func.sum(ParamTokenMetric.input_tokens), 0),
            func.coalesce(func.sum(ParamTokenMetric.output_tokens), 0),
            func.coalesce(func.sum(ParamTokenMetric.responses), 0),
            func.coalesce(func.sum(ParamTokenMetric.audio_duration_s), 0.0),
            func.coalesce(func.sum(ParamTokenMetric.window_s), 0),
        ).where(*conditions)
    ).one()
    return TokenSum(
        input_tokens=int(row[0]),
        output_tokens=int(row[1]),
        responses=int(row[2]),
        audio_duration_s=float(row[3]),
        window_s=int(row[4]),
    )
