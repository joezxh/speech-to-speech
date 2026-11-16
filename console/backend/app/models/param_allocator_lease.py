from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ParamAllocatorLease(Base):
    """选台占位明细（spec 2026-11-17 §2.1）：跨副本共享的槽位租约。

    `param_instance_runtime.reserved` 是聚合计数（用于原子判定），这张表是明细：
    每一条对应一次预留，键是控制台自己生成的 uuid，不是上游 session_id——
    这样"预留 → 会话"是同一把 key，占位不会泄漏到 TTL 才回收。

    状态两态：
    - `pending`：已预留未连接，靠 `expires_at` 超时回收；
    - `held`：会话已建立，随会话结束释放，不靠 TTL。

    两者都占槽位，都要从 free 里扣（spec 2026-11-16 §5.3）。

    不建 FK：实例删除后残留租约由服务层清理，历史仍可读。
    """

    __tablename__ = "param_allocator_lease"

    lease_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    # pending 的回收时刻（墙钟）；held 为空。
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    # 占住这个槽位的控制台副本，用于排查与自愈。
    console_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
