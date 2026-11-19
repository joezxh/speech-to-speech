"""Agent control endpoints published by the speech-to-speech server.

The s2s-agent used to be a separate process whose only job was to talk to the
console.  ``speech-to-speech serve --with-agent`` runs it inside the pipeline
process instead, and this module publishes that instance's capabilities on the
same port as the rest of the service, in the same style:

* ``/v1/agent/*`` paths, ``{"error": {"code", "message", "details"}}`` bodies;
* read-only endpoints are unauthenticated (like ``/v1/pool`` and ``/v1/usage``);
* endpoints that change state or trigger an external action require
  ``Authorization: Bearer <S2S_ADMIN_TOKEN>`` and fail closed when no token is
  configured.

The routes are always registered so the contract never depends on a switch:
without ``--with-agent`` every call answers ``503 agent_disabled``.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
from typing import Any, Iterable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from speech_to_speech.api.openai_realtime.openapi_meta import admin_error_response
from speech_to_speech.api.openai_realtime.usage import aggregate_pool_usage

AGENT_TAG = "运维代理"

STATUS_PATH = "/v1/agent/status"
CAPABILITY_PATH = "/v1/agent/capability"
WORKLOADS_PATH = "/v1/agent/workloads"
METRICS_PATH = "/v1/agent/metrics"
DEPLOYMENT_PATH = "/v1/agent/deployment"
USAGE_PATH = "/v1/agent/usage"
HEARTBEAT_PATH = "/v1/agent/heartbeat"
CONFIG_SYNC_PATH = "/v1/agent/config/sync"
COMMANDS_POLL_PATH = "/v1/agent/commands/poll"
COMMANDS_PATH = "/v1/agent/commands"
REGISTER_PATH = "/v1/agent/register"
DRAIN_PATH = "/v1/agent/drain"
LOGS_PATH = "/v1/agent/logs"

#: The machine-command whitelist (see ``agent/commands.py``).
COMMAND_KINDS = (
    "drain",
    "resume",
    "reboot",
    "config_restart",
    "recover",
    "health_check",
)

_AGENT_PATHS = (
    STATUS_PATH,
    CAPABILITY_PATH,
    WORKLOADS_PATH,
    METRICS_PATH,
    DEPLOYMENT_PATH,
    USAGE_PATH,
    HEARTBEAT_PATH,
    CONFIG_SYNC_PATH,
    COMMANDS_POLL_PATH,
    COMMANDS_PATH,
    REGISTER_PATH,
    DRAIN_PATH,
    LOGS_PATH,
)


def _route_exists(app: FastAPI, path: str) -> bool:
    return any(getattr(route, "path", None) == path for route in app.routes)


def _error(status: int, code: str, message: str, details: Any = None) -> JSONResponse:
    """The management-endpoint error body, so the platform can pass it through as is."""

    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": details or []}},
    )


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else ""


def _require_admin(request: Request) -> JSONResponse | None:
    """Fail closed: an unset token must never mean "no authentication"."""

    expected = os.environ.get("S2S_ADMIN_TOKEN", "").strip()
    if not expected:
        return _error(
            503, "admin_disabled", "S2S_ADMIN_TOKEN is not configured on this service"
        )
    if not hmac.compare_digest(_bearer(request).encode(), expected.encode()):
        return _error(401, "unauthorized", "a valid Bearer token is required")
    return None


def _require_agent(agent: Any) -> JSONResponse | None:
    if agent is None:
        return _error(
            503,
            "agent_disabled",
            "the embedded agent is not enabled; start the server with --with-agent",
        )
    return None


def _action_error(exc: BaseException) -> JSONResponse:
    """Map an agent failure onto the shared error envelope."""

    from speech_to_speech.agent.embedded import AgentBusyError, AgentNotRegisteredError

    if isinstance(exc, AgentBusyError):
        return _error(409, "agent_busy", str(exc))
    if isinstance(exc, AgentNotRegisteredError):
        return _error(409, "agent_not_registered", str(exc))
    try:
        import httpx

        if isinstance(exc, httpx.HTTPError):
            return _error(
                502,
                "console_unreachable",
                f"the console is unreachable: {type(exc).__name__}",
            )
    except ImportError:  # pragma: no cover - httpx 是硬依赖
        pass
    return _error(500, "agent_error", f"{type(exc).__name__}: {exc}")


class _CommandRequest(BaseModel):
    kind: str = Field(description="机器命令类型，取值见 `kind` 枚举。")
    payload: dict[str, Any] = Field(
        default_factory=dict, description="命令参数；`health_check` 需要 `service_id`。"
    )


class _DrainRequest(BaseModel):
    drain: bool = Field(
        default=True, description="`true` 排空本机实例（新会话不再进入），`false` 恢复。"
    )


_STATUS_DESCRIPTION = """
**agent 运行态快照**。免鉴权。

