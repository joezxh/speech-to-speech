"""Per-backend 调用增量落库与四维聚合（kind/model/machine/trend）。

写入方唯一：agent 心跳的 tokens.backends{}（与 param_token_metric 同一单通道
约定）；instance_probe 等其他来源不落库。计数是窗口增量，防御负值钳 0；
全零段跳过不落库（心跳 15s 一次，零行会刷表）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.backend_metric import ParamBackendMetric

BACKEND_KINDS = ("stt", "llm", "tts")
BACKEND_METRICS = ("calls", "errors", "ms_sum")

_WINDOWS = {"5m": timedelta(minutes=5), "1h": timedelta(hours=1), "24h": timedelta(hours=24)}


def _clamp(value: int) -> int:
    """负增量 = agent 没做差分：钳到 0，库里无负行（与 token_metric 同口径）。"""
    return max(0, value)


def append_backend_deltas(
    db: Session,
    machine_id: str,
    backends: dict,
    *,
    window_s: int = 0,
    workload_id: int | None = None,
    observed_at: datetime | None = None,
    reported_by: str = "agent",
) -> int:
    """把心跳里的 backends{} 段落库；返回写入行数（全零段跳过）。

    backends 形如 {"stt": {"calls": int, "errors": int, "ms_sum": int,
    "engine": str?, "model": str?}, ...}；window_s 取心跳顶层 tokens.window_s
    （per-kind 条目可覆盖）；未知 kind 原样接受（前向兼容）。
    """

    rows = 0
    for kind, payload in (backends or {}).items():
        if not isinstance(payload, dict):
            continue
        calls = _clamp(int(payload.get("calls") or 0))
        errors = _clamp(int(payload.get("errors") or 0))
        ms_sum = _clamp(int(payload.get("ms_sum") or 0))
        if calls == 0 and errors == 0 and ms_sum == 0:
            continue
        db.add(
            ParamBackendMetric(
                machine_id=machine_id,
                kind=str(kind)[:16],
                engine=str(payload.get("engine") or "")[:64],
                model=str(payload.get("model") or "")[:128],
                observed_at=observed_at or utcnow(),
                calls=calls,
                errors=errors,
                latency_ms_sum=ms_sum,
                window_s=max(
                    0,
                    int(payload["window_s"]) if payload.get("window_s") is not None else max(0, window_s),
                ),
                reported_by=reported_by,
            )
        )
        rows += 1
    db.commit()
    return rows


def _range(window: str, now: datetime) -> tuple[datetime, datetime]:
    delta = _WINDOWS.get(window, _WINDOWS["1h"])
    return now - delta, now


def _window_filter(machine_id: str | None, since: datetime, until: datetime):
    conditions = [ParamBackendMetric.observed_at >= since, ParamBackendMetric.observed_at < until]
    if machine_id is not None:
        conditions.append(ParamBackendMetric.machine_id == machine_id)
    return conditions


def by_kind(db: Session, window: str, *, machine_id: str | None = None, now: datetime | None = None) -> list[dict]:
    """维度一：按 kind 汇总 calls/errors/avg_ms。"""
    now = now or datetime.now(UTC)
    since, until = _range(window, now)
    rows = db.execute(
        select(
            ParamBackendMetric.kind,
            func.sum(ParamBackendMetric.calls),
            func.sum(ParamBackendMetric.errors),
            func.sum(ParamBackendMetric.latency_ms_sum),
        ).where(*_window_filter(machine_id, since, until)).group_by(ParamBackendMetric.kind)
    ).all()
    return [
        {
            "kind": kind,
            "calls": int(calls or 0),
            "errors": int(errors or 0),
            "avg_ms": round(ms_sum / calls, 1) if calls else None,
        }
        for kind, calls, errors, ms_sum in rows
    ]


def by_model(db: Session, window: str, *, machine_id: str | None = None, now: datetime | None = None) -> list[dict]:
    """维度二：按 kind+engine+model 细分的调用计数明细。"""
    now = now or datetime.now(UTC)
    since, until = _range(window, now)
    rows = db.execute(
        select(
            ParamBackendMetric.kind,
            ParamBackendMetric.engine,
            ParamBackendMetric.model,
            func.sum(ParamBackendMetric.calls),
            func.sum(ParamBackendMetric.errors),
            func.sum(ParamBackendMetric.latency_ms_sum),
        ).where(*_window_filter(machine_id, since, until))
        .group_by(ParamBackendMetric.kind, ParamBackendMetric.engine, ParamBackendMetric.model)
        .order_by(ParamBackendMetric.kind, func.sum(ParamBackendMetric.calls).desc())
    ).all()
    return [
        {
            "kind": kind,
            "engine": engine,
            "model": model,
            "calls": int(calls or 0),
            "errors": int(errors or 0),
            "avg_ms": round(ms_sum / calls, 1) if calls else None,
        }
        for kind, engine, model, calls, errors, ms_sum in rows
    ]


def by_machine(db: Session, window: str, *, now: datetime | None = None) -> list[dict]:
    """维度三：按机器的调用分布（calls + share_pct，按调用量降序）。"""
    now = now or datetime.now(UTC)
    since, until = _range(window, now)
    rows = db.execute(
        select(
            ParamBackendMetric.machine_id,
            func.sum(ParamBackendMetric.calls),
        ).where(*_window_filter(None, since, until)).group_by(ParamBackendMetric.machine_id)
    ).all()
    result = [{"machine_id": machine_id, "calls": int(calls or 0)} for machine_id, calls in rows if calls]
    grand = sum(row["calls"] for row in result) or 1
    for row in result:
        row["share_pct"] = round(row["calls"] / grand * 100, 1)
    return sorted(result, key=lambda r: -r["calls"])


def trend(db: Session, window: str, buckets: int = 30, *, now: datetime | None = None) -> list[dict]:
    """维度四：调用次数时间桶（与 token_analytics_service.trend 同分桶写法）。"""
    now = now or datetime.now(UTC)
    since, until = _range(window, now)
    span = (until - since).total_seconds() / buckets
    points: list[dict] = []
    for index in range(buckets):
        start = since + timedelta(seconds=span * index)
        end = start + timedelta(seconds=span)
        calls = db.scalar(
            select(func.sum(ParamBackendMetric.calls)).where(
                ParamBackendMetric.observed_at >= start, ParamBackendMetric.observed_at < end
            )
        )
        points.append({"at": start.isoformat(), "calls": int(calls or 0)})
    return points
