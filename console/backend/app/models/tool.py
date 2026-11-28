"""控制台工具与本地日历事件（spec 2026-11-28 console tools module）。

`id` 稳定（对话页/语音工具声明按 id 引用），`builtin=true` 的行由 0022 迁移 seed。
`scope=session` 的工具定义仍落库，只有 enabled 由浏览器 localStorage 决定。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ConsoleTool(Base):
    __tablename__ = "ai_console_tool"
    __table_args__ = (UniqueConstraint("name", name="uq_ai_console_tool_name"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    endpoint: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    method: Mapped[str] = mapped_column(String(8), nullable=False, default="GET")
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="global")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    owner: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    params: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class CalendarEvent(Base):
    __tablename__ = "ai_console_calendar_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    start_at: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    end_at: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    description: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
