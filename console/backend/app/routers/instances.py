from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request

from app.core.errors import ApiError
from app.core.security import CurrentUser, require_admin, require_operator, require_user
from app.deps import DbSession
from app.repositories.allocator_lease_repository import AllocatorLeaseRepository
from app.repositories.audit_repository import AuditRepository
from app.repositories.instance_metric_repository import InstanceMetricRepository
from app.repositories.instance_repository import InstanceRepository
from app.repositories.instance_runtime_repository import InstanceRuntimeRepository
from app.repositories.proxy_metric_repository import ProxyMetricRepository
from app.repositories.version_repository import VersionRepository
from app.schemas.common import ok
from app.schemas.instance import (
    WINDOWS,
    HangupRequest,
    InstanceBinding,
    InstanceCreate,
    metric_point,
    proxy_metric_point,
)
from app.services import instance_monitor, instance_probe, instances_service

router = APIRouter(prefix="/api/v1", tags=["instances"])
hangup_router = APIRouter(prefix="/api/v1", tags=["instances"])


@router.get("/instances")
def get_instances(
    db: DbSession,
    profile: str = "prod",
    cluster: str | None = None,
    user: CurrentUser = Depends(require_user),
):
    """A.10: a degraded read is still a 200. cluster 缺省 = 全部行（现状不变）。"""
    latest = VersionRepository(db).latest_live(profile)
    return ok(instances_service.collect(profile, int(latest.version) if latest else None, db=db, cluster=cluster))


@router.put("/instances/{instance_id}/machine")
def bind_instance_machine(
    instance_id: str,
    payload: InstanceBinding,
    db: DbSession,
    request: Request,
    user: CurrentUser = Depends(require_admin),
):
    """手工绑定/解绑机器（spec 2026-11-17 §7.1）：machine_id 传空 = 解绑。"""
    row = InstanceRepository(db).get_by_instance_id(instance_id)
    if row is None:
        raise ApiError("not_found", f"instance {instance_id} does not exist", 404)
    machine_id = (payload.machine_id or "").strip()
    if machine_id:
        from app.repositories.machine_repository import MachineRepository

        if MachineRepository(db).get(machine_id) is None:
            raise ApiError("not_found", f"machine {machine_id} does not exist", 404)
    row.machine_id = machine_id or None
    row.updated_by = user.username
    row.updated_at = datetime.now(UTC)
    db.commit()
    _audit(db, user, "instance.bind_machine", instance_id, ["machine_id"], _request_id(request))
    return ok({"instance_id": row.instance_id, "machine_id": row.machine_id})


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


@router.post("/instances")
def register_instance(
    payload: InstanceCreate,
    db: DbSession,
    request: Request,
    user: CurrentUser = Depends(require_admin),
):
    """在线纳管一台实例（spec 2026-11-17 §5.4）。

    以前只能改 `instances.yaml` 再重启控制台；现在声明数据直接写库，
    巡检下一轮就会探它，运行时状态落到 `param_instance_runtime`。
    """
    if InstanceRepository(db).get_by_instance_id(payload.instance_id):
        raise ApiError("conflict", f"instance {payload.instance_id} is already registered", 409)
    row = InstanceRepository(db).create(
        instance_id=payload.instance_id,
        base_url=payload.base_url.strip(),
        weight=payload.weight,
        max_sessions_hint=payload.max_sessions_hint,
        labels=payload.labels,
        cluster_id=payload.cluster_id,
        updated_by=user.username,
    )
    _audit(db, user, "instance.register", payload.instance_id, ["base_url", "weight"], _request_id(request))
    instance_monitor.invalidate()
    return ok(
        {
            "instance_id": row.instance_id,
            "base_url": row.base_url,
            "weight": row.weight,
            "cluster_id": row.cluster_id,
            "enabled": row.enabled,
            "drain_requested": row.drain_requested,
        }
    )


@router.delete("/instances/{instance_id}")
def remove_instance(
    instance_id: str,
    db: DbSession,
    request: Request,
    user: CurrentUser = Depends(require_admin),
):
    """摘掉一台实例：占位、运行时状态、声明数据一起清（spec 2026-11-17 §5.4）。

    先清租约再删声明行——否则那个实例的槽位会一直被"占着"。
    """
    _registry_row(db, instance_id)
    AllocatorLeaseRepository(db).delete_by_instance(instance_id)
    InstanceRuntimeRepository(db).delete(instance_id)
    InstanceRepository(db).delete(instance_id)
    _audit(db, user, "instance.remove", instance_id, [], _request_id(request))
    instance_monitor.invalidate()
    return ok({"instance_id": instance_id, "removed": True})


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
    kind: str = "slots",
    user: CurrentUser = Depends(require_operator),
):
    if window not in WINDOWS:
        raise ApiError("invalid_request", f"window must be one of {sorted(WINDOWS)}", 400)
    _registry_row(db, instance_id)
    since = datetime.now(UTC) - timedelta(seconds=WINDOWS[window])
    if kind == "proxy":
        # 数据面代理采样（spec §6.2/§7）：与槽位采样分表，所以单独一条读路径。
        rows = ProxyMetricRepository(db).window(instance_id, since=since)
        return ok(
            {
                "instance_id": instance_id,
                "window": window,
                "kind": "proxy",
                "points": [proxy_metric_point(row) for row in rows],
            }
        )
    if kind != "slots":
        raise ApiError("invalid_request", "kind must be one of ['proxy', 'slots']", 400)
    rows = InstanceMetricRepository(db).window(instance_id, since=since)
    return ok(
        {
            "instance_id": instance_id,
            "window": window,
            "points": [metric_point(row) for row in rows],
        }
    )


@hangup_router.post("/instances/{instance_id}/hangup")
def hangup(
    instance_id: str,
    payload: HangupRequest,
    request: Request,
    db: DbSession,
    user: CurrentUser = Depends(require_admin),
):
    """spec §9.2：跨机代理实例侧的 WebRTC 挂断。默认不注册，开了才有这条路由。

    只对 WebRTC 传输有效；WS 会话没有服务端断开能力（spec §3）。"""
    row = _registry_row(db, instance_id)
    token = os.environ.get("S2S_ADMIN_TOKEN", "").strip()
    if not token:
        # 与 Task 17 的实例侧行为对齐：没配 token 是功能不可用（503），不是没权限。
        raise ApiError("admin_disabled", "S2S_ADMIN_TOKEN is not configured on this console", 503)
    upstream = instance_probe.hangup_call(row.base_url, payload.session_id, token)
    # 审计先于错误映射：一次挂断尝试无论成败都留痕（spec §5.3）。
    _audit(db, user, "instance.hangup", instance_id, ["session_id"], _request_id(request))
    if upstream == 0:
        raise ApiError("upstream_unreachable", f"instance {instance_id} did not answer the hangup", 502)
    if upstream == 401:
        raise ApiError("upstream_unauthorized", "the instance rejected S2S_ADMIN_TOKEN", 502)
    if upstream == 404:
        raise ApiError("upstream_not_found", f"no call {payload.session_id} on {instance_id}", 404)
    if upstream != 200:
        raise ApiError("upstream_error", f"instance {instance_id} answered {upstream}", 502)
    return ok({"instance_id": instance_id, "session_id": payload.session_id, "upstream_status": upstream})
