"""校验参数目录与控制台配置项登记表一致（CI 闸，spec 2026-11-17 §4.1）。

参数目录 `docs/parameter-catalog.yaml` 的 `console_parameters` 段是控制台配置项
的**唯一真源**：`console/backend/app/config/_schema.py` 的登记表从它派生。本脚本
站在目录这一侧，把两份东西对着看，任何漂移都算失败：

1. **键集合双向一致**：目录有而登记表没有、登记表有而目录没有，都算失败；
2. **取值域与类型相容**：`choices` 里的每个值都能按该条的 `type` 解析；
3. **env 名对得上 settings**：`env` 必须是 `pydantic-settings` 字段真实读的那个
   变量名（`validation_alias`，没有就用字段名大写），否则播种与兜底都读不到；
4. **默认值落在取值域内**：settings 的默认值必须满足 `choices` 与
   `minimum`/`maximum`，否则"库里没值 → 回退 env"这条退路会拿到非法值。

用法（从 `console/backend`）：

    python scripts/validate_catalog_schema.py

不通过时打印全部问题并以非零码退出。
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any, get_args, get_origin

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent.parent
CATALOG = REPO / "docs" / "parameter-catalog.yaml"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# `app.config` 没有 JWT 密钥就拒绝导入；这里只是读元数据，不需要真密钥。
os.environ.setdefault("JWT_SECRET_KEY", "catalog-schema-validator-placeholder-32b")

import yaml  # noqa: E402

from app.config import _schema  # noqa: E402

BOOL_TRUE = ("1", "true", "yes", "on")
BOOL_FALSE = ("0", "false", "no", "off", "")


def load_entries(path: Path) -> list[dict[str, Any]]:
    """读目录文件里的 `console_parameters` 段。"""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path.name} 顶层不是映射")
    raw = document.get("console_parameters")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{path.name} 的 console_parameters 不是列表")
    return [row for row in raw if isinstance(row, dict)]


def _key(entry: dict[str, Any]) -> str:
    return f"{entry.get('stage')}.{entry.get('name')}"


def _choice_compatible(value_type: str, choice: Any) -> bool:
    """取值域里的每个值都要能被该类型解析。"""
    text = str(choice).strip()
    if value_type == _schema.BOOL:
        return text.lower() in BOOL_TRUE or text.lower() in BOOL_FALSE
    if value_type == _schema.INT:
        try:
            int(text)
        except ValueError:
            return False
        return True
    if value_type == _schema.FLOAT:
        try:
            float(text)
        except ValueError:
            return False
        return True
    return True


def _settings_field(entry: dict[str, Any]):
    """按 `source_ref` 找到 settings 类与字段（`…_app.py:AppSettings.env`）。"""
    source_ref = str(entry.get("source_ref") or "")
    if ":" not in source_ref:
        return None, None, None, "source_ref 缺少 `文件:类.字段` 形态"
    file_part, target = source_ref.split(":", 1)
    if "." not in target:
        return None, None, None, "source_ref 缺少字段名"
    class_name, attr = target.rsplit(".", 1)
    module_name = f"app.config.{Path(file_part).stem}"
    try:
        module = importlib.import_module(module_name)
        settings_cls = getattr(module, class_name)
    except (ImportError, AttributeError) as exc:
        return None, None, None, f"source_ref 指向的 {class_name} 找不到：{exc}"
    fields = getattr(settings_cls, "model_fields", {})
    field = fields.get(attr)
    if field is None:
        return None, None, None, f"{class_name} 没有字段 {attr}"
    return settings_cls, field, attr, None


def _expected_env(field) -> str:
    """pydantic-settings 真正读的环境变量名。"""
    alias = getattr(field, "validation_alias", None) or getattr(field, "alias", None)
    if isinstance(alias, str):
        return alias
    return str(field.alias or "").upper() or ""


def _expected_type(field) -> tuple[str, tuple[str, ...]]:
    """字段的类型 → (登记类型, Literal 的取值)。"""
    annotation = field.annotation
    if get_origin(annotation) is not None and str(get_origin(annotation)).endswith("Literal"):
        values = tuple(str(value) for value in get_args(annotation))
        return _schema.STR, values
    text = str(annotation)
    if "bool" in text:
        return _schema.BOOL, ()
    if "int" in text and "float" not in text:
        return _schema.INT, ()
    if "float" in text:
        return _schema.FLOAT, ()
    return _schema.STR, ()


def check_entry(entry: dict[str, Any], item) -> list[str]:
    """逐条校验目录条目本身，以及它与 settings 字段的关系。"""
    key = _key(entry)
    errors: list[str] = []

    catalog_type = str(entry.get("type") or "").strip()
    value_type = _schema.TYPE_BY_CATALOG_TYPE.get(catalog_type)
    if value_type is None:
        errors.append(f"{key}: type {catalog_type!r} 不在 {sorted(_schema.TYPE_BY_CATALOG_TYPE)} 里")
        return errors
    if value_type != item.value_type:
        errors.append(f"{key}: 登记类型 {item.value_type!r} 与目录 type {catalog_type!r} 不一致")

    if not str(entry.get("what") or "").strip():
        errors.append(f"{key}: 缺少 what（配置页与审计都靠它说明这项是什么）")

    choices = [str(choice) for choice in (entry.get("choices") or ())]
    for choice in choices:
        if not _choice_compatible(value_type, choice):
            errors.append(f"{key}: 取值 {choice!r} 与 type {catalog_type!r} 不相容")

    settings_cls, field, attr, ref_error = _settings_field(entry)
    if ref_error:
        errors.append(f"{key}: {ref_error}")
        return errors

    expected_env = _expected_env(field)
    entry_env = str(entry.get("env") or "").strip()
    if expected_env and entry_env != expected_env:
        errors.append(f"{key}: env 是 {entry_env!r}，但 settings 读的是 {expected_env!r}")
    if item.env != entry_env:
        errors.append(f"{key}: 登记表的 env {item.env!r} 与目录的 {entry_env!r} 不一致")

    expected_type, literal_values = _expected_type(field)
    if expected_type != value_type:
        errors.append(f"{key}: 目录 type {catalog_type!r} 与 settings 字段类型 {expected_type!r} 不一致")
    if literal_values and set(literal_values) != set(choices):
        errors.append(f"{key}: choices {choices} 与 Literal{literal_values} 不一致")

    default = field.get_default(call_default_factory=True)
    if default is not None:
        try:
            _schema.coerce(item, str(default))
        except ValueError as exc:
            errors.append(f"{key}: settings 默认值 {default!r} 不在取值域内（{exc}）")
    return errors


def check_consistency(entries: list[dict[str, Any]], items) -> list[str]:
    """目录 ↔ 登记表的双向一致性检查。"""
    errors: list[str] = []

    catalog_keys = [_key(entry) for entry in entries]
    duplicates = sorted({key for key in catalog_keys if catalog_keys.count(key) > 1})
    if duplicates:
        errors.append(f"目录里有重复的键：{duplicates}")

    schema_keys = [item.key for item in items]
    only_catalog = sorted(set(catalog_keys) - set(schema_keys))
    only_schema = sorted(set(schema_keys) - set(catalog_keys))
    if only_catalog:
        errors.append(f"目录里有、登记表没有：{only_catalog}")
    if only_schema:
        errors.append(f"登记表里有、目录里没有：{only_schema}")

    env_owner: dict[str, str] = {}
    for entry in entries:
        env = str(entry.get("env") or "").strip()
        if not env:
            errors.append(f"{_key(entry)}: 缺少 env 名（播种与兜底都靠它）")
        elif env in env_owner:
            errors.append(f"{_key(entry)}: env {env} 与 {env_owner[env]} 撞名")
        else:
            env_owner[env] = _key(entry)

    by_key = {item.key: item for item in items}
    for entry in entries:
        item = by_key.get(_key(entry))
        if item is None:
            continue
        errors.extend(check_entry(entry, item))
    return errors


def main() -> int:
    if not CATALOG.is_file():
        print(f"找不到参数目录：{CATALOG}")
        return 1

    derived = getattr(_schema, "CATALOG_PATH", None)
    if derived is None or Path(derived).resolve() != CATALOG.resolve():
        print(f"控制台登记表派生自 {derived}，不是仓库里的 {CATALOG}")
        return 1

    try:
        entries = load_entries(CATALOG)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        print(f"参数目录解析失败：{exc}")
        return 1

    errors = check_consistency(entries, _schema.ITEMS)
    if errors:
        print(f"参数目录与配置项登记表不一致（{len(errors)} 处）：")
        for error in errors:
            print(f"  - {error}")
        return 1

    print(f"参数目录与配置项登记表一致：{len(_schema.ITEMS)} 个配置项（{len(entries)} 条目录条目）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
