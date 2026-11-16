"""agent 注册、心跳与配置面端点（A0–A4，spec 2026-11-17 §7.2.1）。

register 是唯一的匿名 agent 端点（凭据是一次性注册码，放请求体）；
其余端点用 machine token（与用户 JWT 完全分离，§5.4）。
A5（turn-latency 上报）挂在本 router 上（Task 13 扩展）。
"""

from __future__ import annotations

from fastapi import APIRouter, Header, Query, Request, Response

from app.core.errors import ApiError
from app.deps import DbSession
from app.schemas.agent import (
    AgentConfigAckIn,
    AgentConfigReportIn,
    AgentRegisterIn,
    AgentTurnLatencyIn,
    HeartbeatIn,
)
from app.schemas.common import ok
from app.services import agent_config_service, agent_latency_service, agent_registry_service

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


@router.post("/turn-latency")
def report_turn_latency(
    payload: AgentTurnLatencyIn,
    db: DbSession,
    authorization: str = Header(default=""),
):
    """A5：逐轮 TURN_LATENCY 行上报；machine_id 取 token 所指机器（§5.4）。"""
    machine_id = _machine_id(db, authorization)
    return ok(agent_latency_service.report_rows(db, machine_id, payload.rows))
