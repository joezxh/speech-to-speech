"""LB 策略/规则端点 L1–L6（spec 2026-11-17 §4.3；query 只读，rule:write 才能写）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.errors import ApiError
from app.core.permissions import require_permission
from app.core.security import CurrentUser
from app.deps import DbSession
from app.schemas.common import ok
from app.schemas.lb import LbRuleCreate, LbRuleUpdate
from app.repositories.audit_repository import AuditRepository
from app.services import lb_policy_service

router = APIRouter(prefix="/api/v1/lb", tags=["lb"])


@router.get("/policy")
def policy(
    user: CurrentUser = Depends(require_permission("console:lb:query")),
):
    return ok(lb_policy_service.policy_snapshot())


@router.get("/rules")
def list_rules(
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:lb:query")),
):
    return ok({"rules": lb_policy_service.rules(db)})


@router.post("/rules")
def create_rule(
    payload: LbRuleCreate,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:lb:rule:write")),
):
    rule = lb_policy_service.create_rule(db, **payload.model_dump(), actor=user.username)
    AuditRepository(db).record(
        actor=user.username, role=user.role, action="lb.rule.create", profile=rule["name"], fields=["priority"]
    )
    db.commit()
    return ok(rule)


@router.put("/rules/{rule_id}")
def update_rule(
    rule_id: int,
    payload: LbRuleUpdate,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:lb:rule:write")),
):
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    rule = lb_policy_service.update_rule(db, rule_id, user.username, **fields)
    AuditRepository(db).record(
        actor=user.username, role=user.role, action="lb.rule.update", profile=rule["name"], fields=sorted(fields)
    )
    db.commit()
    return ok(rule)


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(
    rule_id: int,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:lb:rule:write")),
):
    lb_policy_service.delete_rule(db, rule_id)


@router.get("/route-stats")
def route_stats(
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:lb:query")),
    window_s: int = 3600,
):
    return ok(lb_policy_service.route_stats(db, window_s))
