"""配置读取门面背后的存储（spec 2026-11-17 §4.2–4.5）。

`ConfigStore` 只做三件事：

1. **播种**：把 env 解析出的默认值写进 `param_config`（只写缺失的键）；
2. **读取**：库优先，库里没有或读库失败就回退 env 默认值（进程内 TTL 缓存）；
3. **写入**：校验类型与取值域 → 写表 → 让本进程缓存立即失效。

DB 不可用不是故障：读路径静默降级到 env，语音链路不受影响（设计 §5.1）。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from app.config._schema import ITEMS, coerce, item_by_key, render
from app.repositories.config_repository import ConfigRepository

SOURCE_DB = "db"
SOURCE_ENV = "env"


def _default_session_factory():
    # 延迟导入：app.db.database 依赖 app.config.database，模块级导入会成环。
    from app.db.database import SessionLocal

    return SessionLocal


class ConfigStore:
    """库优先、env 兜底、TTL 缓存的配置存储。"""

    def __init__(
        self,
        defaults: Mapping[str, Mapping[str, Any]],
        *,
        session_factory=None,
        ttl_s: float = 2.0,
    ) -> None:
        # defaults：分区 → 属性名 → env 解析出的默认值
        self._defaults = defaults
        self._session_factory = session_factory
        self._ttl_s = ttl_s
        self._lock = threading.Lock()
        self._cached: dict[str, str] | None = None
        self._cached_until = 0.0
        self._db_ok = True

    # ── 读取 ────────────────────────────────────────────────────────────
    def _rows(self) -> dict[str, str]:
        """库里的全部键值，带 TTL 缓存；读库失败按空表处理。"""
        now = time.monotonic()
        with self._lock:
            if self._cached is not None and now < self._cached_until:
                return self._cached
        rows = self._load_rows()
        with self._lock:
            self._cached = rows
            self._cached_until = time.monotonic() + self._ttl_s
            return rows

    def _load_rows(self) -> dict[str, str]:
        factory = self._session_factory or _default_session_factory()
        try:
            with factory() as session:
                rows = ConfigRepository(session).values()
        except Exception as exc:  # 读库失败：降级到 env，不影响链路
            logger.warning(f"读取配置表失败，本次回退环境变量默认值：{exc}")
            with self._lock:
                self._db_ok = False
            return {}
        with self._lock:
            self._db_ok = True
        return rows

    def env_value(self, key: str) -> str:
        """env 默认值的字符串形态（播种用）。"""
        item = item_by_key(key)
        if item is None:
            return ""
        value = self._defaults.get(item.section, {}).get(item.attr)
        if value is None:
            return ""
        return render(item, value)

    def get_raw(self, key: str) -> tuple[str, str]:
        """返回 (值, 来源)；来源是 db 或 env。"""
        rows = self._rows()
        if key in rows:
            return rows[key], SOURCE_DB
        return self.env_value(key), SOURCE_ENV

    def get(self, key: str):
        """按登记类型返回有效值：库优先，库里没有或非法则回退 env。"""
        item = item_by_key(key)
        if item is None:
            raise KeyError(key)
        raw, source = self.get_raw(key)
        if source == SOURCE_DB:
            try:
                return coerce(item, raw)
            except ValueError:
                logger.warning(f"配置 {key} 的库值 {raw!r} 不合法，回退环境变量默认值")
        return self._defaults.get(item.section, {}).get(item.attr)

    def source(self, key: str) -> str:
        return self.get_raw(key)[1]

    def snapshot(self) -> list[dict[str, Any]]:
        """全部登记项的有效值 + 来源 + 元信息（供配置页与状态接口）。"""
        rows = self._rows()
        out: list[dict[str, Any]] = []
        for item in ITEMS:
            if item.key in rows:
                raw, source = rows[item.key], SOURCE_DB
            else:
                raw, source = self.env_value(item.key), SOURCE_ENV
            out.append(
                {
                    "key": item.key,
                    "value": raw,
                    "source": source,
                    "type": item.value_type,
                    "env": item.env,
                    "section": item.section,
                    "description": item.description,
                    "hot": item.hot,
                    "restart_required": item.restart_required,
                    "choices": list(item.choices),
                    "minimum": item.minimum,
                    "maximum": item.maximum,
                }
            )
        return out

    def source_summary(self) -> str:
        """来源概览：db（全部来自库）/ env（全部兜底）/ mixed（部分来自库）。"""
        rows = self._rows()
        if not rows:
            return SOURCE_ENV
        return SOURCE_DB if len(rows) >= len(ITEMS) else "mixed"

    # ── 写入 ────────────────────────────────────────────────────────────
    def set(self, session: Session, key: str, value: str, *, actor: str):
        """写一个配置项；类型或取值域不合法时抛 ValueError（调用方据此回 400）。"""
        item = item_by_key(key)
        if item is None:
            raise KeyError(key)
        typed = coerce(item, value)
        row = ConfigRepository(session).upsert(
            key=key,
            value=render(item, typed),
            value_type=item.value_type,
            section=item.section,
            description=item.description,
            restart_required=item.restart_required,
            updated_by=actor,
        )
        self.invalidate()
        return row

    # ── 播种 ────────────────────────────────────────────────────────────
    def seed_missing(self, session: Session) -> list[str]:
        """把 env 默认值写进配置表（只写缺失的键）。返回写入的键列表。"""
        rows = [
            (
                item.key,
                self.env_value(item.key),
                item.value_type,
                item.section,
                item.description,
                item.restart_required,
            )
            for item in ITEMS
        ]
        written = ConfigRepository(session).insert_missing(rows)
        if written:
            logger.info(f"播种配置项 {len(written)} 条到配置表")
            self.invalidate()
        return written

    def invalidate(self) -> None:
        with self._lock:
            self._cached = None
            self._cached_until = 0.0

    def set_session_factory(self, session_factory) -> None:
        """替换会话工厂（测试用：把读库指向测试库，而不是默认库）。"""
        self._session_factory = session_factory
        self.invalidate()

    @property
    def db_ok(self) -> bool:
        with self._lock:
            return self._db_ok  
