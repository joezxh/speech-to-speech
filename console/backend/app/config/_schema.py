"""配置项登记表（spec 2026-11-17 §4.1）。

**登记表从参数目录派生。** `docs/parameter-catalog.yaml` 的 `console_parameters`
段是键集合、类型、取值域与说明的唯一真源；本模块只做"目录条目 → ConfigItem"的
翻译，不再手写第二份键清单。两边漂移由
`console/backend/scripts/validate_catalog_schema.py` 在 CI 里挡住（双向一致：
目录有而登记表没有、登记表有而目录没有，都算失败）。

**只有登记在册的键能进 `param_config` 表。** 这张表是白名单，不是任意键值袋：
控制台自己的配置面（探针节奏、LB 开关、路径、上限……）都能在线改，但密钥不进表
（JWT、口令、S2S token 仍只走 env，见设计 §5.2）。

目录文件找不到或解析失败时，登记表为空：所有开关退回环境变量默认值，控制台照常
启动——配置面不可用不能让语音链路带崩（设计 §5.1 的降级矩阵）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

STR, INT, FLOAT, BOOL = "str", "int", "float", "bool"

# 目录里的 type 词汇 → 登记表的取值类型。
TYPE_BY_CATALOG_TYPE = {
    "string": STR,
    "integer": INT,
    "float": FLOAT,
    "boolean": BOOL,
}

# 目录里的 effect 词汇：startup = 改完要重启控制台才生效。
EFFECT_STARTUP = "startup"


@dataclass(frozen=True)
class ConfigItem:
    """一个可在线修改的配置项。"""

    section: str
    attr: str
    env: str
    value_type: str
    description: str
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    # 启动期语义（是否起巡检任务、是否注册路由、是否播种）改完要重启控制台。
    restart_required: bool = False

    @property
    def key(self) -> str:
        return f"{self.section}.{self.attr}"

    @property
    def hot(self) -> bool:
        """不重启控制台也能生效。"""
        return not self.restart_required


def catalog_path() -> Path | None:
    """目录文件的位置：env → 仓库 `docs/` → 容器挂载点。

    刻意不读配置表里的 `console.param_catalog_path`：登记表是配置面自己的地基，
    不能依赖它自己配置出来的值。
    """
    explicit = os.environ.get("PARAM_CATALOG_PATH", "").strip()
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    for parent in Path(__file__).resolve().parents:
        candidates.append(parent / "docs" / "parameter-catalog.yaml")
    candidates.append(Path("/app/catalog/parameter-catalog.yaml"))
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:  # 路径不可达（权限/挂载问题）就当它不存在
            continue
    return None


def _number(value: Any) -> float | int | None:
    """目录里的 minimum/maximum：整数保持整数，其余按浮点。"""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("minimum/maximum 不能是布尔值")
    if isinstance(value, int):
        return value
    return float(value)


def _item_from_entry(entry: dict[str, Any]) -> ConfigItem:
    """把一条目录条目翻译成登记项；字段不合法就抛 ValueError。"""
    stage = str(entry.get("stage") or "").strip()
    name = str(entry.get("name") or "").strip()
    if not stage or not name:
        raise ValueError("条目缺少 stage 或 name")

    catalog_type = str(entry.get("type") or "").strip()
    value_type = TYPE_BY_CATALOG_TYPE.get(catalog_type)
    if value_type is None:
        raise ValueError(f"{stage}.{name} 的 type {catalog_type!r} 不在 {sorted(TYPE_BY_CATALOG_TYPE)} 里")

    env = str(entry.get("env") or "").strip()
    if not env:
        raise ValueError(f"{stage}.{name} 缺少 env 名（播种与兜底都靠它）")

    effect = str(entry.get("effect") or "hot").strip()
    return ConfigItem(
        section=stage,
        attr=name,
        env=env,
        value_type=value_type,
        description=str(entry.get("what") or "").strip(),
        choices=tuple(str(choice) for choice in (entry.get("choices") or ())),
        minimum=_number(entry.get("minimum")),
        maximum=_number(entry.get("maximum")),
        restart_required=effect == EFFECT_STARTUP,
    )


def _entries(path: Path) -> list[dict[str, Any]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path.name} 顶层不是映射")
    raw = document.get("console_parameters") or []
    if not isinstance(raw, list):
        raise ValueError(f"{path.name} 的 console_parameters 不是列表")
    return [row for row in raw if isinstance(row, dict)]


def _load_items(path: Path) -> tuple[ConfigItem, ...]:
    items: list[ConfigItem] = []
    for entry in _entries(path):
        try:
            items.append(_item_from_entry(entry))
        except ValueError as exc:
            # 一条坏条目不该拖垮整个控制台：跳过它，其余照常。
            logger.error(f"参数目录条目无法登记，已跳过：{exc}")
    return tuple(sorted(items, key=lambda item: (item.section, item.attr)))


CATALOG_PATH = catalog_path()

if CATALOG_PATH is None:
    ITEMS: tuple[ConfigItem, ...] = ()
    CATALOG_OK = False
    logger.warning("参数目录不可用：控制台配置登记表为空，所有开关退回环境变量默认值")
else:
    try:
        ITEMS = _load_items(CATALOG_PATH)
        CATALOG_OK = bool(ITEMS)
        if not CATALOG_OK:
            logger.warning(f"参数目录 {CATALOG_PATH} 里没有 console_parameters，配置登记表为空")
    except (OSError, yaml.YAMLError, ValueError) as exc:
        ITEMS = ()
        CATALOG_OK = False
        logger.error(f"参数目录 {CATALOG_PATH} 解析失败，配置登记表为空：{exc}")

_BY_KEY = {item.key: item for item in ITEMS}
_BY_SECTION_ATTR = {(item.section, item.attr): item for item in ITEMS}


def item_by_key(key: str) -> ConfigItem | None:
    """按 `section.attr` 取登记项；未登记返回 None（不允许进表）。"""
    return _BY_KEY.get(key)


def item_for(section: str, attr: str) -> ConfigItem | None:
    """按分区与属性名取登记项。"""
    return _BY_SECTION_ATTR.get((section, attr))


def items_for_section(section: str) -> list[ConfigItem]:
    return [item for item in ITEMS if item.section == section]


def _choice_text(item: ConfigItem, value: Any) -> str:
    """取值的字符串形态，用来和取值域比对。"""
    if item.value_type == BOOL:
        return "true" if value else "false"
    return str(value)


def coerce(item: ConfigItem, raw: str):
    """把库里的字符串按登记类型转成 Python 值，并校验取值域。

    非法值抛 ValueError——写 API 据此回 400，且整批不落库。
    """
    text = ("" if raw is None else str(raw)).strip()
    value: Any
    if item.value_type == BOOL:
        low = text.lower()
        if low in ("1", "true", "yes", "on"):
            value = True
        elif low in ("0", "false", "no", "off", ""):
            value = False
        else:
            raise ValueError(f"{item.key} 期望布尔值，收到 {raw!r}")
    elif item.value_type in (INT, FLOAT):
        try:
            value = int(text) if item.value_type == INT else float(text)
        except ValueError as exc:
            raise ValueError(f"{item.key} 期望 {item.value_type}，收到 {raw!r}") from exc
        if item.minimum is not None and value < item.minimum:
            raise ValueError(f"{item.key} 不得小于 {item.minimum}")
        if item.maximum is not None and value > item.maximum:
            raise ValueError(f"{item.key} 不得大于 {item.maximum}")
    else:
        value = text

    if item.choices and _choice_text(item, value) not in item.choices:
        raise ValueError(f"{item.key} 只能是 {', '.join(item.choices)} 之一，收到 {raw!r}")
    return value


def render(item: ConfigItem, value) -> str:
    """把 Python 值转成入库用的字符串。"""
    if item.value_type == BOOL:
        return "true" if value else "false"
    return str(value)
