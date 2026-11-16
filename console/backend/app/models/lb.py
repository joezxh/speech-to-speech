from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ParamLbRule(Base):
    """路由规则（有序，按 priority 升序首条命中生效）。

    share_pct / sticky_ttl_s 仅对分流型规则有意义，其余规则存空。
    """

    __tablename__ = "param_lb_rule"
    __table_args__ = (UniqueConstraint("name", name="uq_param_lb_rule_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    match_type: Mapped[str] = mapped_column(String(16), nullable=False, default="default")
    match_value: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    target_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="instance")
    target_value: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    share_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sticky_ttl_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class ParamLbAffinity(Base):
    """会话亲和（粘性）：affinity_key 是会话派生键，命中则跳过规则评估。"""

    __tablename__ = "param_lb_affinity"

    affinity_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    machine_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rule_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    # 面板与过期清理读法都是“到期之前还有哪些”。
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


class ParamLbRouteLog(Base):
    """路由决策记账（算命中率与规则命中），只追加。"""

    __tablename__ = "param_lb_route_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )
    session_key: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    rule_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    matched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sticky_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_canary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
