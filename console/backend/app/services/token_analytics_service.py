"""Token 观测分析（T1–T4，spec 2026-11-17 §4.3 token 卡 / §9.2.4）。

成本、每会话等公式只在后端算；单价常量走 env（S2S_TOKEN_PRICE_IN/OUT，$/Mtok）。
无数据时给 null/空，绝不编 0。
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.repositories.instance_metric_repository import InstanceMetricRepository
from app.repositories.token_metric_repository import window_sum

_WINDOWS = {"5m": timedelta(minutes=5), "1h": timedelta(hours=1), "24h": timedelta(hours=24)}


def _range(window: str, now: datetime) -> tuple[datetime, datetime]:
    delta = _WINDOWS.get(window, _WINDOWS["5m"])
    return now - delta, now


def _alloc_ok_total(db: Session, cluster: str | None, since: datetime, until: datetime) -> int:
    """会话数代理：分配窗口的成功次数之和（per_session 公式的分母）。"""
    rows = InstanceMetricRepository(db).alloc_window_by_cluster(cluster, since=since)
    until_naive = until
    return sum(int(r["ok"]) for r in rows)


def summary(db: Session, cluster: str | None, window: str, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    since, until = _range(window, now)
    total = window_sum(db, None, since, until)
    sessions = _alloc_ok_total(db, cluster, since, until)
    per_minute = round(total.input_tokens + total.output_tokens, 0) / max((until - since).total_seconds(), 1) * 60
    quota = _env_float("S2S_TOKEN_QUOTA_DAILY", None)
    water_pct = None if quota in (None, 0) else round((total.input_tokens + total.output_tokens) / quota * 100, 1)
    sessions = sessions or 0
    return {
        "window": window,
        "total": int(total.input_tokens + total.output_tokens),
        "input": int(total.input_tokens),
        "output": int(total.output_tokens),
        "per_minute": round(per_minute, 1),
        "quota": quota,
        "water_pct": water_pct,
        "cost_usd": _cost(total.input_tokens, total.output_tokens),
        "per_session": round((total.input_tokens + total.output_tokens) / sessions, 1) if sessions else None,
        "per_session_turns": round(total.responses / sessions, 2) if sessions else None,
    }


def _env_float(name: str, default: float | None) -> float | None:
    text = os.environ.get(name, "").strip()
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def _cost(input_tokens: int, output_tokens: int) -> float | None:
    price_in = _env_float("S2S_TOKEN_PRICE_IN", None)
    price_out = _env_float("S2S_TOKEN_PRICE_OUT", None)
    if price_in is None and price_out is None:
        return None
    cost = (input_tokens / 1_000_000) * (price_in or 0.0) + (output_tokens / 1_000_000) * (price_out or 0.0)
    return round(cost, 6)


def trend(db: Session, cluster: str | None, window: str, buckets: int = 30, *, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    since, until = _range(window, now)
    span = (until - since).total_seconds() / buckets
    points: list[dict] = []
    for index in range(buckets):
        start = since + timedelta(seconds=span * index)
        end = start + timedelta(seconds=span)
        bucket = window_sum(db, None, start, end)
        points.append(
            {
                "at": start.isoformat(),
                "input": bucket.input_tokens,
                "output": bucket.output_tokens,
                "total": bucket.input_tokens + bucket.output_tokens,
            }
        )
    return points


def distribution(db: Session, cluster: str | None, window: str, *, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    since, until = _range(window, now)
    # 按机器取窗口和：对每台机器分别聚合（machine_id 维度）。
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.machine import ParamMachine  # noqa: PLC0415

    machine_ids = list(db.scalars(select(ParamMachine.machine_id)).all())
    rows: list[dict] = []
    for machine_id in machine_ids:
        bucket = window_sum(db, machine_id, since, until)
        tokens = bucket.input_tokens + bucket.output_tokens
        if tokens:
            rows.append({"machine_id": machine_id, "tokens": tokens, "share_pct": 0.0})
    grand = sum(row["tokens"] for row in rows) or 1
    for row in rows:
        row["share_pct"] = round(row["tokens"] / grand * 100, 1)
    return sorted(rows, key=lambda r: -r["tokens"])


def egress(db: Session, cluster: str | None, window: str, *, now: datetime | None = None) -> list[dict]:
    """负载出口 7 列：kind/engine/hosts/load/tokens/vram/route。

    token 记账与 engine/hosts/vram 分开：后者来自机器负载声明（心跳全量
    覆盖），与窗口内有没有流量无关——有负载声明就出列，tokens 为 0 不隐藏。
    """
    now = now or datetime.now(UTC)
    since, until = _range(window, now)
    totals: dict[str, dict] = {}

    def _bump(kind: str, tokens: int) -> None:
        row = totals.setdefault(kind, {"kind": kind, "route": "lb" if kind == "pipeline" else "direct", "tokens": 0})
        row["tokens"] += tokens

    from sqlalchemy import func, select  # noqa: PLC0415

    from app.models.machine import ParamMachine, ParamMachineWorkload  # noqa: PLC0415
    from app.models.param_instance import ParamInstance  # noqa: PLC0415

    # 负载声明 → per-kind 的 engine/hosts/vram/load（与流量无关的静态面）。
    workloads = db.execute(
        select(
            ParamMachineWorkload.kind,
            ParamMachineWorkload.engine,
            ParamMachineWorkload.machine_id,
            ParamMachineWorkload.vram_gb,
        )
    ).all()
    kind_meta: dict[str, dict] = {}
    for kind, engine, machine_id, vram_gb in workloads:
        meta = kind_meta.setdefault(kind, {"engines": [], "hosts": [], "vram": 0.0})
        if engine and engine not in meta["engines"]:
            meta["engines"].append(engine)
        if machine_id not in meta["hosts"]:
            meta["hosts"].append(machine_id)
        if vram_gb is not None:
            meta["vram"] += float(vram_gb)
    instance_counts = dict(
        db.execute(
            select(ParamInstance.machine_id, func.count(ParamInstance.id))
            .where(ParamInstance.machine_id.isnot(None))
            .group_by(ParamInstance.machine_id)
        ).all()
    )

    machine_ids = list(db.scalars(select(ParamMachine.machine_id)).all())
    for machine_id in machine_ids:
        bucket = window_sum(db, machine_id, since, until)
        tokens = bucket.input_tokens + bucket.output_tokens
        if not tokens:
            continue
        kinds = list(
            db.scalars(
                select(ParamMachineWorkload.kind).where(ParamMachineWorkload.machine_id == machine_id)
            ).all()
        )
        # 一台机器的 token 记在它的每个负载 kind 上会重复计——按优先级取代表 kind：
        # pipeline > llm > 其余首字母序。
        for priority in ("pipeline", "llm", "video", "jepa", "embed"):
            if priority in kinds:
                _bump(priority, tokens)
                break
        else:
            _bump(kinds[0] if kinds else "other", tokens)

    rows = []
    for kind, row in totals.items():
        meta = kind_meta.get(kind, {"engines": [], "hosts": [], "vram": 0.0})
        if kind == "pipeline":
            load = f"{sum(instance_counts.get(host, 0) for host in meta['hosts'])} · instances"
        elif meta["hosts"]:
            load = f"{len(meta['hosts'])} machines"
        else:
            load = "0 machines"
        rows.append(
            {
                **row,
                "engine": " / ".join(meta["engines"]),
                "hosts": meta["hosts"],
                "load": load,
                "vram_gb": round(meta["vram"], 1) if meta["vram"] else None,
            }
        )
    # 有负载声明但窗口内零流量的 kind 也出列（tokens=0，如实呈现）。
    for kind, meta in kind_meta.items():
        if kind not in totals:
            load = (
                f"{sum(instance_counts.get(host, 0) for host in meta['hosts'])} · instances"
                if kind == "pipeline"
                else f"{len(meta['hosts'])} machines"
            )
            rows.append(
                {
                    "kind": kind,
                    "route": "lb" if kind == "pipeline" else "direct",
                    "tokens": 0,
                    "engine": " / ".join(meta["engines"]),
                    "hosts": meta["hosts"],
                    "load": load,
                    "vram_gb": round(meta["vram"], 1) if meta["vram"] else None,
                }
            )
    return sorted(rows, key=lambda r: -r["tokens"])


def policy(db: Session) -> dict:
    """Token 策略四项 + 来源与生效徽标（本期来源都是 env/default，§4.3 策略卡）。"""
    quota = _env_float("S2S_TOKEN_QUOTA_DAILY", None)
    price_in = _env_float("S2S_TOKEN_PRICE_IN", None)
    price_out = _env_float("S2S_TOKEN_PRICE_OUT", None)
    max_context = _env_float("S2S_TOKEN_MAX_CONTEXT", None)
    items = [
        {"key": "quota_daily_tokens", "value": quota, "source": "env" if quota is not None else "default", "effective": quota is not None},
        {"key": "price_in_usd_per_mtok", "value": price_in, "source": "env" if price_in is not None else "default", "effective": price_in is not None},
        {"key": "price_out_usd_per_mtok", "value": price_out, "source": "env" if price_out is not None else "default", "effective": price_out is not None},
        {"key": "max_context", "value": max_context, "source": "env" if max_context is not None else "default", "effective": max_context is not None},
    ]
    return {"items": items}
