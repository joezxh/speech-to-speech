"""机器实体服务（M1–M7，spec 2026-11-17 §7.2.2）。

口径：machine_id 重复 → ValueError（路由层映射 409）；不存在 → KeyError（映射 404）。
注册码 = secrets.token_urlsafe(24)，明文只在 create 返回值里出现一次，库中只存 sha256。
审计沿用 instances.py 的约定：action 点分前缀、fields 只存字段名不存值、失败也记。
"""

from __future__ import annotations

import hashlib
import secrets

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.machine import ParamMachine
from app.models.param_instance import ParamInstance
from app.models.param_instance_runtime import ParamInstanceRuntime
from app.repositories.audit_repository import AuditRepository
from app.repositories.machine_repository import MachineRepository
from app.schemas.common import iso_utc

REGISTER_CODE_BYTES = 24


def hash_secret(raw: str) -> str:
    """注册码 / machine token 的入库形式；比对一律走本函数（Task 4 复用）。"""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class WorkloadIn(BaseModel):
    """负载声明条目（心跳清单与手工编辑共用）。字段名即前端契约（camelCase）。"""

    kind: str = Field(default="pipeline", max_length=16)
    engine: str = ""
    model: str = Field(default="", max_length=128)
    port: int | None = Field(default=None, ge=0, le=65535)
    listenAddr: str = Field(default="", max_length=64)
    publicAddr: str = Field(default="", max_length=64)
    vramGb: float | None = Field(default=None, ge=0)
    healthPath: str = ""
    healthIntervalS: int = Field(default=30, ge=1)
    note: str = ""
    state: str = ""


class WorkloadOut(WorkloadIn):
    workloadId: int | None = None


class MachineCreate(BaseModel):
    machineId: str = Field(min_length=1, max_length=64)
    clusterId: str = Field(default="", max_length=64)
    profile: str | None = Field(default=None, max_length=64)
    addr: str = Field(default="", max_length=255)
    role: str = Field(default="agent", max_length=16)
    gpu: str = Field(default="", max_length=64)
    gpuTotalGb: float | None = Field(default=None, ge=0)
    version: str = ""


class MachineUpdate(BaseModel):
    """部分更新：只取显式传入的字段（exclude_unset）。"""

    clusterId: str | None = Field(default=None, max_length=64)
    profile: str | None = Field(default=None, max_length=64)
    addr: str | None = Field(default=None, max_length=255)
    role: str | None = Field(default=None, max_length=16)
    gpu: str | None = Field(default=None, max_length=64)
    gpuTotalGb: float | None = Field(default=None, ge=0)
    version: str | None = None


class MachineOut(BaseModel):
    machineId: str
    clusterId: str
    profile: str | None = None
    addr: str = ""
    role: str = "agent"
    gpu: str = ""
    gpuTotalGb: float | None = None
    version: str = ""
    state: str = "pending_register"
    registryMode: str = "manual"
    agentVersion: str = ""
    protocolVersion: int = 1
    lastSeen: str | None = None
    workloads: list[WorkloadOut] = Field(default_factory=list)


class MachineDetail(MachineOut):
    """M2 详情：附绑定实例与运行时摘要（实例级状态，机器级 util 待 Task 14 接 token 差分）。"""

    instanceIds: list[str] = Field(default_factory=list)
    runtime: list[dict] = Field(default_factory=list)


# MachineUpdate 的 camelCase 属性名 → param_machine 列名（审计 fields 用列名）。
_UPDATE_COLUMNS = {
    "clusterId": "cluster_id",
    "profile": "profile",
    "addr": "addr",
    "role": "role",
    "gpu": "gpu",
    "gpuTotalGb": "gpu_total_gb",
    "version": "version",
}


def _workload_out(row: ParamMachineWorkload) -> WorkloadOut:
    return WorkloadOut(
        workloadId=row.id,
        kind=row.kind,
        engine=row.engine,
        model=row.model,
        port=row.port,
        listenAddr=row.listen_addr,
        publicAddr=row.public_addr,
        vramGb=row.vram_gb,
        healthPath=row.health_path,
        healthIntervalS=row.health_interval_s,
        note=row.note,
        state=row.state,
    )


def _machine_out(db: Session, row: ParamMachine) -> MachineOut:
    return MachineOut(
        machineId=row.machine_id,
        clusterId=row.cluster_id,
        profile=row.profile,
        addr=row.addr,
        role=row.role,
        gpu=row.gpu,
        gpuTotalGb=row.gpu_total_gb,
        version=row.version,
        state=row.state,
        registryMode=row.registry_mode,
        agentVersion=row.agent_version,
        protocolVersion=row.protocol_version,
        lastSeen=iso_utc(row.last_seen_at) if row.last_seen_at else None,
        workloads=[_workload_out(w) for w in MachineRepository(db).list_workloads(row.machine_id)],
    )


