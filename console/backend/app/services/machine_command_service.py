"""机器命令下发/拉取/回执（reverse-pull，面向机器端 agent）。

状态机：pending → dispatched → succeeded/failed，expires_at 到期转 expired。
同一 machine_id + kind 只允许一条未完成命令（幂等去重，拒绝重复下发）。
审计只记命令 ID/类型，不记 payload 与探测结果大对象。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.machine_command import FAILED, PENDING, SUCCEEDED, ParamMachineCommand
from app.repositories.audit_repository import AuditRepository
from app.repositories.machine_command_repository import MachineCommandRepository
from app.repositories.machine_repository import MachineRepository

KINDS = frozenset({"drain", "resume", "reboot", "recover", "health_check"})
DEFAULT_TTL_S = 120
DEFAULT_LIMIT = 20


def _aware(value: datetime | None) -> datetime | None:
    """SQLite 把 aware UTC 读回 naive；对外一律补回 UTC（与 routing_service 同口径）。"""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _as_dict(row: ParamMachineCommand) -> dict[str, Any]:
    return {
        "command_id": row.command_id,
        "machine_id": row.machine_id,
        "kind": row.kind,
        "payload": row.payload,
        "status": row.status,
        "result": row.result,
        "error": row.error,
        "expires_at": _aware(row.expires_at),
        "dispatched_at": _aware(row.dispatched_at),
        "finished_at": _aware(row.finished_at),
        "created_at": _aware(row.created_at),
    }


def _audit(db: Session, *, actor: str, action: str, command: dict) -> None:
    AuditRepository(db).record(
        actor=actor,
        role="",
        action=action,
        profile=command["machine_id"],
        fields=["command_id", "kind"],
        request_id=command["command_id"],
    )


def issue(
    db: Session,
    machine_id: str,
    kind: str,
    *,
    actor: str,
    payload: dict | None = None,
    ttl_s: int = DEFAULT_TTL_S,
) -> dict[str, Any]:
    if kind not in KINDS:
        raise ValueError(f"unsupported command kind: {kind}")
    if MachineRepository(db).get(machine_id) is None:
        raise KeyError(machine_id)
    now = utcnow()
    repo = MachineCommandRepository(db)
    if repo.has_active(machine_id, kind, now=now):
        raise ValueError("in_flight: command already pending or dispatched")
    row = repo.insert(
        command_id=uuid4().hex,
        machine_id=machine_id,
        kind=kind,
        payload=dict(payload or {}),
        expires_at=now + timedelta(seconds=ttl_s),
    )
    command = _as_dict(row)
    _audit(db, actor=actor, action="machine.command.issue", command=command)
    return command


def expire_stale(db: Session) -> int:
    """把超时未回执的命令收敛为 expired，供 poll/前端列表看到终态。"""
    count = MachineCommandRepository(db).expire(now=utcnow())
    if count:
        AuditRepository(db).record(
            actor="system", role="", action="machine.command.expire", profile="", fields=[]
        )
    return count


def poll(db: Session, machine_id: str, *, limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
    """agent 拉取：先收敛超时，再领本机的 pending 命令（条件 UPDATE）。"""
    expire_stale(db)
    repo = MachineCommandRepository(db)
    now = utcnow()
    claimed: list[dict[str, Any]] = []
    for row in repo.pending_for(machine_id, limit, now=now):
        if repo.mark_dispatched(row.command_id, now=now):
            claimed.append(_as_dict(row))
    return claimed


def report(
    db: Session,
    machine_id: str,
    command_id: str,
    *,
    ok: bool,
    result: dict | None = None,
    error: str = "",
) -> dict[str, Any]:
    """agent 回执；machine_id 必须与 token 所指机器一致（路由层额外校验）。"""
    repo = MachineCommandRepository(db)
    row = repo.get(command_id)
    if row is None:
        raise KeyError(command_id)
    if row.machine_id != machine_id:
        raise PermissionError("command belongs to another machine")
    if not repo.finish(
        command_id,
        status=SUCCEEDED if ok else FAILED,
        result=result,
        error=error,
        now=utcnow(),
    ):
        raise ValueError("command is not dispatched")
    command = _as_dict(repo.get(command_id))
    _audit(db, actor=machine_id, action="machine.command.report", command=command)
    return command


def list_for_machine(db: Session, machine_id: str, *, limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
    expire_stale(db)
    return [_as_dict(row) for row in MachineCommandRepository(db).list_by_machine(machine_id, limit)]