返回内嵌 agent 的实时状态：

* `enabled` / `running`：agent 是否随本进程启动、常驻循环是否在跑；
* `registered`：本机是否已有机器令牌；
* `ticks`：已完成的轮次；`last_heartbeat_at` / `last_config_sync_at` / `last_command_at`：最近一次动作时间；
* `last_error` / `last_error_at`：最近一次失败（失败只退避，不影响语音链路）；
* `backoff_s`：当前退避时长（1s → 60s 封顶）；`next_action_in_s`：距离下一次动作的秒数。

```bash
curl http://localhost:8765/v1/agent/status
```
"""

_CAPABILITY_DESCRIPTION = """
**agent 能力与就绪自检**。免鉴权。

返回 agent 版本、协议版本、可执行动作列表，以及控制台地址、机器标识、注册码是否配置、
令牌是否就绪、本机 pipeline 是否可达。

> `restart_supported=false` 表示当前是**内嵌形态**：pipeline 就是这个进程，
> 从进程内部重启自己不可行，因此 `reboot` / `config_restart` 命令会被明确拒绝。

```bash
curl http://localhost:8765/v1/agent/capability
```
"""

_WORKLOADS_DESCRIPTION = """
**本机负载清单**。免鉴权。

返回 agent 声明文件（`agent.yaml`）里的负载，加上自动探测到的 pipeline 实例；
每项含 `kind`、`engine`、`model`、`port`、`vram_gb`（实测显存）、`health_path`（健康探测地址）
与 `params`（对应 block 的参数，密钥类参数已掩码为 `***`）。

> 采集会拉起 `nvidia-smi` 并做一次 HTTP 探测，因此服务端对结果做了 2 秒缓存。

```bash
curl http://localhost:8765/v1/agent/workloads
```
"""

_METRICS_DESCRIPTION = """
**节点资源指标**。免鉴权。

返回 CPU 使用率与负载、内存总量/用量/使用率、GPU 型号与利用率、GPU 显存总量/用量、
pipeline 进程占用显存（`pipeline_vram_gb`）与采集时间 `collected_at`。

> 拿不到的字段一律为 `null`，不猜。

```bash
curl http://localhost:8765/v1/agent/metrics
```
"""

_DEPLOYMENT_DESCRIPTION = """
**部署参数**。免鉴权。

分两栏返回：

* `runtime`：本机**运行时生效**的配置值（来自落地后的 YAML 与 supervisor）；
* `declared`：仓库**声明**的部署参数（来自构建期生成的 deployment manifest）。

密钥类参数（键名含 key/token/secret/password/credential）一律掩码为 `***`。

```bash
curl http://localhost:8765/v1/agent/deployment
```
"""

_USAGE_DESCRIPTION = """
**pipeline 累计用量**。免鉴权。

返回自进程启动以来的累计用量：输入/输出 token、完成的响应数、被取消的响应数、
对话轮次、音频时长与错误聚合——与 `GET /v1/usage` 同源同值。

```bash
curl http://localhost:8765/v1/agent/usage
```
"""

_HEARTBEAT_DESCRIPTION = """
**立即执行一次心跳**。需要鉴权。

不等下一个心跳周期，立刻向 console 上报一次机器状态（版本、GPU、负载清单、
运行时参数、token 窗口增量），并返回本次心跳体与 console 的响应。

* 失败不抛出：agent 失败只退避重试，语音链路不受影响。
* 需要 `Authorization: Bearer <S2S_ADMIN_TOKEN>`；未配置令牌时返回 503 `admin_disabled`。

```bash
curl -X POST http://localhost:8765/v1/agent/heartbeat \\
  -H "Authorization: Bearer $S2S_ADMIN_TOKEN"
```
"""

_CONFIG_SYNC_DESCRIPTION = """
**立即执行一轮配置同步**。需要鉴权。