def _audit(db: Session, *, actor: str, action: str, machine_id: str, fields: list[str]) -> None:
    AuditRepository(db).record(
        actor=actor,
        role="",
        action=action,
        profile=machine_id,
        fields=list(fields),
    )


def _get_row(db: Session, machine_id: str) -> ParamMachine:
    row = MachineRepository(db).get(machine_id)
    if row is None:
        raise KeyError(machine_id)
    return row


def list_machines(db: Session, cluster: str | None = None) -> list[MachineOut]:
    return [_machine_out(db, row) for row in MachineRepository(db).list(cluster)]


def get_machine(db: Session, machine_id: str) -> MachineDetail:
    row = _get_row(db, machine_id)
    out = MachineDetail(**_machine_out(db, row).model_dump())
    instance_rows = db.scalars(
        select(ParamInstance).where(ParamInstance.machine_id == machine_id)
    ).all()
    out.instanceIds = [instance.instance_id for instance in instance_rows]
    for instance in instance_rows:
        runtime = db.scalar(
            select(ParamInstanceRuntime).where(ParamInstanceRuntime.instance_id == instance.instance_id)
        )
        if runtime is not None:
            out.runtime.append(
                {
                    "instanceId": runtime.instance_id,
                    "status": runtime.status,
                    "reserved": runtime.reserved,
                    "probeMs": runtime.probe_ms,
                    "observedAt": iso_utc(runtime.observed_at),
                }
            )
    return out


def create_machine(db: Session, p: MachineCreate, actor: str) -> tuple[MachineOut, str]:
    """建档并签发一次性注册码；返回 (机器, 注册码明文)，明文仅此一次。"""
    if MachineRepository(db).get(p.machineId) is not None:
        raise ValueError(f"machine {p.machineId} is already registered")
    register_code = secrets.token_urlsafe(REGISTER_CODE_BYTES)
    row = ParamMachine(
        machine_id=p.machineId,
        cluster_id=p.clusterId,
        profile=p.profile,
        addr=p.addr,
        role=p.role,
        gpu=p.gpu,
        gpu_total_gb=p.gpuTotalGb,
        version=p.version,
        state="pending_register",
        register_code_hash=hash_secret(register_code),
        created_by=actor,
        updated_by=actor,
    )
    MachineRepository(db).create(row=row)
    _audit(
        db,
        actor=actor,
        action="machine.create",
        machine_id=p.machineId,
        fields=["machine_id", "cluster_id", "profile", "addr", "role", "gpu", "gpu_total_gb", "version"],
    )
    return _machine_out(db, row), register_code


def update_machine(db: Session, machine_id: str, p: MachineUpdate, actor: str) -> MachineOut:
    row = _get_row(db, machine_id)
    changed = p.model_dump(exclude_unset=True)
    for attr, value in changed.items():
        setattr(row, _UPDATE_COLUMNS[attr], value)
    row.updated_by = actor
    db.commit()
    db.refresh(row)
    _audit(
        db,
        actor=actor,
        action="machine.update",
        machine_id=machine_id,
        fields=[_UPDATE_COLUMNS[attr] for attr in changed],
    )
    return _machine_out(db, row)


def delete_machine(db: Session, machine_id: str, actor: str) -> None:
    _get_row(db, machine_id)  # 不存在 → KeyError（路由层 404）
    MachineRepository(db).delete(machine_id)
    _audit(db, actor=actor, action="machine.delete", machine_id=machine_id, fields=[])


# WorkloadIn 的 camelCase 属性名 → param_machine_workload 列名（仓储 setattr 只认列名）。
_WORKLOAD_COLUMNS = {
    "kind": "kind",
    "engine": "engine",
    "model": "model",
    "port": "port",
    "listenAddr": "listen_addr",
    "publicAddr": "public_addr",
    "vramGb": "vram_gb",
    "healthPath": "health_path",
    "healthIntervalS": "health_interval_s",
    "note": "note",
    "state": "state",
}


def upsert_workloads(
    db: Session, machine_id: str, items: list[WorkloadIn], actor: str
) -> list[WorkloadOut]:
    _get_row(db, machine_id)
    rows = MachineRepository(db).replace_workloads(
        machine_id,
        [{_WORKLOAD_COLUMNS[key]: value for key, value in item.model_dump().items()} for item in items],
    )
    return [_workload_out(row) for row in rows]
