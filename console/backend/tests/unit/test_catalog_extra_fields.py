"""Task 19：参数目录四字段（what/scope/product_baseline/anchor）+ scenarios.yaml
+ 两道 CI 校验闸（schema 双向一致、场景键与建议值合法）。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from app.services import catalog_service

REPO = Path(__file__).resolve().parents[4]
CATALOG = REPO / "docs" / "parameter-catalog.yaml"
SCENARIOS = REPO / "docs" / "scenarios.yaml"
SCRIPTS = REPO / "console" / "backend" / "scripts"


def _real_catalog():
    return catalog_service.load(CATALOG)


def test_real_catalog_exposes_four_new_fields():
    catalog = _real_catalog()
    assert catalog.available
    extras = [entry for entry in catalog.entries if entry.what and entry.scope and entry.anchor]
    assert len(extras) > 0, "至少有条目带 what/scope/anchor 草稿字段"
    assert any(entry.product_baseline is not None for entry in catalog.entries), "存在产品基线值"

    entry = next(item for item in catalog.entries if item.what)
    payload = entry.as_json()
    for key in ("what", "scope", "product_baseline", "anchor"):
        assert key in payload


def test_exposure_ops_count_is_still_52():
    catalog = _real_catalog()
    assert len([e for e in catalog.entries if e.exposure == "ops"]) == 52


def test_scenarios_reference_existing_keys_and_valid_choices():
    scenarios = yaml.safe_load(SCENARIOS.read_text(encoding="utf-8"))
    catalog = _real_catalog()
    index = catalog.by_key()
    assert set(scenarios["scenarios"]) == {"latency", "slow", "edge", "mix"}
    for name, scenario in scenarios["scenarios"].items():
        for patch in scenario["patches"]:
            key = patch["key"]
            assert key in index, f"{name}: {key} 不在目录"
            entry = index[key]
            if entry.choices:
                assert str(patch["value"]) in entry.choices, f"{name}: {key}={patch['value']} 不在 choices"
            for field in ("note", "why", "gain", "cost", "risk"):
                assert set(scenario[field]) == {"en", "zh"}, f"{name}.{field} 缺双语"
            assert index[key].product_baseline is not None, f"{name}: {key} 缺 product_baseline (N4)"


def test_validate_scripts_pass_on_real_files():
    for name in ("validate_catalog_schema.py", "validate_scenarios.py"):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / name)],
            capture_output=True, text=True, cwd=str(REPO), check=False,
        )
        assert result.returncode == 0, f"{name}: {result.stderr[-500:]}"


def test_validate_catalog_schema_fails_on_injected_inconsistency(tmp_path):
    document = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    # 人为删掉一个参数的字段 → schema 不一致必须非零退出。
    document["console_parameters"][0].pop("type", None)
    fake = tmp_path / "bad-catalog.yaml"
    fake.write_text(yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "validate_catalog_schema.py"), "--catalog", str(fake)],
        capture_output=True, text=True, cwd=str(REPO), check=False,
    )
    assert result.returncode != 0
