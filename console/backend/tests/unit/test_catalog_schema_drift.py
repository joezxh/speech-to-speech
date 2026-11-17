"""参数目录 ↔ 配置项登记表的一致性守卫（spec 2026-11-17 §4.1）。

登记表（`app/config/_schema.py`）是从参数目录的 `console_parameters` 段**派生**的，
所以仓库里不该存在第二份键清单。真出现漂移，要么是派生逻辑坏了，要么是有人手改了
登记表——两种都要在这里钉住：

- 目录加了项、登记表没跟上（= 有人手改登记表）；
- 登记表多了项、目录没有（= 派生时漏了，或手写了清单）；
- 类型、取值域、env 名与 settings 字段对不上；
- 控制台自己的条目漏进了 pipeline 参数树（部署页会被污染）。
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml

from app.config import _schema
from app.services import catalog_service

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent.parent
CATALOG = REPO / "docs" / "parameter-catalog.yaml"

# 校验脚本住在 scripts/ 下，不是一个包；按路径导入它，好让测试与 CI 用同一套判定。
sys.path.insert(0, str(BACKEND / "scripts"))

import validate_catalog_schema as validator  # noqa: E402

CONSOLE_STAGES = {"app", "console", "allocator", "demo", "bootstrap"}


@pytest.fixture(scope="module")
def entries() -> list[dict]:
    return validator.load_entries(CATALOG)


def _find(entries: list[dict], stage: str, name: str) -> dict:
    for entry in entries:
        if entry.get("stage") == stage and entry.get("name") == name:
            return entry
    raise AssertionError(f"目录里没有 {stage}.{name}")


def test_the_registry_is_derived_from_the_repository_catalog(entries):
    assert _schema.CATALOG_PATH is not None
    assert Path(_schema.CATALOG_PATH).resolve() == CATALOG.resolve()
    assert _schema.CATALOG_OK is True
    assert {item.key for item in _schema.ITEMS} == {
        f"{entry['stage']}.{entry['name']}" for entry in entries
    }


def test_the_catalog_and_the_registry_agree(entries):
    assert validator.check_consistency(entries, _schema.ITEMS) == []


def test_the_gate_passes_on_the_repository_catalog(monkeypatch):
    # validator.main() 直接 parse_args()：pytest 的 -q 会被误当脚本参数，
    # 注入脚本自己的 argv 才能测到“仓库目录跑校验脚本”的真实行为。
    monkeypatch.setattr(sys, "argv", [str(BACKEND / "scripts" / "validate_catalog_schema.py")])
    assert validator.main() == 0


def test_a_catalog_entry_without_a_registry_item_fails(entries):
    broken = copy.deepcopy(entries)
    broken.append(
        {
            "stage": "console",
            "name": "ghost",
            "type": "string",
            "env": "CONSOLE_GHOST",
            "choices": [],
            "effect": "hot",
            "what": "只存在于目录里的幽灵项",
            "source_ref": "console/backend/app/config/_console.py:ConsoleSettings.ghost",
        }
    )
    errors = validator.check_consistency(broken, _schema.ITEMS)
    assert any("console.ghost" in error and "登记表没有" in error for error in errors)


def test_a_registry_item_without_a_catalog_entry_fails(entries):
    errors = validator.check_consistency(entries[:-1], _schema.ITEMS)
    assert any("目录里没有" in error for error in errors)


def test_a_type_that_contradicts_the_settings_fails(entries):
    broken = copy.deepcopy(entries)
    _find(broken, "console", "lb_mode")["type"] = "integer"
    errors = validator.check_consistency(broken, _schema.ITEMS)
    assert any("console.lb_mode" in error for error in errors)


def test_choices_that_cannot_be_parsed_as_the_type_fail(entries):
    broken = copy.deepcopy(entries)
    _find(broken, "allocator", "probe_interval_s")["choices"] = ["often"]
    errors = validator.check_consistency(broken, _schema.ITEMS)
    assert any("allocator.probe_interval_s" in error for error in errors)


def test_an_env_name_the_settings_do_not_read_fails(entries):
    broken = copy.deepcopy(entries)
    _find(broken, "allocator", "probe_interval_s")["env"] = "PROBE_INTERVAL"
    errors = validator.check_consistency(broken, _schema.ITEMS)
    assert any("INSTANCE_PROBE_INTERVAL_S" in error for error in errors)


def test_console_entries_do_not_leak_into_the_pipeline_catalog(entries):
    document = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    assert document["console_parameters"]
    assert all(entry["stage"] not in CONSOLE_STAGES for entry in document["parameters"])

    loaded = catalog_service.load(CATALOG)
    assert loaded.available is True
    assert not any(entry.stage in CONSOLE_STAGES for entry in loaded.entries)
