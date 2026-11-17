"""agent 注册、心跳与配置面端点（A0–A4，spec 2026-11-17 §7.2.1）。

register 是唯一的匿名 agent 端点（凭据是一次性注册码，放请求体）；
其余端点用 machine token（与用户 JWT 完全分离，§5.4）。
A5（turn-latency 上报）挂在本 router 上（Task 13 扩展）。
"""

from __future__ import annotations

from fastapi import APIRouter, Header, Query, Request, Response

from app.config import console as console_settings
from app.core.errors import ApiError
from app.deps import DbSession
from app.repositories.audit_repository import AuditRepository
from app.repositories.instance_repository import InstanceRepository
from app.schemas.agent import (
    AgentCommandReportIn,
    AgentConfigAckIn,
    AgentConfigReportIn,
    AgentDrainIn,
    AgentLogsIn,
    AgentRegisterIn,
    AgentTurnLatencyIn,
    HeartbeatIn,
)
from app.schemas.common import iso_utc, ok
from app.services import (
    agent_config_service,
    agent_latency_service,
    agent_registry_service,
    instance_monitor,
    log_service,
    machine_command_service,
)

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


def _machine_id(db, authorization: str, claimed_machine_id: str = "") -> str:
    """token → machine_id；body/query 里的 machine_id 只做一致性校验（§5.4）。"""
    machine_id = agent_registry_service.authenticate(db, authorization)
    if claimed_machine_id and claimed_machine_id != machine_id:
        raise ApiError("forbidden", "machine_id does not match token", 403)
    return machine_id


@router.post("/register")
def register(payload: AgentRegisterIn, db: DbSession):
    """一次性注册码换正式 machine token；码用过即焚，错码/复用一律 401。"""
    return ok(agent_registry_service.register(db, payload))


@router.post("/heartbeat")
def heartbeat(
    payload: HeartbeatIn,
    db: DbSession,
    authorization: str = Header(default=""),
):
    """心跳 + 负载清单 + 运行时摘要 + token 增量（合并上报，减少往返）。"""
    machine_id = _machine_id(db, authorization)
    return ok(agent_registry_service.heartbeat(db, machine_id, payload))


@router.get("/config")
def pull_config(
    request: Request,
    db: DbSession,
    machine_id: str = Query(default=""),
    authorization: str = Header(default=""),
):
    """A2：拉取目标配置（渲染后的 YAML + 版本号）；If-None-Match 命中 → 304。"""
    mapped = _machine_id(db, authorization, machine_id)
    data, status, etag = agent_config_service.pull(
        db, mapped, request.headers.get("if-none-match", "")
    )
    if status == 304:
        return Response(status_code=304, headers={"ETag": etag})
    return ok(data)


@router.post("/config/report")
def report_config(
    payload: AgentConfigReportIn,
    db: DbSession,
    authorization: str = Header(default=""),
):
    """A3：回报实际生效配置；与 profile live 期望值比对得 drift_count。"""
    machine_id = _machine_id(db, authorization)
    return ok(agent_config_service.report_values(db, machine_id, payload.config_version, payload.values))


@router.post("/config/ack")
def ack_config(
    payload: AgentConfigAckIn,
    db: DbSession,
    authorization: str = Header(default=""),
):
    """A4：落地结果；ok=false 的版本不留下发快照。"""
    machine_id = _machine_id(db, authorization)
    return ok(agent_config_service.ack(db, machine_id, payload.config_version, payload.ok, payload.error))


@router.get("/commands")
def pull_commands(
    db: DbSession,
    limit: int = Query(default=10, ge=1, le=50),
    authorization: str = Header(default=""),
):
    """机器端拉取命令：machine token 决定 machine_id，领到即置 dispatched。"""
    machine_id = _machine_id(db, authorization)
    return ok(
        [
            {
                "command_id": row["command_id"],
                "kind": row["kind"],
                "payload": row["payload"],
                "issued_at": iso_utc(row["created_at"]),
                "expires_at": iso_utc(row["expires_at"]),
            }
            for row in machine_command_service.poll(db, machine_id, limit=limit)
        ]
    )


@router.post("/commands/{command_id}/report")
def report_command(
    command_id: str,
    payload: AgentCommandReportIn,
    db: DbSession,
    authorization: str = Header(default=""),
):
    """机器端回执：真实执行/探测结果写入命令记录，越权机器 403。"""
    machine_id = _machine_id(db, authorization)
    try:
        command = machine_command_service.report(
            db,
            machine_id,
            command_id,
            ok=payload.ok,
            result=payload.result,
            error=payload.error,
        )
    except KeyError:
        raise ApiError("not_found", f"command {command_id} does not exist", 404) from None
    except PermissionError:
        raise ApiError("forbidden", "command belongs to another machine", 403) from None
    except ValueError:
        raise ApiError("conflict", "command is not dispatched", 409) from None
    return ok({"command_id": command["command_id"], "status": command["status"]})


def _bound_instances(db, machine_id: str) -> list[str]:
    return [
        row.instance_id
        for row in InstanceRepository(db).list_all()
        if row.machine_id == machine_id
    ]


@router.post("/instances/drain")
def agent_set_drain(
    payload: AgentDrainIn,
    db: DbSession,
    authorization: str = Header(default=""),
):
    """agent 执行排空/恢复：DB 期望态 + 内存注册表同步（与用户侧 drain 同口径）。"""
    machine_id = _machine_id(db, authorization)
    ids = _bound_instances(db, machine_id)
    for instance_id in ids:
        InstanceRepository(db).set_drain(instance_id, drain=payload.drain, updated_by=machine_id)
        # 还没被巡检到的实例只有 DB 期望态，内存态等首轮探测自然带上。
        if instance_monitor.registry.get(instance_id) is not None:
            instance_monitor.registry.set_drain(instance_id, payload.drain)
    if ids:
        instance_monitor.invalidate()
        AuditRepository(db).record(
            actor=machine_id,
            role="",
            action="machine.instance.drain" if payload.drain else "machine.instance.undrain",
            profile=machine_id,
            fields=["drain_requested"],
        )
    return ok({"instanceIds": ids, "drainRequested": payload.drain})


@router.post("/instances/probe")
def agent_probe_instances(
    db: DbSession,
    authorization: str = Header(default=""),
):
    """agent 执行拉起后的巡检：真实探测并回传本机实例状态。"""
    machine_id = _machine_id(db, authorization)
    instance_monitor.probe_all(db)
    instance_monitor.invalidate()
    statuses = {}
    for instance_id in _bound_instances(db, machine_id):
        state = instance_monitor.registry.get(instance_id)
        statuses[instance_id] = state.status if state else "unknown"
    return ok({"statuses": statuses})


@router.post("/logs")
def agent_upload_logs(
    payload: AgentLogsIn,
    db: DbSession,
    authorization: str = Header(default=""),
):
    """容器日志落盘到既有四日志文件，供 /api/v1/logs 与 /logs/analyze 复用。"""
    machine_id = _machine_id(db, authorization)
    written = log_service.append_agent_logs(
        console_settings.log_dir, machine_id, [row.model_dump() for row in payload.logs]
    )
    return ok({"written": written})


@router.post("/turn-latency")
def report_turn_latency(
    payload: AgentTurnLatencyIn,
    db: DbSession,
    authorization: str = Header(default=""),
):
    """A5：逐轮 TURN_LATENCY 行上报；machine_id 取 token 所指机器（§5.4）。"""
    machine_id = _machine_id(db, authorization)
    return ok(agent_latency_service.report_rows(db, machine_id, payload.rows))
