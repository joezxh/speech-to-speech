"""配置业务层（spec 2026-11-17 §4.3 / §6.1）。

写配置的三条规矩：

1. **只允许登记在册的键**（`app/config/_schema.py` 白名单）；
2. **逐项校验类型与取值域，整批拒绝**——任一项非法就都不落库；
3. **写入即留审计，但 `fields` 只记字段名不记值**（沿用 `param_audit` 既有口径）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.config import store as config_store
from app.config._schema import ITEMS, coerce, item_by_key, render


class ConfigError(ValueError):
    """配置不合法：键未登记，或类型/取值域不对。"""


def snapshot() -> list[dict[str, Any]]:
    """全部登记项的有效值 + 来源（db/env）+ 类型 + 说明 + 是否需重启。"""
    return config_store.snapshot()


def schema() -> list[dict[str, Any]]:
    """配置项元数据，供前端渲染表单。"""
    return [
        {
            "key": item.key,
            "section": item.section,
            "attr": item.attr,
            "env": item.env,
            "type": item.value_type,
            "description": item.description,
            "choices": list(item.choices),
            "minimum": item.minimum,
            "maximum": item.maximum,
            "hot": item.hot,
            "restart_required": item.restart_required,
        }
        for item in ITEMS
    ]


def update(session: Session, values: dict[str, Any], *, actor: str) -> dict[str, Any]:
    """批量写入配置。

    先整批校验再落库：任一项非法就抛 ConfigError，一项都不写（调用方回 400）。
    返回改动的键与"哪些要重启才生效"。
    """
    if not values:
        raise ConfigError("没有要写入的配置项")

    prepared: list[tuple[str, str]] = []
    for key, raw in values.items():
        item = item_by_key(key)
        if item is None:
            raise ConfigError(f"未登记的配置项：{key}")
        try:
            typed = coerce(item, raw)
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
        prepared.append((item.key, render(item, typed)))

    changed: list[str] = []
    restart_required: list[str] = []
    for key, text in prepared:
        before = config_store.get_raw(key)
        config_store.set(session, key, text, actor=actor)
        after = config_store.get_raw(key)
        if before != after:
            changed.append(key)
        item = item_by_key(key)
        if item is not None and item.restart_required:
            restart_required.append(key)
    return {"changed": changed, "restart_required": restart_required}


def source_summary() -> str:
    """配置来源概览：db / env / mixed。"""
    return config_store.source_summary()


def db_ok() -> bool:
    """配置库是否可用（最近一次读取没失败）。"""
    return config_store.db_ok  
