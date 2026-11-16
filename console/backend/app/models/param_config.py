from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ParamConfig(Base):
    """控制台配置项登记表：库中的值优先于环境变量（spec 2026-11-17 §2.3）。

    值统一按字符串存（`value` + `value_type` 配对），读取方按 `value_type` 转型。
    这样加一个配置项不需要改表结构，也不用为 str/int/float/bool 各建一列。

    只有登记在 `app/config/_schema.py` 的键才能落库：这张表是"控制台自己读自己写"
    的白名单，不是任意键值袋。
    """

    __tablename__ = "param_config"
    __table_args__ = (UniqueConstraint("config_key", name="uq_param_config_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 列名不叫 key：SQLite 把 KEY 当保留字，SQLAlchemy 会给它加引号（"key"），
    # 双方言的裸 SQL 就对不上了。config_key 两个方言都渲染成裸列名。
    config_key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    value_type: Mapped[str] = mapped_column(String(16), nullable=False, default="str")
    section: Mapped[str] = mapped_column(String(32), nullable=False, default="console")
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # 启动期语义（是否起巡检任务、是否注册路由等）的键改完需要重启 console。
    restart_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 单调递增的写入版本；读侧据此判断缓存是否过期（spec §2.3）。
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
