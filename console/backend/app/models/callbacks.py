"""回调子系统两张表（spec 2026-11-25 §8.1）：目标配置 + 投递日志。

callback_delivery_log.target_id 对 callback_target.id 是 SET NULL 软关联：
目标删除后日志保留（审计口径）。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class CallbackTarget(Base):
    """一个回调目标的完整配置；java/python 两类协议由 target_type 区分。"""

    __tablename__ = "callback_target"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    # java: base_url + 固定内部端点路径；python: base_url 即完整 webhook URL
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)  # java | python
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    auth_type: Mapped[str] = mapped_column(String(16), nullable=False, default="none")  # none|bearer|header_token
    auth_header_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    auth_token: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    extra_headers: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=3000)
    retry_max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    retry_backoff_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    events: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # ["transcript", ...]
    filters: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"speakers": [...], "min_text_len": N}
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class CallbackDeliveryLog(Base):
    """每次投递尝试一行；payload 截断存储、token 脱敏（写入方负责）。"""

    __tablename__ = "callback_delivery_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("callback_target.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    request_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    request_payload: Mapped[str] = mapped_column(Text, nullable=False, default="")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_snippet: Mapped[str] = mapped_column(Text, nullable=False, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # success|failed|retrying
    error: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
