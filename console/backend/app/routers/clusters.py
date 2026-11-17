from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.errors import ApiError
from app.core.permissions import require_permission
from app.core.security import CurrentUser
from app.deps import DbSession
from app.repositories.audit_repository import AuditRepository
from app.repositories.cluster_repository import ClusterRepository
from app.schemas.cluster import ClusterCreate, ClusterUpdate
from app.schemas.common import iso_utc, ok
from app.services import cluster_service

router = APIRouter(prefix="/api/v1", tags=["clusters"])


def _request_id(request: Request) -> str:
    # 与 routers/instances.py 同一条路径：RequestIdMiddleware 已写入 request.state。
    return getattr(request.state, "request_id", "")


def _audited(db, user, action: str, name: str, fields: list[str], request_id: str, fn):
    """成功记 ok、ApiError 记 error 后原样重抛（spec §4.3：失败也要记录）。
    401 到不了这里——require_permission 在解析操作人之前就拒绝了。"""
    try:
        result = fn()
    except ApiError as exc:
        AuditRepository(db).record(
            actor=user.username, role=user.role, action=action, profile=name,
            fields=list(fields), result="error", error_code=exc.code, request_id=request_id,
        )
        raise
    AuditRepository(db).record(
        actor=user.username, role=user.role, action=action, profile=name,
        fields=list(fields), request_id=request_id,
    )
    return result


def _row_payload(db, cluster) -> dict:
    stats = cluster_service.instance_host_stats(db, cluster.name)
    return {
        "name": cluster.name,
        "registry": cluster.registry,
        "policy": cluster.policy,
        "machines_pending": stats["machines_pending"],
        "note": cluster.note,
        "machines_total": stats["machines_total"],
        "machines_online": stats["machines_online"],
        "instances_total": stats["instances_total"],
        "healthy": stats["machines_online"] > 0,
        "updated_at": iso_utc(cluster.updated_at),
        "updated_by": cluster.updated_by,
    }


@router.get("/clusters")
def list_clusters(db: DbSession, user: CurrentUser = Depends(require_permission("console:cluster:query"))):
    return ok([_row_payload(db, cluster) for cluster in ClusterRepository(db).list_all()])


@router.get("/clusters/events")
def cluster_events(
    db: DbSession,
    limit: int = 4,
    user: CurrentUser = Depends(require_permission("console:cluster:query")),
):
    """最近集群审计事件（spec §5.2-5）：cluster.* ∪ machine.*——机器增删改
    也是集群运营事件，只看 cluster.* 时总览页添加机器后事件区为空（用户反馈）。"""
    limit = max(1, min(int(limit), 20))
    rows = AuditRepository(db).list_any_prefix(["cluster.", "machine."], limit=limit)
    return ok([
        {
            "auditId": str(row.id),
            "at": iso_utc(row.at),
            "actor": row.actor,
            "role": row.role,
            "action": row.action,
            "profile": row.profile,  # 存的是集群名
            "fields": list(row.fields or []),
            "result": row.result,
            "errorCode": row.error_code,
        }
        for row in rows
    ])


@router.get("/clusters/{name}")
def get_one_cluster(name: str, db: DbSession, user: CurrentUser = Depends(require_permission("console:cluster:query"))):
    return ok(_row_payload(db, cluster_service.get_cluster(db, name)))


@router.post("/clusters")
def create_cluster(
    payload: ClusterCreate,
    db: DbSession,
    request: Request,
    user: CurrentUser = Depends(require_permission("console:cluster:create")),
):
    row = _audited(
        db, user, "cluster.create", payload.name, ["name", "registry", "policy", "note"], _request_id(request),
        lambda: cluster_service.create_cluster(
            db, name=payload.name, registry=payload.registry, policy=payload.policy,
            note=payload.note, actor=user.username,
        ),
    )
    return ok(_row_payload(db, row))


@router.put("/clusters/{name}")
def update_cluster(
    name: str,
    payload: ClusterUpdate,
    db: DbSession,
    request: Request,
    user: CurrentUser = Depends(require_permission("console:cluster:update")),
):
    row = _audited(
        db, user, "cluster.update", name, ["registry", "policy", "note"], _request_id(request),
        lambda: cluster_service.update_cluster(
            db, name=name, registry=payload.registry, policy=payload.policy, note=payload.note, actor=user.username
        ),
    )
    return ok(_row_payload(db, row))


@router.delete("/clusters/{name}")
def delete_cluster(
    name: str,
    db: DbSession,
    request: Request,
    user: CurrentUser = Depends(require_permission("console:cluster:delete")),
):
    _audited(
        db, user, "cluster.delete", name, [], _request_id(request),
        lambda: cluster_service.delete_cluster(db, name=name, actor=user.username),
    )
    return ok({"name": name, "deleted": True})


@router.post("/clusters/{name}/switch")
def switch_cluster(
    name: str,
    db: DbSession,
    request: Request,
    user: CurrentUser = Depends(require_permission("console:cluster:switch")),
):
    # 只校验存在 + 审计留痕，无 DB 状态变更；当前集群持久在前端 sessionStorage（spec §5.1）。
    def _check_exists():
        if not cluster_service.exists(db, name):
            raise ApiError("cluster_not_found", f"cluster {name} does not exist", 404)
        return True

    _audited(db, user, "cluster.switch", name, [], _request_id(request), _check_exists)
    return ok({"name": name, "switched": True})