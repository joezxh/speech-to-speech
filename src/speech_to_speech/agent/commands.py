"""机器命令执行器：console 下达 → 本机真动作 → 回执（不阻塞语音链路）。

只做能落到真源的动作：排空/恢复写 console 实例期望态，重启走 supervisor
XML-RPC，拉起=恢复调度+巡检，健康检查读 agent.yaml 声明的 health_path 真探测。
"""

from __future__ import annotations

import httpx
from loguru import logger

from speech_to_speech.agent import config_sync
from speech_to_speech.agent.collectors import collect_workloads

PROBE_TIMEOUT_S = 2.0

# model_reload 契约：模块白名单与规范顺序（asr → llm → tts）。
RELOAD_MODULES = ("asr", "llm", "tts")
DEFAULT_DRAIN_TIMEOUT_MS = 5000


def normalize_reload_request(payload: dict) -> dict:
    """校验并规范化 model_reload payload；非法参数抛 ValueError。

    console API 用 camelCase，agent 内部统一 snake_case（与 serviceId 一致）。
    """
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")
    raw_modules = payload.get("modules")
    if not isinstance(raw_modules, (list, tuple)) or not raw_modules:
        raise ValueError("modules must be a non-empty list")
    selected = set()
    for module in raw_modules:
        if not isinstance(module, str) or module not in RELOAD_MODULES:
            raise ValueError(f"modules contains unsupported value: {module!r}")
        selected.add(module)
    modules = [module for module in RELOAD_MODULES if module in selected]

    scope = str(payload.get("scope", "all") or "all")
    if scope not in ("all", "unit"):
        raise ValueError(f"scope must be all or unit, got {scope!r}")
    unit_index = payload.get("unit_index", payload.get("unitIndex"))
    if scope == "unit" and unit_index is None:
        raise ValueError("unitIndex is required when scope=unit")
    if unit_index is not None:
        try:
            unit_index = int(unit_index)
        except (TypeError, ValueError):
            raise ValueError(f"unitIndex must be an integer, got {unit_index!r}") from None

    timeout = payload.get("drain_timeout_ms", payload.get("drainTimeoutMs", DEFAULT_DRAIN_TIMEOUT_MS))
    try:
        drain_timeout_ms = int(timeout)
    except (TypeError, ValueError):
        raise ValueError(f"drainTimeoutMs must be an integer, got {timeout!r}") from None
    if drain_timeout_ms < 0:
        raise ValueError("drainTimeoutMs must not be negative")

    config_version = payload.get("config_version", payload.get("configVersion", ""))
    return {
        "modules": modules,
        "scope": scope,
        "unit_index": unit_index,
        "drain": bool(payload.get("drain", True)),
        "drain_timeout_ms": drain_timeout_ms,
        "config_version": str(config_version or ""),
        "reason": str(payload.get("reason", "") or ""),
    }


def _model_reload(
    command: dict,
    client,
    token: str,
    reload_provider,
) -> tuple[bool, dict, str]:
    """校验参数后投递重载工作线程，同步回执 accepted。"""
    try:
        request = normalize_reload_request(command.get("payload") or {})
    except ValueError as exc:
        return False, {"stage": "validation"}, str(exc)

    command_id = str(command.get("command_id") or "")

    def on_progress(progress: dict) -> None:
        """阶段进度与终态都经 report_command 回执 console；失败只记日志。"""
        if not command_id:
            return
        status = str(progress.get("status") or "")
        terminal = status in {"succeeded", "failed"}
        result = dict(progress)
        if not terminal:
            result = {"status": "progress", "progress": progress}
        try:
            client.report_command(
                token, command_id, ok=status != "failed", result=result,
                error=str(progress.get("error", ""))[:512],
            )
        except Exception as exc:  # noqa: BLE001 - 回执失败不影响重载线程
            logger.warning("model reload progress receipt failed: {}", exc)

    task_id = reload_provider(request, on_progress)
    return (
        True,
        {
            "status": "accepted",
            "stage": "queued",
            "taskId": str(task_id),
            "modules": request["modules"],
        },
        "",
    )


def _drain(client, token: str, drain: bool) -> tuple[bool, dict, str]:
    result = client.set_instance_drain(token, drain)
    return True, result, ""


def _reboot(settings) -> tuple[bool, dict, str]:
    config_sync.restart_pipeline(settings)
    return True, {"restarted": True}, ""


def _config_restart(settings, client, token: str) -> tuple[bool, dict, str]:
    """先落地配置再重启；任一步失败都带阶段名回执，不假装成功。"""
    try:
        config = config_sync.sync_config(client, token, settings)
    except Exception as exc:  # noqa: BLE001 - 失败阶段必须显式回执
        return False, {"stage": "config"}, f"config stage failed: {type(exc).__name__}: {exc}"
    try:
        config_sync.restart_pipeline(settings)
    except Exception as exc:  # noqa: BLE001
        return False, {"stage": "restart", "config": config}, f"restart stage failed: {type(exc).__name__}: {exc}"
    return True, {"config": config, "restart": {"restarted": True}}, ""


def _recover(client, token: str) -> tuple[bool, dict, str]:
    drained = client.set_instance_drain(token, False)
    probed = client.probe_instances(token)
    return True, {**drained, **probed}, ""


def _service_matches(workload: dict, service_id: str) -> bool:
    kind = str(workload.get("kind") or "")
    port = workload.get("port")
    keys = {kind, f"{kind}:{port}"} if port is not None else {kind}
    return service_id in keys


