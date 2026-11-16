from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ParamProxyMetric(Base):
    """数据面代理采样：按实例与服务记录成功数与失败原因。

    与 `param_instance_metric` 分表：那张表的列语义是**槽位**（size/in_use/free/
    stuck），塞进代理耗时会让两套口径混在一张表里，而 UI 已按列语义画图。

    不建 FK：实例删除后指标仍可读（同 param_instance_metric）。
    `ok` 是采样窗口内的增量而非累计值。
    """

    __tablename__ = "param_proxy_metric"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    service: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, default=utcnow
    )
    # console 标识（CONSOLE_ID，默认主机名）：多 console 多活必需。
    observed_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    ok: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 列名避开 fail（SQL 保留字，alembic 会加引号，破坏 schema 守护测试的列名正则）。
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fail_reason: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
