"""机器管理面 M1–M9（spec 2026-11-17 §7.2.2；用户 JWT + console:machine:* 权限码）。

M8 三步注册测试与 M9 自动注册走 console:machine:create（建档动作同权）。
审计已在 machine_service 落（machine.create/update/delete），路由层不重复记。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.errors import ApiError
from app.core.permissions import require_permission
from app.core.security import CurrentUser
from app.deps import DbSession
from app.schemas.common import ok
from app.schemas.machine import (
    AutoRegisterIn,
    MachineCreate,
    MachineDeployIn,
    MachineDraftPut,
    MachineUpdate,
    RegisterTestIn,
    WorkloadsPut,
)
from app.services import machine_config_service, machine_service

router = APIRouter(prefix="/api/v1/machines", tags=["machines"])


@router.get("")
def list_machines(
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:machine:query")),
    cluster: str | None = None,
):
    machines = machine_service.list_machines(db, cluster)
    return ok({"machines": [m.model_dump() for m in machines], "total": len(machines)})


@router.get("/{machine_id}")
def get_machine(
    machine_id: str,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:machine:query")),
):
    try:
        return ok(machine_service.get_machine(db, machine_id).model_dump())
    except KeyError:
        raise ApiError("not_found", f"machine {machine_id} does not exist", 404) from None


@router.post("")
def create_machine(
    payload: MachineCreate,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:machine:create")),
):
    """建档并签发一次性注册码；明文仅此一次（M3）。"""
    try:
        machine, register_code = machine_service.create_machine(db, payload, actor=user.username)
    except ValueError:
        raise ApiError("conflict", f"machine {payload.machineId} is already registered", 409) from None
    return ok({"machine": machine.model_dump(), "registerCode": register_code})


@router.put("/{machine_id}")
def update_machine(
    machine_id: str,
    payload: MachineUpdate,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:machine:update")),
):
    try:
        machine = machine_service.update_machine(db, machine_id, payload, actor=user.username)
    except KeyError:
        raise ApiError("not_found", f"machine {machine_id} does not exist", 404) from None
    return ok(machine.model_dump())


@router.delete("/{machine_id}", status_code=204)
def delete_machine(
    machine_id: str,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:machine:delete")),
):
    try:
        machine_service.delete_machine(db, machine_id, actor=user.username)
    except KeyError:
        raise ApiError("not_found", f"machine {machine_id} does not exist", 404) from None


@router.get("/{machine_id}/workloads")
def list_workloads(
    machine_id: str,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:machine:query")),
):
    try:
        detail = machine_service.get_machine(db, machine_id)
    except KeyError:
        raise ApiError("not_found", f"machine {machine_id} does not exist", 404) from None
    return ok({"workloads": [w.model_dump() for w in detail.workloads]})


@router.put("/{machine_id}/workloads")
def replace_workloads(
    machine_id: str,
    payload: WorkloadsPut,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:machine:update")),
):
    """M7：负载清单全量覆盖。"""
    try:
        workloads = machine_service.upsert_workloads(db, machine_id, payload.workloads, actor=user.username)
    except KeyError:
        raise ApiError("not_found", f"machine {machine_id} does not exist", 404) from None
    return ok({"workloads": [w.model_dump() for w in workloads]})


@router.get("/{machine_id}/config")
def config_view(
    machine_id: str,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:machine:query")),
):
    """D1：机器参数视图（expected/actual/drift/source/...，Review Focus #5）。"""
    try:
        return ok({"rows": machine_config_service.config_view(db, machine_id)})
    except KeyError:
        raise ApiError("not_found", f"machine {machine_id} does not exist", 404) from None


@router.get("/{machine_id}/drift")
def drift_view(
    machine_id: str,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:machine:query")),
):
    """D2：漂移摘要（agent 未回报的键未知、不算漂移）。"""
    try:
        return ok(machine_config_service.drift(db, machine_id))
    except KeyError:
        raise ApiError("not_found", f"machine {machine_id} does not exist", 404) from None


@router.get("/{machine_id}/draft")
def get_draft(
    machine_id: str,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:machine:query")),
):
    """D3：机器草稿（values + version，version 供乐观锁）。"""
    return ok(machine_config_service.get_draft(db, machine_id))


@router.put("/{machine_id}/draft")
def put_draft(
    machine_id: str,
    payload: MachineDraftPut,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:machine:update")),
):
    """D4：保存草稿；非法值 400、base_version 过期 409。"""
    try:
        return ok(
            machine_config_service.put_draft(
                db, machine_id, payload.patch, base_version=payload.base_version, actor=user.username
            )
        )
    except KeyError:
        raise ApiError("not_found", f"machine {machine_id} does not exist", 404) from None


@router.delete("/{machine_id}/draft")
def clear_draft(
    machine_id: str,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:machine:update")),
):
    """D5：清除草稿。"""
    machine_config_service.clear_draft(db, machine_id, actor=user.username)
    return ok({"cleared": True})


@router.post("/{machine_id}/deploy")
def deploy_config(
    machine_id: str,
    payload: MachineDeployIn,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:machine:update")),
):
    """D6：push（期望+草稿）/ rollback（最近 ack 成功快照）；非 canary 需确认词。"""
    try:
        return ok(
            machine_config_service.deploy(
                db,
                machine_id,
                payload.rows,
                payload.mode,
                actor=user.username,
                confirm_word=payload.confirm_word,
            )
        )
    except KeyError:
        raise ApiError("not_found", f"machine {machine_id} does not exist", 404) from None


@router.post("/register-test")
def register_test(
    payload: RegisterTestIn,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:machine:create")),
):
    """M8：三步注册测试（simulate=fail 演练"agent 不来"）。"""
    return ok(machine_service.register_test(db, payload, actor=user.username))


@router.post("/auto-register")
def auto_register(
    payload: AutoRegisterIn,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:machine:create")),
):
    """M9：自动注册受理（生成注册码挂待接入，不代 agent 完成注册）。"""
    try:
        return ok(machine_service.auto_register(db, payload, actor=user.username))
    except ValueError:
        raise ApiError("conflict", f"machine {payload.machineId} is already registered", 409) from None
