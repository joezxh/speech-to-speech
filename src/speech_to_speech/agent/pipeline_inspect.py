"""从本机生效配置提取 pipeline 部署模型与全部参数，并实测 GPU 显存。

真源：target_yaml（console 渲染后落地的 prod.yaml）+ supervisor PID +
nvidia-smi。密钥类参数一律掩码，缺失配置返回空而不是编造。
"""

from __future__ import annotations

import http.client
import os
import re
import socket
import subprocess
import xmlrpc.client
from pathlib import Path
from typing import Any

SECRET_KEY = re.compile(r"key|token|secret|password|credential", re.I)
MODEL_KEYS = ("model_name", "model_path", "model")


def _resolve(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"env"}:
        return os.environ.get(str(value["env"]), "")
    if isinstance(value, (dict, list)):
        return {k: _resolve(v) for k, v in value.items()} if isinstance(value, dict) else [_resolve(v) for v in value]
    return value


def _flatten(node: Any, prefix: str, out: dict[str, Any]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            _flatten(value, f"{prefix}.{key}" if prefix else str(key), out)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _flatten(value, f"{prefix}[{index}]", out)
    elif node is not None:
        out[prefix] = "***" if SECRET_KEY.search(prefix.split(".")[-1]) else (
            str(node).lower() if isinstance(node, bool) else node
        )


def _model_of(block: dict) -> str:
    settings = block.get("settings") or {}
    if not isinstance(settings, dict):
        return ""
    for key in MODEL_KEYS:
        for name, value in settings.items():
            if name.endswith(key) and _resolve(value):
                return str(_resolve(value))
    return ""


def collect_pipeline_deployment(settings: Any) -> dict:
    """返回 {models: {block: model}, params: {flat_key: value}, vram_gb: float|None}。"""
    result: dict = {"models": {}, "params": {}, "vram_gb": None}
    path = Path(getattr(settings, "target_yaml", "") or "")
    if not path.is_file():
        return result
    try:
        import yaml  # noqa: PLC0415 - pipeline 镜像自带

        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - 配置坏/读到一半都不阻塞心跳
        return result
    if not isinstance(payload, dict):
        return result

    resolved = _resolve(payload)
    blocks = resolved.get("blocks") or {}
    flat: dict[str, Any] = {}
    for name, block in blocks.items() if isinstance(blocks, dict) else []:
        if not isinstance(block, dict):
            continue
        model = _model_of(block)
        if model:
            result["models"][str(name)] = model
        if block.get("backend"):
            flat[f"{name}.backend"] = block["backend"]
        _flatten(block.get("settings") or {}, str(name), flat)
    _flatten(resolved.get("pipelines") or {}, "pipelines", flat)
    _flatten(resolved.get("runtime") or {}, "runtime", flat)
    result["params"] = flat
    result["vram_gb"] = _nvidia_smi_vram()
    return result


def _supervisor_pid() -> int | None:
    settings_socket = os.environ.get(
        "S2S_AGENT_SUPERVISOR_SOCKET", "/run/s2s-console/supervisor.sock"
    )
    program = os.environ.get("S2S_AGENT_SUPERVISOR_PROGRAM", "pipeline")
    if not os.path.exists(settings_socket):
        return None

    class _Connection(http.client.HTTPConnection):
        def __init__(self) -> None:
            super().__init__("localhost", timeout=3.0)

        def connect(self) -> None:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect(settings_socket)
            self.sock = sock

    class _Transport(xmlrpc.client.Transport):
        def make_connection(self, host):  # noqa: ANN001,ANN202
            return _Connection()

    try:
        proxy = xmlrpc.client.ServerProxy(
            "http://localhost", transport=_Transport(), allow_none=True
        )
        info = proxy.supervisor.getProcessInfo(program)
        pid = int(info.get("pid") or 0)
        return pid or None
    except Exception:  # noqa: BLE001 - supervisor 不可达就没有显存真源
        return None


def _nvidia_smi_vram() -> float | None:
    """pipeline 进程实际占用显存（GiB）；nvidia-smi 不可用时 None。"""
    pid = _supervisor_pid()
    if pid is None:
        return None
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,used_gpu_memory",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in proc.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2 or not parts[0].isdigit() or int(parts[0]) != pid:
            continue
        match = re.search(r"\d+(?:\.\d+)?", parts[1])
        if match:
            return round(float(match.group()) / 1024, 2)
    return None


SERVICE_BLOCK = {
    "asr": "stt",
    "stt": "stt",
    "llm": "llm",
    "tts": "tts",
    "vad": "vad",
}


def enrich_workload(row: dict, snapshot: dict) -> dict:
    """声明式服务行补对应 block 的模型与参数；pipeline 行承载全量与实测显存。"""
    block = SERVICE_BLOCK.get(str(row.get("kind") or ""))
    if block:
        if not row.get("model"):
            row["model"] = snapshot["models"].get(block, "")[:128]
        row["params"] = {
            key.split(".", 1)[1]: value
            for key, value in snapshot["params"].items()
            if key.startswith(f"{block}.")
        }
    if row.get("kind") == "pipeline":
        row["model"] = " · ".join(snapshot["models"].values())[:128]
        row["vram_gb"] = snapshot["vram_gb"]
        row["params"] = {**snapshot["params"], "models": snapshot["models"]}
    return row
