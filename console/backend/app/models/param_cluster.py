from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ParamCluster(Base):
    """集群边界的管理标签（spec §2.1）。不建 FK：`param_instance.cluster_id` 是软关联，
    与 param_instance/param_instance_metric 既有做法一致。
    registry 空串 = default 集群（存量零感知的落点）；非空值的全局唯一由服务层校验，
    DB 层不加唯一约束（spec §2.1）。"""

    __tablename__ = "param_cluster"
    __table_args__ = (UniqueConstraint("name", name="uq_param_cluster_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    registry: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    policy: Mapped[str] = mapped_column(String(16), nullable=False, default="least")
    note: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
