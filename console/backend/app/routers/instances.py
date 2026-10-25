from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request

from app.core.errors import ApiError
from app.core.security import CurrentUser, require_operator, require_user
from app.deps import DbSession
from app.repositories.audit_repository import AuditRepository
from app.repositories.instance_metric_repository import InstanceMetricRepository
from app.repositories.instance_repository import InstanceRepository
from app.repositories.version_repository import VersionRepository
from app.schemas.common import ok
from app.schemas.instance import WINDOWS, metric_point
from app.services import instance_monitor, instances_service

router = APIRouter(prefix="/api/v1", tags=["instances"])


@router.get("/instances")
def get_instances(db: DbSession, profile: str = "prod", user: CurrentUser = Depends(require_user)):
    """A.10: a degraded read is still a 200."""
    latest = VersionRepository(db).latest_live(profile)
    return ok(instances_service.collect(profile, int(latest.version) if latest else None, db=db))


def _registry_row(db, instance_id: str):
    row = InstanceRepository(db).get_by_instance_id(instance_id)
    if row is None:
        raise ApiError("not_found", f"instance {instance_id} is not registered", 404)
    return row


def _request_id(request: Request) -> str:
    # 与 routers/profiles.py 同一条路径：RequestIdMiddleware 已经把
    # `x-request-id` 或新生成的 hex 写进 request.state，读头会拿到空串，
    # 审计行就断了关联。
    return getattr(request.state, "request_id", "")


def _audit(db, user, action: str, instance_id: str, fields: list[str], request_id: str = "") -> None:
    AuditRepository(db).record(
        actor=user.username,
        role=user.role,
        action=action,
        profile=instance_id,
        fields=list(fields),
        request_id=request_id,
    )


@router.post("/instances/{instance_id}/drain")
def drain(
    instance_id: str,
    db: DbSession,
    request: Request,
    user: CurrentUser = Depends(require_operator),
):
    _registry_row(db, instance_id)
    # 先写 DB 再同步内存态，两边缺一不可（spec §6.2 draining 落库）。
    InstanceRepository(db).set_drain(instance_id, drain=True, updated_by=user.username)
    instance_monitor.registry.set_drain(instance_id, True)
    instance_monitor.invalidate()
    _audit(db, user, "instance.drain", instance_id, ["drain_requested"], _request_id(request))
    return ok({"instance_id": instance_id, "drain_requested": True})


@router.post("/instances/{instance_id}/undrain")
def undrain(
    instance_id: str,
    db: DbSession,
    request: Request,
    user: CurrentUser = Depends(require_operator),
):
    _registry_row(db, instance_id)
    InstanceRepository(db).set_drain(instance_id, drain=False, updated_by=user.username)
    instance_monitor.registry.set_drain(instance_id, False)
    instance_monitor.invalidate()
    _audit(db, user, "instance.undrain", instance_id, ["drain_requested"], _request_id(request))
    return ok({"instance_id": instance_id, "drain_requested": False})


@router.post("/instances/{instance_id}/probe")
def probe(
    instance_id: str,
    db: DbSession,
    request: Request,
    user: CurrentUser = Depends(require_operator),
):
    _registry_row(db, instance_id)
    instance_monitor.probe_all(db)  # 绕过 2s 缓存：探测本身是实时的（spec §9）
    instance_monitor.invalidate()
    _audit(db, user, "instance.probe", instance_id, [], _request_id(request))
    state = instance_monitor.registry.get(instance_id)
    return ok(
        {
            "instance_id": instance_id,
            "status": state.status if state else "unknown",
            "probe_ms": state.probe_ms if state else None,
        }
    )


@router.get("/instances/{instance_id}")
def detail(
    instance_id: str,
    db: DbSession,
    user: CurrentUser = Depends(require_user),
):
    _registry_row(db, instance_id)
    state = instance_monitor.registry.get(instance_id)
    return ok(
        {
            "instance_id": instance_id,
            "status": state.status if state else "unknown",
            "units": [
                {"index": u.get("index"), "state": u.get("state"), "sessionId": u.get("session_id")}
                for u in (state.pool.units if state and state.pool else ())
            ],
            "probeHistory": list(state.probe_history) if state else [],
            "p50ProbeMs": state.p50_probe_ms if state else None,
            "p95ProbeMs": state.p95_probe_ms if state else None,
            "lastError": state.last_error if state else "",
            "usage": state.usage if state else None,
        }
    )


@router.get("/instances/{instance_id}/metrics")
def metrics(
    instance_id: str,
    db: DbSession,
    window: str = "1h",
    user: CurrentUser = Depends(require_operator),
):
    if window not in WINDOWS:
        raise ApiError("invalid_request", f"window must be one of {sorted(WINDOWS)}", 400)
    _registry_row(db, instance_id)
    since = datetime.now(UTC) - timedelta(seconds=WINDOWS[window])
    rows = InstanceMetricRepository(db).window(instance_id, since=since)
    return ok(
        {
            "instance_id": instance_id,
            "window": window,
            "points": [metric_point(row) for row in rows],
        }
    )
