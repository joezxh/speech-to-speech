from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ParamInstanceMetric(Base):
    """30s 采样 + 状态跳变即时落。不建 FK：实例删除后指标仍可读（spec §5.2）。
    计数列是采样窗口内的增量，非累计；NULL=不可得，不写 0。"""

    __tablename__ = "param_instance_metric"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    # console 标识（CONSOLE_ID，默认主机名）：多 console 多活必需，聚合按实例取最新不累加。
    observed_by: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="sample")
    size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    in_use: Mapped[int | None] = mapped_column(Integer, nullable=True)
    free: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stuck: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    probe_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alloc_ok: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alloc_fail_no_instance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alloc_fail_instance_503: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evict_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recover_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
