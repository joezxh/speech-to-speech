"""机器命令队列（reverse-pull 通道，spec 2026-11-17 机器管理对齐）。

console 不主动连 NAT 后的机器：这里存用户下发的命令，machine token 鉴权的
agent 拉取并回执。软关联 machine_id（无 FK），机器删除后历史命令仍可读。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow

PENDING = "pending"
DISPATCHED = "dispatched"
SUCCEEDED = "succeeded"
FAILED = "failed"
EXPIRED = "expired"


class ParamMachineCommand(Base):
    __tablename__ = "param_machine_command"
    __table_args__ = (
        UniqueConstraint("command_id", name="uq_param_machine_command_command_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    command_id: Mapped[str] = mapped_column(String(64), nullable=False)
    machine_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=PENDING, index=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
