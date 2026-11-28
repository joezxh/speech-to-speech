"""Token 观测端点 T1–T5（spec 2026-11-17 §4.3；console:token:query）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import CurrentUser
from app.core.permissions import require_permission
from app.deps import DbSession
from app.schemas.common import ok
from app.repositories import backend_metric_repository
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


@router.get("/backends")
def backends(
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:token:query")),
    window: str = "1h",
    buckets: int = 30,
):
    """Per-backend 调用统计四维聚合（kind/model/machine/trend）。

    数据源：agent 心跳 tokens.backends → param_backend_metric。无数据时
    by_* 为空数组、trend 全零桶，不编造。
    """
    return ok(
        {
            "by_kind": backend_metric_repository.by_kind(db, window),
            "by_model": backend_metric_repository.by_model(db, window),
            "by_machine": backend_metric_repository.by_machine(db, window),
            "trend": backend_metric_repository.trend(db, window, buckets),
        }
    )
