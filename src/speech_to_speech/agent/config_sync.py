"""目标配置落地：拉取 → 原子替换 → 按 effect 分流 → 回报 → 确认（§5.3.6）。

effect 分流（生效方式取自本机声明 agent.yaml 的可选 `effects:` 映射，
缺省 container=只记声明，最安全）：
- hot → 调本机 pipeline 的 /internal/sessions/update（不中断语音）
- start → supervisor XML-RPC 重启 pipeline（中断语音，与 console 发布同代价）
- container → 只更新声明，运维按 compose 流程处理
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import tempfile
import xmlrpc.client
from pathlib import Path

from speech_to_speech.agent.client import AgentClient
from speech_to_speech.agent.settings import AgentSettings

CALL_TIMEOUT = 60.0


def declared_effects(settings: AgentSettings) -> dict[str, str]:
    """agent.yaml 的 `effects: {<param_key>: hot|start|container}`；缺文件返回空。"""
    declaration = Path(settings.declaration_file)
    if not declaration.is_file():
        return {}
    try:
        import yaml  # noqa: PLC0415 - pipeline 镜像自带

        payload = yaml.safe_load(declaration.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - 声明文件坏了就全按 container
        return {}
    effects = payload.get("effects") if isinstance(payload, dict) else None
    return dict(effects) if isinstance(effects, dict) else {}


def apply_text_atomically(target: str, text: str) -> None:
    """临时文件 + 原子替换：半写文件永远不会成为 pipeline 的启动配置。"""
    destination = Path(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=destination.parent, delete=False
    )
    try:
        with handle:
            handle.write(text)
        os.replace(handle.name, destination)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._path)
        self.sock = sock


def restart_pipeline(settings: AgentSettings) -> None:
    """supervisor XML-RPC 重启 pipeline——与 console restart_runner 同一套机制。"""
    path = settings.supervisor_socket
    if not os.path.exists(path):
        raise RuntimeError(f"supervisor socket {path} does not exist")

    class _Transport(xmlrpc.client.Transport):
        def make_connection(self, host):  # noqa: ANN001,ANN202
            return _UnixHTTPConnection(path, CALL_TIMEOUT)

    proxy = xmlrpc.client.ServerProxy(
        "http://localhost", transport=_Transport(), allow_none=True
    )
    proxy.supervisor.stopProgram(settings.supervisor_program)
    proxy.supervisor.startProgram(settings.supervisor_program, True)


def hot_update(settings: AgentSettings, values: dict) -> None:
    """hot 类参数逐项下发到本机 pipeline 的既有会话更新端点。"""
    connection = http.client.HTTPConnection("127.0.0.1", 8765, timeout=CALL_TIMEOUT)
    try:
        connection.request(
            "POST",
            "/internal/sessions/update",
            body=json.dumps({"values": values}),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        if response.status >= 400:
            raise RuntimeError(f"/internal/sessions/update returned {response.status}")
    finally:
        connection.close()


def sync_config(client: AgentClient, token: str, settings: AgentSettings) -> dict | None:
    """一轮配置同步。返回 ack 结果；任何失败由调用方（主循环）吞掉并退避。"""
    machine_id = settings.machine_id
    if not settings.target_yaml or not machine_id:
        return None

    if_none_match = ""
    marker = Path(settings.target_yaml + ".etag")
    if marker.is_file():
        if_none_match = marker.read_text(encoding="utf-8").strip()
    status, data = client.pull_config(token, machine_id, if_none_match)
    if status == 304:
        return None

    apply_text_atomically(settings.target_yaml, data["yaml_text"])
    marker.write_text(data["etag"], encoding="utf-8")

    effects = declared_effects(settings)
    start_keys = [key for key, effect in effects.items() if effect == "start"]
    hot_values = {
        key: value for key, effect in effects.items() if effect == "hot"
    }
    if start_keys:
        restart_pipeline(settings)
    elif hot_values:
        hot_update(settings, hot_values)

    client.report(
        token,
        {
            "config_version": data["config_version"],
            "applied_at": data.get("rendered_at", ""),
            "values": hot_values or {},
        },
    )
    return client.ack(
        token, {"config_version": data["config_version"], "ok": True, "error": None}
    )
