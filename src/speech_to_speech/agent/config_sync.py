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
from collections.abc import Iterable
from pathlib import Path

import yaml
from loguru import logger

from speech_to_speech.agent.client import AgentClient
from speech_to_speech.agent.collectors import pipeline_port
from speech_to_speech.agent.settings import AgentSettings

CALL_TIMEOUT = 60.0

# hot 参数 → 会话字段：只有明确是「会话字段」的键才下发到
# /internal/sessions/update。模型路径、端口这类键不属于会话配置，硬塞进去
# 会被 session.update 的 schema 直接拒绝。
SESSION_HOT_FIELDS = frozenset(
    {
        "instructions",
        "voice",
        "modalities",
        "temperature",
        "max_response_output_tokens",
        "turn_detection",
        "input_audio_format",
        "output_audio_format",
        "input_audio_transcription",
        "truncation",
        "response_format",
        "tool_choice",
        "include",
    }
)


def hot_session_payload(values: dict) -> tuple[dict, list[str]]:
    """把 hot 参数切成 (会话字段字典, 无法映射的键)。

    无法映射的键不是错误——它们可能本来就是「改了要重启」的参数，只是被
    声明成了 hot；调用方会记一条日志，而不是假装已经生效。
    """

    session: dict = {}
    unmapped: list[str] = []
    for key, value in values.items():
        field = str(key).rsplit(".", 1)[-1]
        if field in SESSION_HOT_FIELDS:
            session[field] = value
        else:
            unmapped.append(str(key))
    return session, unmapped


def _lookup_dotted(document: object, dotted_key: str) -> object | None:
    """按 ``a.b.c`` 取嵌套 YAML 里的值；取不到返回 None。"""

    current = document
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def values_for_keys(yaml_text: str, keys: Iterable[str]) -> dict[str, str]:
    """从渲染好的配置 YAML 里取出指定参数键的**实际值**。

    ``effects`` 只说明「这个键该走哪条生效链路」，值本身在 console 渲染出来
    的 YAML 里。回报给 console 的必须是值（漂移判定靠它），不是效果名。
    """

    wanted = list(keys)
    if not wanted:
        return {}
    try:
        document = yaml.safe_load(yaml_text) or {}
    except Exception:  # noqa: BLE001 - YAML 坏了不该让整轮同步失败
        logger.warning("rendered config yaml could not be parsed; no hot values extracted")
        return {}
    values: dict[str, str] = {}
    for key in wanted:
        value = _lookup_dotted(document, key)
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            values[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            values[key] = str(value)
    return values


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
    """hot 类参数逐项下发到本机 pipeline 的既有会话更新端点。

    端点是 fail-closed 的：必须带 `S2S_INTERNAL_TOKEN` 的 Bearer 头，否则一律
    401/503。端口也不再硬编码——服务可能跑在非 8765 上。
    """
    host = os.environ.get("S2S_AGENT_PIPELINE_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.environ.get("S2S_AGENT_PIPELINE_PORT", "0").strip() or 0) or pipeline_port(settings)
    token = os.environ.get("S2S_INTERNAL_TOKEN", "").strip()

    session, unmapped = hot_session_payload(values)
    if unmapped:
        logger.warning(
            "hot params are not session fields and were not pushed to live sessions: {}",
            ", ".join(sorted(unmapped)),
        )

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {"scope": "all", "target": None, "session": session}
    connection = http.client.HTTPConnection(host, port, timeout=CALL_TIMEOUT)
    try:
        connection.request(
            "POST",
            "/internal/sessions/update",
            body=json.dumps(payload),
            headers=headers,
        )
        response = connection.getresponse()
        if response.status >= 400:
            raise RuntimeError(f"/internal/sessions/update returned {response.status}")
    finally:
        connection.close()


def sync_config(
    client: AgentClient,
    token: str,
    settings: AgentSettings,
    *,
    allow_restart: bool = True,
) -> dict | None:
    """一轮配置同步。返回 ack 结果；任何失败由调用方（主循环）吞掉并退避。

    ``allow_restart=False`` 用于内嵌形态：此时 pipeline 就是当前进程，
    从进程内部重启自己不可行，``start`` 类参数只登记不生效（并如实回报）。
    """
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
    hot_keys = [key for key, effect in effects.items() if effect == "hot"]
    hot_values = values_for_keys(data["yaml_text"], hot_keys)
    start_values = values_for_keys(data["yaml_text"], start_keys)

    applied: dict[str, str] = {}
    if start_keys:
        if allow_restart:
            restart_pipeline(settings)
            applied.update(start_values)
        else:
            logger.warning(
                "config has start-effect params but the agent runs inside the pipeline "
                "process; they were not applied: {}",
                ", ".join(sorted(start_keys)),
            )
    elif hot_values:
        hot_update(settings, hot_values)
        applied.update(hot_values)

    client.report(
        token,
        {
            "config_version": data["config_version"],
            "applied_at": data.get("rendered_at", ""),
            "values": applied,
        },
    )
    return client.ack(
        token, {"config_version": data["config_version"], "ok": True, "error": None}
    )
