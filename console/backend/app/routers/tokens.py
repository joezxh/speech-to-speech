"""Token 观测端点 T1–T5（spec 2026-11-17 §4.3；console:token:query）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import CurrentUser
from app.core.permissions import require_permission
from app.deps import DbSession
from app.schemas.common import ok
from app.services import token_analytics_service

router = APIRouter(prefix="/api/v1/tokens", tags=["tokens"])


@router.get("/summary")
def summary(
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:token:query")),
    cluster: str | None = None,
    window: str = "5m",
):
    return ok(token_analytics_service.summary(db, cluster, window))


@router.get("/trend")
def trend(
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:token:query")),
    cluster: str | None = None,
    window: str = "1h",
    buckets: int = 30,
):
    return ok({"points": token_analytics_service.trend(db, cluster, window, buckets)})


@router.get("/distribution")
def distribution(
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:token:query")),
    cluster: str | None = None,
    window: str = "1h",
):
    return ok({"machines": token_analytics_service.distribution(db, cluster, window)})


@router.get("/egress")
def egress(
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:token:query")),
    cluster: str | None = None,
    window: str = "1h",
):
    return ok({"rows": token_analytics_service.egress(db, cluster, window)})


@router.get("/policy")
def policy(
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:token:query")),
):
    return ok(token_analytics_service.policy(db))
