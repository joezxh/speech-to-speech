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

from app.core.errors import ApiError
from app.models.machine import ParamMachine
from app.models.machine_config import ParamAgentConfigVersion
from app.models.param_audit import ParamAudit
from app.models.param_instance import ParamInstance
from app.models.param_instance_runtime import ParamInstanceRuntime
from app.repositories.audit_repository import AuditRepository
from app.repositories.machine_repository import MachineRepository
from app.schemas.common import iso_utc

REGISTER_CODE_BYTES = 24

# 平台类型（模板硬件校验用）：显式传入优先，否则按 gpu 描述推断；推断不出 → cpu。
PLATFORMS = ("gpu", "npu", "amd", "cpu")
_GPU_HINTS = ("rtx", "gtx", "nvidia", "cuda", "a100", "h100", "l40", "4090", "3090", "t4", "v100")
_NPU_HINTS = ("ascend", "npu", "910b", "310p")
_AMD_HINTS = ("radeon", "amd", "mi3", "instinct")


def infer_platform(gpu: str) -> str:
    """从显卡描述推断平台类型；模板面板的平台徽章与硬件校验消费该值。"""
    text = (gpu or "").lower()
    if any(hint in text for hint in _NPU_HINTS):
        return "npu"
    if any(hint in text for hint in _AMD_HINTS):
        return "amd"
    if any(hint in text for hint in _GPU_HINTS):
        return "gpu"
    return "cpu"


def _resolve_platform(platform: str | None, gpu: str) -> str:
    if platform and platform in PLATFORMS:
        return platform
    return infer_platform(gpu)


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
    params: dict = Field(default_factory=dict)
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
    platform: str | None = Field(default=None, max_length=16)
    driver: str | None = Field(default=None, max_length=64)
    version: str = ""
    registryMode: str = Field(default="manual", max_length=16)


class RegisterTestIn(BaseModel):
    """M8：三步注册测试（simulate=fail 演练"agent 不来"路径）。"""

    machineId: str = Field(min_length=1, max_length=64)
    addr: str = ""
    clusterId: str = Field(default="", max_length=64)
    profile: str | None = None
    simulate: bool = False


class AutoRegisterIn(BaseModel):
    """M9：自动注册受理（不代 agent 完成注册）。"""

    clusterId: str = Field(default="", max_length=64)
    addr: str = ""
    machineId: str | None = None


class MachineUpdate(BaseModel):
    """部分更新：只取显式传入的字段（exclude_unset）。"""

    clusterId: str | None = Field(default=None, max_length=64)
    profile: str | None = Field(default=None, max_length=64)
    addr: str | None = Field(default=None, max_length=255)
    role: str | None = Field(default=None, max_length=16)
    gpu: str | None = Field(default=None, max_length=64)
    gpuTotalGb: float | None = Field(default=None, ge=0)
    platform: str | None = Field(default=None, max_length=16)
    driver: str | None = Field(default=None, max_length=64)
    version: str | None = None


class MachineOut(BaseModel):
    machineId: str
    clusterId: str
    profile: str | None = None
    addr: str = ""
    role: str = "agent"
    gpu: str = ""
    gpuTotalGb: float | None = None
    platform: str = "gpu"
    driver: str = ""
    version: str = ""
    state: str = "pending_register"
    registryMode: str = "manual"
    agentVersion: str = ""
    protocolVersion: int = 1
    lastSeen: str | None = None
    workloads: list[WorkloadOut] = Field(default_factory=list)
    # 部署详情（真源派生，无来源为 None/空）
    gpuUtilPct: int | None = None
    cpuPct: float | None = None
    loadAvg: list[float] = Field(default_factory=list)
    memTotalGb: float | None = None
    memUsedGb: float | None = None
    memPct: float | None = None
    gpuMemUsedGb: float | None = None
    gpuMemTotalGb: float | None = None
    pipelineVramGb: float | None = None
    collectedAt: str | None = None
    deployment: dict = Field(default_factory=dict)
    deployedAt: str | None = None
    configSource: str | None = None
    lastPushAt: str | None = None
    lastPushBy: str = ""


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
    "platform": "platform",
    "driver": "driver",
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
        params=row.params_json or {},
        state=row.state,
    )


def _detail_context(db: Session, rows: list[ParamMachine]) -> dict[str, tuple[ParamAudit | None, bool]]:
    """一次查询批量取最近下发审计与配置快照，避免机器列表 N+1。"""
    ids = [row.machine_id for row in rows]
    if not ids:
        return {}
    audits = db.scalars(
        select(ParamAudit)
        .where(ParamAudit.action == "machine.config.deploy", ParamAudit.profile.in_(ids))
        .order_by(ParamAudit.id.desc())
    ).all()
    latest: dict[str, ParamAudit] = {}
    for audit in audits:
        latest.setdefault(audit.profile, audit)
    with_config = set(
        db.scalars(
            select(ParamAgentConfigVersion.machine_id).where(
                ParamAgentConfigVersion.machine_id.in_(ids)
            )
        ).all()
    )
    return {machine_id: (latest.get(machine_id), machine_id in with_config) for machine_id in ids}


