"""从本机生效配置提取 pipeline 部署模型与全部参数，并实测 GPU 显存。

真源：target_yaml（console 渲染后落地的 prod.yaml）+ supervisor PID +
nvidia-smi。密钥类参数一律掩码，缺失配置返回空而不是编造。
"""

from __future__ import annotations

import http.client
import json
import os
import re
import socket
import subprocess
import xmlrpc.client
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

SECRET_KEY = re.compile(r"key|token|secret|password|credential", re.I)
LOG_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?key|secret|token|password)(\s*[:=]\s*)\S+"
)
SK_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{6,}")
MODEL_KEYS = ("model_name", "model_path", "model")


def package_version() -> str:
    """本机安装的 speech-to-speech 版本；读不到就是空，不用硬编码兜底。"""
    try:
        return metadata.version("speech-to-speech")
    except metadata.PackageNotFoundError:
        return ""


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


def collect_pipeline_deployment(settings: Any, *, probe_vram: bool = True, vram_gb: float | None = None) -> dict:
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
    result["vram_gb"] = vram_gb if vram_gb is not None else (_nvidia_smi_vram() if probe_vram else None)
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


def _cpu_mem() -> dict:
    """CPU/内存采样；psutil 缺失时返回空字典，由调用方置 None。"""
    try:
        import psutil  # noqa: PLC0415 - 可选依赖，agent 镜像内有
    except ImportError:
        return {}
    memory = psutil.virtual_memory()
    gib = 1024 ** 3
    return {
        "cpu_pct": round(float(psutil.cpu_percent(interval=None)), 1),
        "load_avg": [round(float(v), 2) for v in os.getloadavg()] if hasattr(os, "getloadavg") else [],
        "mem_total_gb": round(memory.total / gib, 2),
        "mem_used_gb": round(memory.used / gib, 2),
        "mem_pct": round(float(memory.percent), 1),
    }


def _numeric(text: str) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", text)
    return float(match.group()) if match else None


def collect_node_metrics() -> dict:
    """节点 CPU/GPU/MEM 与 pipeline 进程显存；一次 GPU 查询，失败字段为 None。"""
    result: dict = {
        "cpu_pct": None, "load_avg": [], "mem_total_gb": None, "mem_used_gb": None,
        "mem_pct": None, "gpu_name": None, "gpu_util_pct": None,
        "gpu_mem_used_gb": None, "gpu_mem_total_gb": None, "pipeline_vram_gb": None,
        "collected_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    result.update(_cpu_mem())
    pid = _supervisor_pid()
    try:
        gpus = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,uuid,name,utilization.gpu,memory.total,memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, timeout=3.0, check=False,
        )
        # 没有 supervisor PID（本地 PyCharm 形态）仍取整机 GPU 指标；
        # 只有进程级显存需要 PID，拿不到就保持 None，不猜。
        apps = (
            subprocess.run(
                [
                    "nvidia-smi",
                    "--query-compute-apps=pid,gpu_uuid,used_gpu_memory",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True, text=True, timeout=3.0, check=False,
            )
            if pid is not None
            else None
        )
    except (OSError, subprocess.SubprocessError):
        return result
    uuid: str | None = None
    if apps is not None:
        for line in apps.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if parts and parts[0].isdigit() and int(parts[0]) == pid:
                if len(parts) >= 3:
                    uuid = parts[1]
                    result["pipeline_vram_gb"] = round((_numeric(parts[2]) or 0) / 1024, 2)
                elif len(parts) >= 2:
                    result["pipeline_vram_gb"] = round((_numeric(parts[1]) or 0) / 1024, 2)
                break
    selected = None
    for line in gpus.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if uuid and len(parts) >= 6 and parts[1] == uuid:
            selected = parts
            break
        if selected is None:
            selected = parts
    if not selected:
        return result
    if len(selected) >= 6:
        name, util, total, used = selected[2], selected[3], selected[4], selected[5]
    elif len(selected) >= 5:
        name, util, total, used = selected[1], selected[2], selected[3], selected[4]
    else:
        return result
    result["gpu_name"] = name
    result["gpu_util_pct"] = int(_numeric(util) or 0)
    result["gpu_mem_total_gb"] = round((_numeric(total) or 0) / 1024, 2)
    result["gpu_mem_used_gb"] = round((_numeric(used) or 0) / 1024, 2)
    return result


def collect_deployment_params(settings: Any) -> dict:
    """运行时生效参数（YAML/supervisor）与仓库声明参数（compose manifest）分栏。"""
    runtime = collect_pipeline_deployment(settings, probe_vram=False)["params"]
    declared: dict[str, Any] = {}
    path = Path(getattr(settings, "deployment_manifest", "") or "")
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for name, service in (payload.get("services") or {}).items():
                prefix = f"{name}."
                declared[prefix + "compose"] = service.get("compose", "")
                declared[prefix + "image"] = service.get("image", "")
                if isinstance(service.get("command"), list):
                    declared[prefix + "command"] = " ".join(map(str, service["command"]))
                for key, value in (service.get("env") or {}).items():
                    declared[prefix + "env." + key] = (
                        "***" if SECRET_KEY.search(str(key)) else _resolve(value)
                    )
                for key in ("ports", "volumes", "deviceIds"):
                    if service.get(key) is not None:
                        declared[prefix + key] = service[key]
        except (OSError, ValueError, AttributeError, TypeError):
            declared = {}
    return {"runtime": runtime, "declared": declared}


def _redact_log(line: str) -> str:
    line = LOG_SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}***", line)
    return SK_KEY.sub("sk-***", line)


def collect_container_logs(settings: Any) -> list[dict]:
    """有界读取容器 pipeline 日志并脱敏；上报失败不能影响主循环。"""
    max_lines = int(getattr(settings, "container_log_max_lines", 500) or 500)
    max_bytes = 200 * 1024
    stdout = Path(getattr(settings, "pipeline_log", "") or "")
    stderr = Path(str(stdout).replace("stdout", "stderr"))
    rows: list[dict] = []
    for source, path in (("stdout", stdout), ("stderr", stderr)):
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:]
        except OSError:
            continue
        picked: list[str] = []
        size = 0
        for line in reversed(lines):
            size += len(line.encode("utf-8")) + 1
            if size > max_bytes:
                break
            picked.append(_redact_log(line))
        rows.append({"source": source, "lines": list(reversed(picked))})
    return rows
