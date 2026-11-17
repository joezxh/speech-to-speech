"""从仓库 compose 文件生成 agent 可读的部署参数声明清单。

voiceprint/thirdparty 等形态不挂载 config 目录，agent 运行时读不到 compose 文件；
这里在构建期把参数全集固化成 JSON 随镜像投递，标记为 declared，绝不冒充运行时真值。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SECRET = re.compile(r"key|token|secret|password|credential", re.I)
MANIFEST = ROOT / "config" / "deployment-manifest.json"


def _env(node) -> dict[str, str]:
    if isinstance(node, dict):
        return {str(k): str(v) for k, v in node.items()}
    if isinstance(node, list):
        result: dict[str, str] = {}
        for item in node:
            if isinstance(item, str) and "=" in item:
                key, value = item.split("=", 1)
                result[key] = value
        return result
    return {}


def build() -> dict:
    services: dict[str, dict] = {}
    files = sorted(ROOT.glob("docker-compose*.yml")) + sorted(
        (ROOT / "docs" / "hardware").glob("docker-compose*.yml")
    )
    for path in files:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for name, raw in (payload.get("services") or {}).items():
            if not isinstance(raw, dict):
                continue
            command = raw.get("command")
            services[f"{path.name}:{name}"] = {
                "compose": path.name,
                "service": name,
                "image": raw.get("image", ""),
                "command": command if isinstance(command, list) else (
                    command.split() if isinstance(command, str) else []
                ),
                "env": {
                    key: ("***" if SECRET.search(key) else value)
                    for key, value in _env(raw.get("environment")).items()
                },
                "envFile": raw.get("env_file", ""),
                "ports": raw.get("ports", []),
                "volumes": raw.get("volumes", []),
                "deviceIds": (raw.get("gpus") or {}).get("device_ids", []),
            }
    return {"schemaVersion": 1, "source": "repository compose files", "services": services}


def main() -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(build(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {MANIFEST.relative_to(ROOT)} ({len(build()['services'])} services)")


if __name__ == "__main__":
    main()