def _health_check(settings, service_id: str) -> tuple[bool, dict, str]:
    if not service_id:
        return False, {"reachable": None, "reason": "service_id_missing"}, "service id missing"
    workload = next(
        (w for w in collect_workloads(settings) if _service_matches(w, service_id)), None
    )
    if workload is None:
        return False, {"reachable": None, "reason": "service_not_found"}, "service not found"
    path = str(workload.get("health_path") or "")
    address = str(workload.get("listen") or workload.get("public_addr") or "")
    if not path or not address:
        return False, {"reachable": None, "reason": "no_probe_target"}, "no health path or address"
    response = httpx.get(f"http://{address.rstrip('/')}{path}", timeout=PROBE_TIMEOUT_S)
    reachable = response.status_code < 400
    return (
        reachable,
        {
            "reachable": reachable,
            "status_code": response.status_code,
            "url": f"http://{address.rstrip('/')}{path}",
        },
        "" if reachable else f"http {response.status_code}",
    )


def execute(
    command: dict,
    settings,
    client,
    token: str,
    *,
    allow_restart: bool = True,
    reload_provider=None,
) -> tuple[bool, dict, str]:
    """返回 (ok, result, error)；未知类型按失败回执，绝不静默成功。

    ``allow_restart=False`` 用于内嵌形态：此时 pipeline 就是当前进程，
    从进程内部通过 supervisor 重启自己不可行，重启类命令一律明确失败。

    ``reload_provider`` 仅关键字、默认 None：存在时用于 model_reload 的
    进程内模块级重建；缺失时明确降级为 config_restart（独立进程形态）。
    """
    kind = str(command.get("kind") or "")
    payload = command.get("payload") or {}
    if kind == "model_reload" and reload_provider is not None:
        return _model_reload(command, client, token, reload_provider)
    if kind == "drain":
        return _drain(client, token, True)
    if kind == "resume":
        return _drain(client, token, False)
    if kind == "reboot":
        if not allow_restart:
            return False, {"reason": "not_supported_in_embedded_mode"}, (
                "restarting the pipeline is not supported while the agent runs "
                "inside the pipeline process"
            )
        return _reboot(settings)
    if kind == "config_restart":
        if not allow_restart:
            return False, {"reason": "not_supported_in_embedded_mode"}, (
                "restarting the pipeline is not supported while the agent runs "
                "inside the pipeline process"
            )
        return _config_restart(settings, client, token)
    if kind == "model_reload":
        # 独立进程形态（无 reload_provider）降级为整体配置重启。
        if not allow_restart:
            return False, {"reason": "not_supported_in_embedded_mode"}, (
                "model_reload requires a live pipeline coordinator; the standalone "
                "agent cannot restart the pipeline from inside the process"
            )
        ok, result, error = _config_restart(settings, client, token)
        if ok:
            result = {**result, "degraded": "config_restart"}
        return ok, result, error
    if kind == "recover":
        return _recover(client, token)
    if kind == "health_check":
        return _health_check(settings, str(payload.get("service_id") or ""))
    return False, {"reason": "unsupported_kind"}, f"unsupported command kind: {kind}"


def execute_command(
    command: dict,
    settings,
    client,
    token: str,
    allow_restart: bool = True,
    reload_provider=None,
) -> tuple[bool, dict, str]:
    """Call :func:`execute` with optional switches only when they matter.

    The default path keeps the historical four-argument call shape, so an
    existing override of ``execute`` (a stub, a wrapper) keeps working.
    """
    kwargs = {}
    if not allow_restart:
        kwargs["allow_restart"] = False
    if reload_provider is not None:
        kwargs["reload_provider"] = reload_provider
    if kwargs:
        return execute(command, settings, client, token, **kwargs)
    return execute(command, settings, client, token)


def poll_and_run_detailed(
    client,
    token: str,
    settings,
    *,
    limit: int = 10,
    allow_restart: bool = True,
    reload_provider=None,
) -> list[dict]:
    """每 tick 的独立步骤：任何单条命令失败都照常回执，绝不影响主循环。

    返回逐条回执，供控制接口展示；:func:`poll_and_run` 只关心条数。
    回执本身失败只记日志，不影响同批剩余命令的回执（D5）。
    """
    commands = client.pull_commands(token, limit=limit)
    receipts: list[dict] = []
    for command in commands:
        command_id = str(command.get("command_id") or "")
        try:
            ok, result, error = execute_command(
                command, settings, client, token, allow_restart, reload_provider
            )
        except Exception as exc:  # noqa: BLE001 - 命令失败要回执给 console，不是吞掉
            ok, result, error = False, {}, f"{type(exc).__name__}: {exc}"
            logger.warning("machine command {} failed: {}", command_id, exc)
        try:
            client.report_command(
                token, command_id, ok=ok, result=result, error=error[:512]
            )
        except Exception as exc:  # noqa: BLE001 - 单次回执失败不能丢掉同批其余回执
            logger.warning("machine command {} receipt failed: {}", command_id, exc)
        receipts.append(
            {
                "command_id": command_id,
                "kind": str(command.get("kind") or ""),
                "ok": ok,
                "result": result,
                "error": error,
            }
        )
    return receipts


def poll_and_run(
    client,
    token: str,
    settings,
    *,
    limit: int = 10,
    allow_restart: bool = True,
) -> int:
    """拉取并执行本机待办命令，返回执行条数。"""
    return len(
        poll_and_run_detailed(
            client, token, settings, limit=limit, allow_restart=allow_restart
        )
    )