完整跑一遍配置生效流程：拉取 console 渲染好的配置 → 原子替换本机 YAML →
按声明文件 `effects` 分流（`hot` 热更新会话 / `start` 重启 / `container` 仅登记）→
回报实际生效值 → 确认。

* `changed=false` 表示 console 侧没有新版本（`If-None-Match` 命中 304）。
* 内嵌形态下 `start` 类参数不会重启宿主进程（不可行），会明确失败而不是假装生效。
* 需要 `Authorization: Bearer <S2S_ADMIN_TOKEN>`；未配置令牌时返回 503 `admin_disabled`。

```bash
curl -X POST http://localhost:8765/v1/agent/config/sync \\
  -H "Authorization: Bearer $S2S_ADMIN_TOKEN"
```
"""

_COMMANDS_POLL_DESCRIPTION = """
**拉取并执行待办命令**。需要鉴权。

立刻从 console 拉取本机待办的机器命令并逐条执行、回执，返回每条命令的
`command_id`、`kind`、`ok`、`result` 与 `error`。

* 命令类型白名单：`drain`、`resume`、`reboot`、`config_restart`、`recover`、`health_check`。
* 命令「领到即被 console 标记 dispatched」，因此不会重复执行同一条。
* 同一时刻只允许一个动作在跑；并发触发返回 409 `agent_busy`。
* 需要 `Authorization: Bearer <S2S_ADMIN_TOKEN>`；未配置令牌时返回 503 `admin_disabled`。

```bash
curl -X POST "http://localhost:8765/v1/agent/commands/poll?limit=10" \\
  -H "Authorization: Bearer $S2S_ADMIN_TOKEN"
```
"""

_COMMANDS_DESCRIPTION = """
**执行一条指定命令**。需要鉴权。

不经轮询，直接执行一条机器命令并返回 `{ok, result, error}`。

| `kind` | 作用 | `payload` |
|---|---|---|
| `drain` | 排空本机实例 | 无 |
| `resume` | 恢复本机实例 | 无 |
| `reboot` | 经 supervisor 重启 pipeline | 无（内嵌形态不支持） |
| `config_restart` | 先同步配置再重启 pipeline | 无（内嵌形态不支持） |
| `recover` | 恢复调度并巡检实例 | 无 |
| `health_check` | 真探测某个服务的健康端点 | `service_id`（必填） |

* 未知 `kind` 返回 400 `invalid_request_error`。
* 需要 `Authorization: Bearer <S2S_ADMIN_TOKEN>`；未配置令牌时返回 503 `admin_disabled`。

```bash
curl -X POST http://localhost:8765/v1/agent/commands \\
  -H "Authorization: Bearer $S2S_ADMIN_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"kind":"health_check","payload":{"service_id":"pipeline"}}'
```
"""

_REGISTER_DESCRIPTION = """
**用注册码换取机器令牌**。需要鉴权。

走 agent 的两段式注册：拿 `S2S_AGENT_REGISTER_CODE` 向 console 换机器令牌，
令牌以 0600 权限落盘到 `S2S_AGENT_TOKEN_FILE`。

* 响应**不含令牌本身**，只回报注册结果、机器标识与令牌文件路径。
* 未配置注册码或 console 未返回令牌时返回 409 `agent_not_registered`。
* 需要 `Authorization: Bearer <S2S_ADMIN_TOKEN>`；未配置令牌时返回 503 `admin_disabled`。

```bash
curl -X POST http://localhost:8765/v1/agent/register \\
  -H "Authorization: Bearer $S2S_ADMIN_TOKEN"
```
"""

_DRAIN_DESCRIPTION = """
**排空 / 恢复本机实例**。需要鉴权。

把「本机实例应不应该接收新会话」这个期望态写进 console（console 侧的实例注册表
与内存状态同步生效），agent 侧的巡检会照此执行。

* `drain=true` 排空，`drain=false` 恢复；缺省为 `true`。
* 需要 `Authorization: Bearer <S2S_ADMIN_TOKEN>`；未配置令牌时返回 503 `admin_disabled`。

```bash
curl -X POST http://localhost:8765/v1/agent/drain \\
  -H "Authorization: Bearer $S2S_ADMIN_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"drain": true}'
```
"""

_LOGS_DESCRIPTION = """
**读取容器日志**。需要鉴权。

