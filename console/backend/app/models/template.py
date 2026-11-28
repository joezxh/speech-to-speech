"""参数模板实体（原型 console-refactor-demo.html 的「模板管理」页落库）。

模板分两类：effect=runtime（对话态热更，作用于活跃会话）与 effect=restart
（pipeline 启动参数，需发布并重启）。每条模板内置一份推荐配置方案（scene 是
SCENES 的 key，方案内容在目录侧维护，模板只存绑定关系）。

fields_json 存字段快照 [{key, value, patch, source, hot}]；字段 schema 以
parameter-catalog 为单一事实源（template_service 校验），这里只存数据。
name 全局唯一（前端按名称检索、模板选择条按名称展示）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ParamTemplate(Base):
    __tablename__ = "param_template"
    __table_args__ = (UniqueConstraint("name", name="uq_param_template_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # runtime = 对话态热更（session.update 白名单内）；restart = 启动参数（发布 + 重启）。
    effect: Mapped[str] = mapped_column(String(16), nullable=False, default="runtime")
    # 平台类型：gpu | npu | amd | cpu；硬件校验按机器 platform + 显存比对。
    platform: Mapped[str] = mapped_column(String(16), nullable=False, default="gpu")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    # 绑定场景（推荐配置方案的固定组成部分）；空 = 未绑定。
    scene: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    min_vram_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    # [{key, value, patch, source, hot}]；patch 为 session.update 路径（hot）或 YAML 键。
    fields_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    description: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
