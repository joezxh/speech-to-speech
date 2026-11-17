"""校验 scenarios.yaml 与 parameter-catalog.yaml 一致（CI 闸，Task 19）。

失败即非零退出：场景键必须存在、choices 值合法、引用键必须有 product_baseline、
五个说明字段必须有 en/zh 双语。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent.parent
CATALOG = REPO / "docs" / "parameter-catalog.yaml"
SCENARIOS = REPO / "docs" / "scenarios.yaml"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services import catalog_service  # noqa: E402


def validate(catalog_path: Path, scenarios_path: Path) -> list[str]:
    errors: list[str] = []
    catalog = catalog_service.load(catalog_path)
    if not catalog.available:
        return [f"参数目录不可用：{catalog.hint}"]
    index = catalog.by_key()
    document = yaml.safe_load(scenarios_path.read_text(encoding="utf-8"))
    scenarios = document.get("scenarios") if isinstance(document, dict) else None
    if not isinstance(scenarios, dict):
        return ["scenarios.yaml 缺 scenarios 映射"]
    expected = {"latency", "slow", "edge", "mix"}
    if set(scenarios) != expected:
        errors.append(f"场景名应为 {sorted(expected)}，实际 {sorted(scenarios)}")
    for name, scenario in scenarios.items():
        if not isinstance(scenario, dict):
            errors.append(f"{name}: 场景不是映射")
            continue
        for field in ("note", "why", "gain", "cost", "risk"):
            value = scenario.get(field)
            if not isinstance(value, dict) or set(value) != {"en", "zh"}:
                errors.append(f"{name}.{field}: 缺 en/zh 双语")
        for patch in scenario.get("patches") or []:
            key = patch.get("key")
            entry = index.get(key)
            if entry is None:
                errors.append(f"{name}: 键 {key} 不在参数目录")
                continue
            if entry.choices and str(patch.get("value")) not in entry.choices:
                errors.append(f"{name}: {key}={patch.get('value')} 不在 choices")
            if entry.product_baseline is None:
                errors.append(f"{name}: {key} 缺 product_baseline (N4)")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--scenarios", type=Path, default=SCENARIOS)
    args = parser.parse_args(argv)
    errors = validate(args.catalog, args.scenarios)
    if errors:
        print(f"scenarios.yaml 校验失败（{len(errors)} 处）：")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("scenarios.yaml 校验通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
