"""LB 策略与规则（L1–L6，spec 2026-11-17 §4.3 策略卡/规则表/出口卡）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.repositories import lb_repository
from app.repositories.lb_repository import rules_ordered

# 分流型规则才允许 share/sticky；其余类型存空（模型注释同源）。
SHARED_TYPES = {"canary"}


def _rule_out(rule) -> dict:
    return {
        "id": rule.id,
        "name": rule.name,
        "priority": rule.priority,
        "match_type": rule.match_type,
        "match_value": rule.match_value,
        "target_kind": rule.target_kind,
        "target_value": rule.target_value,
        "share_pct": rule.share_pct,
        "sticky_ttl_s": rule.sticky_ttl_s,
        "enabled": rule.enabled,
        "updated_by": rule.updated_by,
    }


def policy_snapshot() -> dict:
    from app.config import console as console_settings  # noqa: PLC0415

    return {
        "mode": console_settings.lb_mode,
        "items": [
            {"key": "lb_mode", "value": console_settings.lb_mode, "source": "env"},
            {"key": "failover_attempts", "value": 3, "source": "default"},
        ],
    }


def rules(db: Session) -> list[dict]:
    return [_rule_out(rule) for rule in rules_ordered(db)]


def _validate(match_type: str, match_value: str) -> None:
    if match_type != "default" and not match_value:
        raise ApiError("invalid_request", "match_value is required for non-default rules", 400)


def _priority_free(db: Session, priority: int, exclude_id: int | None = None) -> None:
    for rule in rules_ordered(db):
        if rule.priority == priority and rule.id != exclude_id:
            raise ApiError("conflict", f"priority {priority} is already taken by rule {rule.name}", 409)


def create_rule(
    db: Session,
    *,
    name: str,
    priority: int,
    match_type: str,
    match_value: str,
    target_kind: str,
    target_value: str,
    actor: str,
    share_pct: int | None = None,
    sticky_ttl_s: int | None = None,
    enabled: bool = True,
) -> dict:
    _validate(match_type, match_value)
    _priority_free(db, priority)
    from app.models.lb import ParamLbRule  # noqa: PLC0415

    row = ParamLbRule(
        name=name,
        priority=priority,
        match_type=match_type,
        match_value=match_value,
        target_kind=target_kind,
        target_value=target_value,
        share_pct=share_pct if match_type in SHARED_TYPES else None,
        sticky_ttl_s=sticky_ttl_s if match_type in SHARED_TYPES else None,
        enabled=enabled,
        updated_by=actor,
    )
    db.add(row)
    db.commit()
    return _rule_out(row)


def update_rule(db: Session, rule_id: int, actor: str, **fields) -> dict:
    from app.models.lb import ParamLbRule  # noqa: PLC0415

    row = db.get(ParamLbRule, rule_id)
    if row is None:
        raise ApiError("not_found", f"rule {rule_id} does not exist", 404)
    if "priority" in fields and fields["priority"] != row.priority:
        _priority_free(db, fields["priority"], exclude_id=rule_id)
    allowed = {
        "name", "priority", "match_type", "match_value", "target_kind",
        "target_value", "share_pct", "sticky_ttl_s", "enabled",
    }
    for key, value in fields.items():
        if key in allowed and value is not None:
            setattr(row, key, value)
    row.updated_by = actor
    db.commit()
    return _rule_out(row)


def delete_rule(db: Session, rule_id: int) -> None:
    from app.models.lb import ParamLbRule  # noqa: PLC0415

    row = db.get(ParamLbRule, rule_id)
    if row is None:
        raise ApiError("not_found", f"rule {rule_id} does not exist", 404)
    db.delete(row)
    db.commit()


def route_stats(db: Session, window_s: int, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    logs = lb_repository.route_logs_since(db, now - timedelta(seconds=window_s))
    if not logs:
        return {"rules": [], "sticky_hit_rate": None}

    by_rule: dict[int, dict] = {}
    sticky_hits = 0
    for log in logs:
        if log.sticky_hit:
            sticky_hits += 1
        if log.rule_id is None or not log.matched:
            continue
        row = by_rule.setdefault(log.rule_id, {"rule_id": log.rule_id, "matched": 0, "tokens": 0, "share_pct": 0.0})
        row["matched"] += 1
        row["tokens"] += log.input_tokens + log.output_tokens
    grand = sum(row["tokens"] for row in by_rule.values()) or 1
    for row in by_rule.values():
        row["share_pct"] = round(row["tokens"] / grand * 100, 1)
    return {
        "rules": sorted(by_rule.values(), key=lambda r: -r["matched"]),
        "sticky_hit_rate": round(sticky_hits / len(logs), 4),
    }
