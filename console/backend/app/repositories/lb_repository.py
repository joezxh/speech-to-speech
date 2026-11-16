"""param_lb_rule / param_lb_route_log 的读写（Task 14 观测 + Task 16 引擎共用）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.lb import ParamLbAffinity, ParamLbRouteLog, ParamLbRule


def rules_ordered(db: Session) -> list[ParamLbRule]:
    return list(db.scalars(select(ParamLbRule).order_by(ParamLbRule.priority)).all())


def append_route_log(
    db: Session,
    *,
    session_key: str,
    rule_id: int | None,
    matched: bool,
    sticky_hit: bool = False,
    is_canary: bool = False,
    instance_id: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    at: datetime | None = None,
) -> None:
    db.add(
        ParamLbRouteLog(
            at=at or utcnow(),
            session_key=session_key,
            rule_id=rule_id,
            matched=matched,
            sticky_hit=sticky_hit,
            is_canary=is_canary,
            instance_id=instance_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    )
    db.commit()


def route_logs_since(db: Session, since: datetime) -> list[ParamLbRouteLog]:
    return list(db.scalars(select(ParamLbRouteLog).where(ParamLbRouteLog.at >= since)).all())


def put_affinity(
    db: Session,
    affinity_key: str,
    *,
    machine_id: str | None,
    instance_id: str | None,
    rule_id: int | None,
    ttl_s: int,
) -> None:
    row = db.get(ParamLbAffinity, affinity_key)
    if row is None:
        row = ParamLbAffinity(affinity_key=affinity_key)
        db.add(row)
    row.machine_id = machine_id
    row.instance_id = instance_id
    row.rule_id = rule_id
    row.created_at = utcnow()
    from datetime import timedelta  # noqa: PLC0415

    row.expires_at = utcnow() + timedelta(seconds=ttl_s)
    db.commit()


def get_affinity(db: Session, affinity_key: str) -> ParamLbAffinity | None:
    return db.get(ParamLbAffinity, affinity_key)