返回本机 pipeline 容器的最近日志（stdout / stderr 两路），已做有界截断与脱敏
（`api_key`、`token`、`secret`、`password` 与 `sk-` 开头的密钥会被替换成 `***`）。

* 默认最多 500 行 / 200 KiB，可用 `S2S_AGENT_LOG_MAX_LINES` 调整。
* 日志属运维敏感数据，因此需要鉴权。
* 需要 `Authorization: Bearer <S2S_ADMIN_TOKEN>`；未配置令牌时返回 503 `admin_disabled`。

```bash
curl http://localhost:8765/v1/agent/logs \\
  -H "Authorization: Bearer $S2S_ADMIN_TOKEN"
```
"""


def mount_agent(
    app: FastAPI,
    agent: Any | None = None,
    pool: Iterable[Any] | None = None,
) -> None:
    """Register the ``/v1/agent/*`` endpoints.

    Always registered: the contract must not depend on a runtime switch. When
    *agent* is ``None`` (the server was started without ``--with-agent``) every
    endpoint answers ``503 agent_disabled``.
    """

    if all(_route_exists(app, path) for path in _AGENT_PATHS):
        return

    units = list(pool) if pool is not None else []

    def _guard() -> JSONResponse | None:
        return _require_agent(agent)

    @app.get(
        STATUS_PATH,
        summary="agent 运行态快照",
        description=_STATUS_DESCRIPTION,
        tags=[AGENT_TAG],
        response_description="agent 运行态",
        responses={
            200: {
                "description": "运行态快照。",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "enabled": {"type": "boolean", "example": True},
                                "running": {"type": "boolean", "example": True},
                                "embedded": {"type": "boolean", "example": True},
                                "registered": {"type": "boolean", "example": True},
                                "machine_id": {"type": "string", "example": "node-a"},
                                "console_url": {"type": "string", "example": "http://127.0.0.1:8080"},
                                "heartbeat_interval_s": {"type": "integer", "example": 15},
                                "agent_version": {"type": "string", "example": "0.4.0"},
                                "uptime_s": {"type": "number", "example": 312.4},
                                "ticks": {"type": "integer", "example": 20},
                                "last_tick_at": {"type": "string", "nullable": True},
                                "last_heartbeat_at": {"type": "string", "nullable": True},
                                "last_heartbeat_ok": {"type": "boolean", "example": True},
                                "last_config_sync_at": {"type": "string", "nullable": True},
                                "last_command_at": {"type": "string", "nullable": True},
                                "last_error": {"type": "string", "example": ""},
                                "last_error_at": {"type": "string", "nullable": True},
                                "backoff_s": {"type": "number", "example": 1.0},
                                "next_action_in_s": {"type": "number", "example": 12.5},
                            },
                        },
                        "example": {
                            "enabled": True,
                            "running": True,
                            "registered": True,
                            "ticks": 20,
                            "last_heartbeat_ok": True,
                            "backoff_s": 1.0,
                        },
                    }
                },
            },
            503: admin_error_response("未开启 `--with-agent`。", "agent_disabled"),
        },
    )
    async def agent_status() -> Response:
        refusal = _guard()
        if refusal is not None:
            return refusal
        return JSONResponse(agent.status())

    @app.get(
        CAPABILITY_PATH,
        summary="agent 能力与就绪自检",
        description=_CAPABILITY_DESCRIPTION,
        tags=[AGENT_TAG],
        response_description="能力与就绪状态",
        responses={
            200: {
                "description": "能力与就绪状态。",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "agent_version": {"type": "string", "example": "0.4.0"},
                                "protocol_version": {"type": "integer", "example": 1},
                                "capabilities": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "example": ["heartbeat", "workloads", "commands"],
                                },
                                "actions": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "example": ["heartbeat", "config_sync"],
                                },
                                "embedded": {"type": "boolean", "example": True},
                                "restart_supported": {"type": "boolean", "example": False},
                                "console_url": {"type": "string", "example": "http://127.0.0.1:8080"},
                                "console_configured": {"type": "boolean", "example": True},
                                "machine_id": {"type": "string", "example": "node-a"},
                                "machine_configured": {"type": "boolean", "example": True},
                                "register_code_configured": {"type": "boolean", "example": True},
                                "token_ready": {"type": "boolean", "example": True},
                                "pipeline_reachable": {"type": "boolean", "example": True},
                            },
                        }
                    }
                },
            },
            503: admin_error_response("未开启 `--with-agent`。", "agent_disabled"),
        },
    )
    async def agent_capability() -> Response:
        refusal = _guard()
        if refusal is not None:
            return refusal
        return JSONResponse(await asyncio.to_thread(agent.capability))

    @app.get(
        WORKLOADS_PATH,
        summary="本机负载清单",
        description=_WORKLOADS_DESCRIPTION,
        tags=[AGENT_TAG],
        response_description="负载清单",
        responses={
            200: {
                "description": "负载清单。",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "workloads": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "kind": {"type": "string", "example": "pipeline"},
                                            "engine": {"type": "string", "example": "speech-to-speech-pipeline"},
                                            "model": {"type": "string", "example": "Qwen3-TTS"},
                                            "port": {"type": "integer", "example": 8765},
                                            "vram_gb": {"type": "number", "nullable": True, "example": 8.2},
                                            "health_path": {"type": "string", "example": "/v1/pool"},
                                            "listen": {"type": "string", "example": "127.0.0.1:8765"},
                                            "public_addr": {"type": "string", "example": "127.0.0.1:8765"},
                                            "params": {"type": "object", "additionalProperties": True},
                                        },
                                    },
                                }
                            },
                        },
                        "example": {"workloads": [{"kind": "pipeline", "port": 8765}]},
                    }
                },
            },
            503: admin_error_response("未开启 `--with-agent`。", "agent_disabled"),
        },
    )
    async def agent_workloads() -> Response:
        refusal = _guard()
        if refusal is not None:
            return refusal
        workloads = await asyncio.to_thread(agent.collect_workloads)
        return JSONResponse({"workloads": workloads})

    @app.get(
        METRICS_PATH,
        summary="节点资源指标",
        description=_METRICS_DESCRIPTION,
        tags=[AGENT_TAG],
        response_description="节点指标",
        responses={
            200: {
                "description": "节点指标。",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "cpu_pct": {"type": "number", "nullable": True, "example": 12.5},
                                "load_avg": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                    "example": [0.4, 0.5, 0.6],
                                },
                                "mem_total_gb": {"type": "number", "nullable": True, "example": 62.9},
                                "mem_used_gb": {"type": "number", "nullable": True, "example": 18.4},
                                "mem_pct": {"type": "number", "nullable": True, "example": 29.3},
                                "gpu_name": {"type": "string", "nullable": True, "example": "NVIDIA RTX 4090"},
                                "gpu_util_pct": {"type": "integer", "nullable": True, "example": 35},
                                "gpu_mem_total_gb": {"type": "number", "nullable": True, "example": 24.0},
                                "gpu_mem_used_gb": {"type": "number", "nullable": True, "example": 9.1},
                                "pipeline_vram_gb": {"type": "number", "nullable": True, "example": 8.2},
                                "collected_at": {"type": "string", "example": "2026-11-18T09:00:00Z"},
                            },
                        }
                    }
                },
            },
            503: admin_error_response("未开启 `--with-agent`。", "agent_disabled"),
        },
    )
    async def agent_metrics() -> Response:
        refusal = _guard()
        if refusal is not None:
            return refusal
        return JSONResponse(await asyncio.to_thread(agent.collect_metrics))

    @app.get(
        DEPLOYMENT_PATH,
        summary="部署参数",
        description=_DEPLOYMENT_DESCRIPTION,
        tags=[AGENT_TAG],
        response_description="部署参数",
        responses={
            200: {
                "description": "运行时与声明两栏参数。",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "runtime": {"type": "object", "additionalProperties": True},
                                "declared": {"type": "object", "additionalProperties": True},
                            },
                        },
                        "example": {"runtime": {"tts.backend": "qwen3-tts"}, "declared": {}},
                    }
                },
            },
            503: admin_error_response("未开启 `--with-agent`。", "agent_disabled"),
        },
    )
    async def agent_deployment() -> Response:
        refusal = _guard()
        if refusal is not None:
            return refusal
        return JSONResponse(await asyncio.to_thread(agent.collect_deployment))

    @app.get(
        USAGE_PATH,
        summary="pipeline 累计用量",
        description=_USAGE_DESCRIPTION,
        tags=[AGENT_TAG],
        response_description="累计用量",
        responses={
            200: {
                "description": "累计用量。",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "input_tokens": {"type": "integer", "example": 1109},
                                "output_tokens": {"type": "integer", "example": 41416},
                                "responses_completed": {"type": "integer", "example": 11},
                                "responses_cancelled": {"type": "integer", "example": 2},
                                "turns": {"type": "integer", "example": 20},
                                "audio_duration_s": {"type": "number", "example": 42.5},
                                "total_tokens": {"type": "integer", "example": 42525},
                                "total_errors": {"type": "integer", "example": 0},
                                "errors_by_type": {"type": "object", "additionalProperties": True},
                            },
                        }
                    }
                },
            },
            503: admin_error_response("未开启 `--with-agent`。", "agent_disabled"),
        },
    )
    async def agent_usage() -> Response:
        refusal = _guard()
        if refusal is not None:
            return refusal
        return JSONResponse(aggregate_pool_usage(units))

    @app.post(
        HEARTBEAT_PATH,
        summary="立即执行一次心跳",
        description=_HEARTBEAT_DESCRIPTION,
        tags=[AGENT_TAG],
        response_description="心跳结果",
        responses={
            200: {
                "description": "心跳已发出。",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "sent": {"type": "boolean", "example": True},
                                "heartbeat": {"type": "object", "additionalProperties": True},
                                "console": {"type": "object", "additionalProperties": True},
                            },
                        }
                    }
                },
            },
            401: admin_error_response("缺少或错误的 Bearer 令牌。", "unauthorized"),
            409: admin_error_response("另一个 agent 动作正在执行。", "agent_busy"),
            502: admin_error_response("console 不可达。", "console_unreachable"),
            503: admin_error_response(
                "未开启 `--with-agent` 或未配置 `S2S_ADMIN_TOKEN`。", "admin_disabled"
            ),
        },
    )
    async def agent_heartbeat(request: Request) -> Response:
        refusal = _guard() or _require_admin(request)
        if refusal is not None:
            return refusal
        try:
            return JSONResponse(await asyncio.to_thread(agent.heartbeat_once))
        except Exception as exc:  # noqa: BLE001 - 统一错误信封
            return _action_error(exc)

    @app.post(
        CONFIG_SYNC_PATH,
        summary="立即执行一轮配置同步",
        description=_CONFIG_SYNC_DESCRIPTION,
        tags=[AGENT_TAG],
        response_description="同步结果",
        responses={
            200: {
                "description": "同步完成。",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "changed": {"type": "boolean", "example": True},
                                "ack": {
                                    "type": "object",
                                    "nullable": True,
                                    "additionalProperties": True,
                                },
                            },
                        },
                        "example": {"changed": True, "ack": {"config_version": "v12"}},
                    }
                },
            },
            401: admin_error_response("缺少或错误的 Bearer 令牌。", "unauthorized"),
            409: admin_error_response("另一个 agent 动作正在执行。", "agent_busy"),
            502: admin_error_response("console 不可达。", "console_unreachable"),
            503: admin_error_response(
                "未开启 `--with-agent` 或未配置 `S2S_ADMIN_TOKEN`。", "admin_disabled"
            ),
        },
    )
    async def agent_config_sync(request: Request) -> Response:
        refusal = _guard() or _require_admin(request)
        if refusal is not None:
            return refusal
        try:
            return JSONResponse(await asyncio.to_thread(agent.sync_config_once))
        except Exception as exc:  # noqa: BLE001
            return _action_error(exc)

    @app.post(
        COMMANDS_POLL_PATH,
        summary="拉取并执行待办命令",
        description=_COMMANDS_POLL_DESCRIPTION,
        tags=[AGENT_TAG],
        response_description="命令回执",
        responses={
            200: {
                "description": "逐条回执。",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "count": {"type": "integer", "example": 1},
                                "receipts": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "command_id": {
                                                "type": "string",
                                                "example": "cmd_abc123",
                                            },
                                            "kind": {"type": "string", "example": "health_check"},
                                            "ok": {"type": "boolean", "example": True},
                                            "result": {
                                                "type": "object",
                                                "additionalProperties": True,
                                            },
                                            "error": {"type": "string", "example": ""},
                                        },
                                    },
                                },
                            },
                        },
                        "example": {
                            "count": 1,
                            "receipts": [
                                {
                                    "command_id": "cmd_abc123",
                                    "kind": "health_check",
                                    "ok": True,
                                    "result": {"reachable": True},
                                    "error": "",
                                }
                            ],
                        },
                    }
                },
            },
            401: admin_error_response("缺少或错误的 Bearer 令牌。", "unauthorized"),
            409: admin_error_response("另一个 agent 动作正在执行。", "agent_busy"),
            502: admin_error_response("console 不可达。", "console_unreachable"),
            503: admin_error_response(
                "未开启 `--with-agent` 或未配置 `S2S_ADMIN_TOKEN`。", "admin_disabled"
            ),
        },
    )
    async def agent_commands_poll(request: Request, limit: int = 10) -> Response:
        refusal = _guard() or _require_admin(request)
        if refusal is not None:
            return refusal
        bounded = max(1, min(int(limit), 50))
        try:
            receipts = await asyncio.to_thread(agent.poll_commands_once, limit=bounded)
            return JSONResponse(receipts)
        except Exception as exc:  # noqa: BLE001
            return _action_error(exc)

    @app.post(
        COMMANDS_PATH,
        summary="执行一条指定命令",
        description=_COMMANDS_DESCRIPTION,
        tags=[AGENT_TAG],
        response_description="命令回执",
        responses={
            200: {
                "description": "命令执行结果。",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "ok": {"type": "boolean", "example": True},
                                "result": {"type": "object", "additionalProperties": True},
                                "error": {"type": "string", "example": ""},
                            },
                        },
                        "example": {"ok": True, "result": {"reachable": True}, "error": ""},
                    }
                },
            },
            400: admin_error_response("请求体非法或命令类型不在白名单内。", "invalid_request_error"),
            401: admin_error_response("缺少或错误的 Bearer 令牌。", "unauthorized"),
            409: admin_error_response("另一个 agent 动作正在执行。", "agent_busy"),
            502: admin_error_response("console 不可达。", "console_unreachable"),
            503: admin_error_response(
                "未开启 `--with-agent` 或未配置 `S2S_ADMIN_TOKEN`。", "admin_disabled"
            ),
        },
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "kind": {
                                    "type": "string",
                                    "enum": list(COMMAND_KINDS),
                                    "description": "机器命令类型。",
                                    "example": "health_check",
                                },
                                "payload": {
                                    "type": "object",
                                    "description": "命令参数；`health_check` 需要 `service_id`。",
                                },
                            },
                            "required": ["kind"],
                        },
                        "example": {
                            "kind": "health_check",
                            "payload": {"service_id": "pipeline"},
                        },
                    }
                },
            }
        },
    )
    async def agent_run_command(request: Request) -> Response:
        refusal = _guard() or _require_admin(request)
        if refusal is not None:
            return refusal
        # The body is parsed here rather than by FastAPI: the guard above must
        # win over a malformed body, otherwise a disabled agent would answer
        # 422 instead of the documented 503.
        try:
            body = await request.json()
        except ValueError:
            return _error(400, "invalid_request_error", "body must be a JSON object")
        if not isinstance(body, dict):
            return _error(400, "invalid_request_error", "body must be a JSON object")
        try:
            payload = _CommandRequest.model_validate(body)
        except ValidationError as exc:
            return _error(
                400,
                "invalid_request_error",
                f"invalid command payload ({exc.error_count()} field error(s))",
            )
        if payload.kind not in COMMAND_KINDS:
            return _error(
                400,
                "invalid_request_error",
                f"kind must be one of: {', '.join(COMMAND_KINDS)}",
            )
        try:
            result = await asyncio.to_thread(
                agent.run_command_once, payload.kind, payload.payload
            )
            return JSONResponse(result)
        except Exception as exc:  # noqa: BLE001
            return _action_error(exc)

    @app.post(
        REGISTER_PATH,
        summary="用注册码换取机器令牌",
        description=_REGISTER_DESCRIPTION,
        tags=[AGENT_TAG],
        response_description="注册结果",
        responses={
            200: {
                "description": "注册成功。",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "registered": {"type": "boolean", "example": True},
                                "machine_id": {"type": "string", "example": "node-a"},
                                "token_file": {
                                    "type": "string",
                                    "example": "/run/s2s-agent/token",
                                },
                            },
                        }
                    }
                },
            },
            401: admin_error_response("缺少或错误的 Bearer 令牌。", "unauthorized"),
            409: admin_error_response(
                "尚未注册（无注册码或 console 未返回令牌）。", "agent_not_registered"
            ),
            502: admin_error_response("console 不可达。", "console_unreachable"),
            503: admin_error_response(
                "未开启 `--with-agent` 或未配置 `S2S_ADMIN_TOKEN`。", "admin_disabled"
            ),
        },
    )
    async def agent_register(request: Request) -> Response:
        refusal = _guard() or _require_admin(request)
        if refusal is not None:
            return refusal
        try:
            return JSONResponse(await asyncio.to_thread(agent.register_once))
        except Exception as exc:  # noqa: BLE001
            return _action_error(exc)

    @app.post(
        DRAIN_PATH,
        summary="排空 / 恢复本机实例",
        description=_DRAIN_DESCRIPTION,
        tags=[AGENT_TAG],
        response_description="排空结果",
        responses={
            200: {
                "description": "期望态已写入。",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "drain": {"type": "boolean", "example": True},
                                "console": {"type": "object", "additionalProperties": True},
                            },
                        }
                    }
                },
            },
            400: admin_error_response("请求体非法。", "invalid_request_error"),
            401: admin_error_response("缺少或错误的 Bearer 令牌。", "unauthorized"),
            409: admin_error_response("另一个 agent 动作正在执行。", "agent_busy"),
            502: admin_error_response("console 不可达。", "console_unreachable"),
            503: admin_error_response(
                "未开启 `--with-agent` 或未配置 `S2S_ADMIN_TOKEN`。", "admin_disabled"
            ),
        },
        openapi_extra={
            "requestBody": {
                "required": False,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "drain": {
                                    "type": "boolean",
                                    "description": "`true` 排空本机实例，`false` 恢复；缺省为 `true`。",
                                    "example": True,
                                }
                            },
                        },
                        "example": {"drain": True},
                    }
                },
            }
        },
    )
    async def agent_drain(request: Request) -> Response:
        refusal = _guard() or _require_admin(request)
        if refusal is not None:
            return refusal
        drain = True
        raw = await request.body()
        if raw:
            try:
                body = json.loads(raw)
            except ValueError:
                return _error(400, "invalid_request_error", "body must be a JSON object")
            if not isinstance(body, dict):
                return _error(400, "invalid_request_error", "body must be a JSON object")
            try:
                drain = _DrainRequest.model_validate(body).drain
            except ValidationError as exc:
                return _error(
                    400,
                    "invalid_request_error",
                    f"invalid drain payload ({exc.error_count()} field error(s))",
                )
        try:
            return JSONResponse(await asyncio.to_thread(agent.set_drain, drain))
        except Exception as exc:  # noqa: BLE001
            return _action_error(exc)

    @app.get(
        LOGS_PATH,
        summary="读取容器日志",
        description=_LOGS_DESCRIPTION,
        tags=[AGENT_TAG],
        response_description="容器日志",
        responses={
            200: {
                "description": "有界且脱敏的容器日志。",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "logs": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "source": {
                                                "type": "string",
                                                "example": "stdout",
                                            },
                                            "lines": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                                "example": ["pipeline ready"],
                                            },
                                        },
                                    },
                                }
                            },
                        },
                        "example": {"logs": [{"source": "stdout", "lines": ["pipeline ready"]}]},
                    }
                },
            },
            401: admin_error_response("缺少或错误的 Bearer 令牌。", "unauthorized"),
            503: admin_error_response(
                "未开启 `--with-agent` 或未配置 `S2S_ADMIN_TOKEN`。", "admin_disabled"
            ),
        },
    )
    async def agent_logs(request: Request) -> Response:
        refusal = _guard() or _require_admin(request)
        if refusal is not None:
            return refusal
        logs = await asyncio.to_thread(agent.collect_logs)
        return JSONResponse({"logs": logs})


__all__ = [
    "AGENT_TAG",
    "CAPABILITY_PATH",
    "COMMANDS_PATH",
    "COMMANDS_POLL_PATH",
    "CONFIG_SYNC_PATH",
    "DEPLOYMENT_PATH",
    "DRAIN_PATH",
    "HEARTBEAT_PATH",
    "LOGS_PATH",
    "METRICS_PATH",
    "REGISTER_PATH",
    "STATUS_PATH",
    "USAGE_PATH",
    "WORKLOADS_PATH",
    "mount_agent",
]

