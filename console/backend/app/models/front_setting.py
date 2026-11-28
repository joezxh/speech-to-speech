from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ParamFrontSetting(Base):
    """前台设置：对话态热更参数的账号级取值（spec 2026-11-28 §后端 1）。

    全局一份，不按机器分列：语义对齐原型的 `state.settings` —— 改一次全站生效。
    值按字符串存（`value` + `value_type` 配对），与 `param_config` 同一思路；
    这里放宽到 2048 以容下 2000 字的提示词。
    """

    __tablename__ = "param_front_setting"
    __table_args__ = (UniqueConstraint("config_key", name="uq_param_front_setting_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 列名不叫 key：SQLite 把 KEY 当保留字（见 param_config 的同款说明）。
    config_key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    value_type: Mapped[str] = mapped_column(String(16), nullable=False, default="str")
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
