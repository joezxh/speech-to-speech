"""agent 注册与心跳端点（A0/A1，spec 2026-11-17 §7.2.1）。

register 是唯一的匿名 agent 端点（凭据是一次性注册码，放请求体）；
heartbeat 用 machine token（与用户 JWT 完全分离，§5.4）。
后续 A2/A3/A4/A5 挂在本 router 上（Task 6/13 扩展）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header

from app.core.errors import ApiError
from app.deps import DbSession
from app.schemas.agent import AgentRegisterIn, HeartbeatIn
from app.schemas.common import ok
from app.services import agent_registry_service

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


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
    machine_id = agent_registry_service.authenticate(db, authorization)
    try:
        data = agent_registry_service.heartbeat(db, machine_id, payload)
    except ApiError:
        raise
    return ok(data)
