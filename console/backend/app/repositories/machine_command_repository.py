"""命令队列读写：状态流转用条件 UPDATE 抢占，避免两个 agent 重复领同一条。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.machine_command import (
    DISPATCHED,
    EXPIRED,
    FAILED,
    PENDING,
    SUCCEEDED,
    ParamMachineCommand,
)

ACTIVE = (PENDING, DISPATCHED)
FINAL = (SUCCEEDED, FAILED, EXPIRED)


class MachineCommandRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, command_id: str) -> ParamMachineCommand | None:
        return self.session.scalar(
            select(ParamMachineCommand).where(ParamMachineCommand.command_id == command_id)
        )

    def insert(self, *, command_id: str, machine_id: str, kind: str, payload: dict, expires_at) -> ParamMachineCommand:
        row = ParamMachineCommand(
            command_id=command_id,
            machine_id=machine_id,
            kind=kind,
            payload=payload,
            expires_at=expires_at,
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def has_active(self, machine_id: str, kind: str, *, now: datetime) -> bool:
        row = self.session.scalar(
            select(ParamMachineCommand)
            .where(
                ParamMachineCommand.machine_id == machine_id,
                ParamMachineCommand.kind == kind,
                ParamMachineCommand.status.in_(ACTIVE),
                ParamMachineCommand.expires_at > now,
            )
            .limit(1)
        )
        return row is not None

    def pending_for(self, machine_id: str, limit: int, *, now: datetime) -> list[ParamMachineCommand]:
        return list(
            self.session.scalars(
                select(ParamMachineCommand)
                .where(
                    ParamMachineCommand.machine_id == machine_id,
                    ParamMachineCommand.status == PENDING,
                    ParamMachineCommand.expires_at > now,
                )
                .order_by(ParamMachineCommand.id)
                .limit(limit)
            )
        )

    def mark_dispatched(self, command_id: str, *, now: datetime, commit: bool = True) -> bool:
        result = self.session.execute(
            update(ParamMachineCommand)
            .where(
                ParamMachineCommand.command_id == command_id,
                ParamMachineCommand.status == PENDING,
            )
            .values(status=DISPATCHED, dispatched_at=now)
        )
        if commit:
            self.session.commit()
        return bool(result.rowcount)

    def finish(
        self,
        command_id: str,
        *,
        status: str,
        result: dict | None,
        error: str,
        now: datetime,
        commit: bool = True,
    ) -> bool:
        done = self.session.execute(
            update(ParamMachineCommand)
            .where(
                ParamMachineCommand.command_id == command_id,
                ParamMachineCommand.status == DISPATCHED,
            )
            .values(status=status, result=result, error=error, finished_at=now)
        )
        if commit:
            self.session.commit()
        return bool(done.rowcount)

    def expire(self, *, now: datetime, commit: bool = True) -> int:
        done = self.session.execute(
            update(ParamMachineCommand)
            .where(
                ParamMachineCommand.status.in_(ACTIVE),
                ParamMachineCommand.expires_at.is_not(None),
                ParamMachineCommand.expires_at < now,
            )
            .values(status=EXPIRED, finished_at=now, error="expired")
        )
        if commit:
            self.session.commit()
        return int(done.rowcount or 0)

    def list_by_machine(self, machine_id: str, limit: int) -> list[ParamMachineCommand]:
        return list(
            self.session.scalars(
                select(ParamMachineCommand)
                .where(ParamMachineCommand.machine_id == machine_id)
                .order_by(ParamMachineCommand.id.desc())
                .limit(limit)
            )
        )