def _machine_out(
    db: Session,
    row: ParamMachine,
    context: dict[str, tuple[ParamAudit | None, bool]] | None = None,
) -> MachineOut:
    audit, has_config = (context or {}).get(row.machine_id, (None, False))
    if context is None:
        audit, has_config = _detail_context(db, [row]).get(row.machine_id, (None, False))
    pushed_at = iso_utc(audit.at) if audit is not None else None
    return MachineOut(
        machineId=row.machine_id,
        clusterId=row.cluster_id,
        profile=row.profile,
        addr=row.addr,
        role=row.role,
        gpu=row.gpu,
        gpuTotalGb=row.gpu_total_gb,
        platform=row.platform,
        driver=row.driver,
        version=row.version,
        state=row.state,
        registryMode=row.registry_mode,
        agentVersion=row.agent_version,
        protocolVersion=row.protocol_version,
        lastSeen=iso_utc(row.last_seen_at) if row.last_seen_at else None,
        workloads=[_workload_out(w) for w in MachineRepository(db).list_workloads(row.machine_id)],
        gpuUtilPct=row.gpu_util_pct,
        cpuPct=row.cpu_pct,
        loadAvg=list(row.load_avg or []),
        memTotalGb=row.mem_total_gb,
        memUsedGb=row.mem_used_gb,
        memPct=row.mem_pct,
        gpuMemUsedGb=row.gpu_mem_used_gb,
        gpuMemTotalGb=row.gpu_mem_total_gb,
        pipelineVramGb=row.pipeline_vram_gb,
        collectedAt=row.collected_at or None,
        deployment=row.deployment_json or {},
        deployedAt=pushed_at,
        configSource="console" if has_config else None,
        lastPushAt=pushed_at,
        lastPushBy=audit.actor if audit is not None else "",
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
    rows = MachineRepository(db).list(cluster)
    context = _detail_context(db, rows)
    return [_machine_out(db, row, context) for row in rows]


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
        platform=_resolve_platform(p.platform, p.gpu),
        driver=p.driver or "",
        version=p.version,
        state="pending_register",
        registry_mode=p.registryMode,
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
    if "platform" in changed and changed["platform"] and changed["platform"] not in PLATFORMS:
        raise ApiError("invalid_request", f"platform must be one of {', '.join(PLATFORMS)}", 400)
    for attr, value in changed.items():
        setattr(row, _UPDATE_COLUMNS[attr], value)
    if "gpu" in changed and "platform" not in changed:
        row.platform = infer_platform(changed["gpu"] or "")
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
    "params": "params_json",
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


# ---- M8 三步注册测试 / M9 自动注册 -----------------------------------------


def _issue_register_code(db: Session, machine_id: str) -> str:
    """签发（或重签）一次性注册码；旧码明文已不可得，重签即覆盖哈希。"""
    register_code = secrets.token_urlsafe(REGISTER_CODE_BYTES)
    row = _get_row(db, machine_id)
    row.register_code_hash = hash_secret(register_code)
    db.commit()
    return register_code


def register_test(db: Session, p: RegisterTestIn, actor: str) -> dict:
    """三步注册测试（§7.2.2 M8）。步1 建档（幂等：已存在则重签注册码）；
    步2/3 按当前库态评估——agent 是异步来的，本调用只报快照，前端可轮询。"""
    register_code = ""
    if MachineRepository(db).get(p.machineId) is None:
        machine, register_code = create_machine(
            db,
            MachineCreate(
                machineId=p.machineId,
                addr=p.addr,
                clusterId=p.clusterId,
                profile=p.profile,
            ),
            actor=actor,
        )
    else:
        register_code = _issue_register_code(db, p.machineId)
        machine = _machine_out(db, _get_row(db, p.machineId))

    token_issued = _get_row(db, p.machineId).token_hash is not None
    heartbeat_seen = _get_row(db, p.machineId).last_seen_at is not None
    step2_state = "fail" if p.simulate else ("pass" if token_issued else "pending")
    step3_state = "fail" if p.simulate else ("pass" if heartbeat_seen else "pending")
    row = _get_row(db, p.machineId)

    steps = [
        {
            "key": "step1",
            "label": "向注册中心登记",
            "state": "pass",
            "detail": {"machineId": machine.machineId, "state": machine.state},
        },
        {
            "key": "step2",
            "label": "已下发注册指令 —— 等待机器端 Agent 上报",
            "state": step2_state,
            "detail": {} if p.simulate else {"registerCode": register_code},
        },
        {
            "key": "step3",
            "label": "Agent 握手 · 心跳 · 版本上报",
            "state": step3_state,
            "detail": {
                "agentVersion": row.agent_version,
                "protocolVersion": row.protocol_version,
                "lastSeen": machine.lastSeen,
            },
        },
    ]
    return {
        "steps": steps,
        "ok": all(step["state"] == "pass" for step in steps),
        "register_code": register_code,
    }


def auto_register(db: Session, p: AutoRegisterIn, actor: str) -> dict:
    """M9：模拟"机器自己来登记"。只做受理——生成注册码挂待接入（pending_register），
    真实建档走 agent 首次注册。machine_id 缺省自动生成。"""
    machine_id = p.machineId or f"auto-{secrets.token_hex(4)}"
    machine, register_code = create_machine(
        db,
        MachineCreate(machineId=machine_id, addr=p.addr, clusterId=p.clusterId, registryMode="auto"),
        actor=actor,
    )
    return {
        "machineId": machine.machineId,
        "registerCode": register_code,
        "state": machine.state,
    }
