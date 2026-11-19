"""可嵌入的 s2s-agent 运行时：可停止、可单步触发、状态可观测。

两种部署形态共用这一份实现：

* 独立进程：``python -m speech_to_speech.agent``（supervisor 拉起，见
  ``console/deploy/supervisord.conf`` 的 ``[program:s2s-agent]``）；
* 内嵌进程：``speech-to-speech serve --with-agent``，agent 与语音链路同进程、
  同端口，``/v1/agent/*`` 控制接口由同一实例驱动。

纪律不变：任一环节失败不抛出、不阻塞语音链路——语音在 pipeline，agent 只是
它的秘书。心跳失败指数退避 1s→60s 封顶；无 token 且有注册码先注册。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from speech_to_speech.agent import collectors, config_sync, pipeline_inspect
from speech_to_speech.agent import commands as command_executor
from speech_to_speech.agent.client import AgentClient
from speech_to_speech.agent.collectors import Usage, UsageDelta
from speech_to_speech.agent.settings import AgentSettings

BACKOFF_START_S = 1.0
BACKOFF_MAX_S = 60.0

# 采集器会拉起 nvidia-smi 子进程并做 HTTP 探测，而只读端点免鉴权：没有缓存的
# 话，一次误打就能把机器变成子进程工厂。
TTL_WORKLOADS_S = 2.0
TTL_METRICS_S = 2.0
TTL_DEPLOYMENT_S = 5.0

# 上报给 console 的能力声明（spec §5.2）。
AGENT_CAPABILITIES = (
    "heartbeat",
    "workloads",
    "token",
    "config_pull",
    "config_report",
    "commands",
)

# 本实例对外提供的动作（REST 层据此渲染能力清单）。
AGENT_ACTIONS = (
    "heartbeat",
    "config_sync",
    "commands_poll",
    "commands_run",
    "register",
    "drain",
    "logs",
)


class AgentBusyError(RuntimeError):
    """另一个 agent 动作正在执行；调用方应稍后重试。"""


class AgentNotRegisteredError(RuntimeError):
    """本机没有机器令牌，且无法用注册码换到。"""


def _iso(timestamp: float) -> str | None:
    """单调时钟时间戳 → ISO-8601（UTC）；0 表示「还没有」。"""

    if not timestamp:
        return None
    return datetime.fromtimestamp(timestamp, UTC).isoformat().replace("+00:00", "Z")


class EmbeddedAgent:
    """s2s-agent 的宿主进程可控形态。

    与旧的长驻循环相比，这里把「一轮」抽成了 :meth:`tick`，把状态收进实例，
    因此控制接口可以手动触发单步动作，而不必等待下一个心跳周期。
    """

    def __init__(
        self,
        settings: AgentSettings,
        *,
        stop_event: threading.Event | None = None,
        client: AgentClient | None = None,
        embedded: bool = True,
        usage_provider: Callable[[], Usage] | None = None,
    ) -> None:
        self.settings = settings
        self.embedded = embedded
        # 宿主进程共享的停止事件：ThreadManager.stop() 会置位 handler.stop_event，
        # 因此这个属性名不能改。
        self.stop_event = stop_event if stop_event is not None else threading.Event()
        self._client = client
        self._usage_provider = usage_provider
        # 单步动作的 single-flight 锁：命令「领到即被 console 标记 dispatched」，
        # 重复执行有副作用（重启、排空），所以并发触发直接拒绝而不是排队。
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._cache: dict[str, tuple[float, Any]] = {}
        self._backoff = BACKOFF_START_S
        self._turn_offset = 0
        self._log_tick = 0
        self._prev_usage: Usage | None = None
        self._ticks = 0
        self._running = False
        self._started_at = time.monotonic()
        self._next_due_at = self._started_at
        self._last_tick_at = 0.0
        self._last_heartbeat_at = 0.0
        self._last_heartbeat_ok = False
        self._last_heartbeat_body: dict[str, Any] = {}
        self._last_config_sync_at = 0.0
        self._last_command_at = 0.0
        self._last_error = ""
        self._last_error_at = 0.0

    # ── 基础设施 ──────────────────────────────────────────────────

    @property
    def client(self) -> AgentClient:
        """console REST 客户端；延迟创建，开关关闭时不留任何连接。"""

        if self._client is None:
            self._client = AgentClient(self.settings.console_url)
        return self._client

    def _acquire(self) -> None:
        if not self._lock.acquire(blocking=False):
            raise AgentBusyError("another agent action is already running")

    def _release(self) -> None:
        try:
            self._lock.release()
        except RuntimeError:  # pragma: no cover - 防御性：重复释放不应炸掉调用方
            pass

    def _record_error(self, exc: BaseException) -> None:
        with self._state_lock:
            self._last_error = f"{type(exc).__name__}: {exc}"
            self._last_error_at = time.monotonic()
        logger.warning("agent tick failed: {}", exc)

    def _wait(self, seconds: float) -> None:
        """睡到下一个动作点，但停止事件一来立刻返回。"""

        with self._state_lock:
            self._next_due_at = time.monotonic() + seconds
        self.stop_event.wait(seconds)

    def _cached(self, key: str, ttl_s: float, producer: Callable[[], Any]) -> Any:
        now = time.monotonic()
        with self._state_lock:
            entry = self._cache.get(key)
            if entry is not None and entry[0] > now:
                return entry[1]
        value = producer()
        with self._state_lock:
            self._cache[key] = (now + ttl_s, value)
        return value

    # ── 令牌 ──────────────────────────────────────────────────────

    def load_token(self) -> str:
        path = Path(self.settings.token_file)
        return path.read_text(encoding="utf-8").strip() if path.is_file() else ""

    def save_token(self, token: str) -> None:
        """0600 落盘（§5.2 两段式第 2 步）。"""

        path = Path(self.settings.token_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token, encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass

    def _register(self) -> str | None:
        """一次性注册码换 token；失败返回 None（下一轮再试）。"""

        if not self.settings.register_code:
            return None
        try:
            data = self.client.register(
                {
                    "register_code": self.settings.register_code,
                    "machine": {"machine_id": self.settings.machine_id},
                    "workloads": [],
                }
            )
        except Exception as exc:  # noqa: BLE001 - 网络失败下一轮再试
            logger.warning("agent register failed: {}", exc)
            return None
        token = str((data or {}).get("machine_token") or "")
        if not token:
            logger.warning("agent register returned no machine token")
            return None
        self.save_token(token)
        return token

    def ensure_token(self) -> str:
        """拿机器令牌；没有就用注册码换一个，都没有就抛错。"""

        token = self.load_token() or self._register()
        if not token:
            raise AgentNotRegisteredError(
                "no machine token on disk and no usable register code"
            )
        return token

    # ── 心跳 ──────────────────────────────────────────────────────

    def _heartbeat_body(self, usage: Usage | UsageDelta, uptime_s: int) -> dict:
        metrics = pipeline_inspect.collect_node_metrics()
        deployment = pipeline_inspect.collect_deployment_params(self.settings)
        workloads = collectors.collect_workloads(
            self.settings, pipeline_vram_gb=metrics["pipeline_vram_gb"]
        )
        return {
            "protocol_version": 1,
            "agent_version": pipeline_inspect.package_version(),
            "machine": {
                "machine_id": self.settings.machine_id,
                "uptime_s": uptime_s,
                "version": pipeline_inspect.package_version(),
                "gpu": metrics["gpu_name"] or "",
                **{key: value for key, value in metrics.items() if key != "gpu_name"},
            },
            "capabilities": list(AGENT_CAPABILITIES),
            "workloads": workloads,
            "runtime": {"deployment": deployment},
            "tokens": usage.__dict__,
        }

    def _read_usage(self) -> Usage:
        """本机 pipeline 的累计用量；不可达按零增量处理，不阻塞心跳。"""

        if self._usage_provider is not None:
            try:
                return self._usage_provider()
            except Exception:  # noqa: BLE001 - 采集失败按零增量
                return Usage()
        return collectors.read_usage(self.settings)

    # ── 一轮 ──────────────────────────────────────────────────────

    def tick(self) -> dict:
        """执行一轮完整动作：心跳 → 配置同步 → 命令轮询 → 日志 → 时延。

        失败一律向上抛给调用方决定怎么处理（常驻循环退避，控制接口回 5xx）。
        """

        token = self.ensure_token()

        cur_usage = self._read_usage()
        delta = collectors.usage_diff(self._prev_usage, cur_usage)
        self._prev_usage = cur_usage
        body = self._heartbeat_body(delta, int(time.monotonic() - self._started_at))
        self.client.heartbeat(token, body)
        with self._state_lock:
            self._last_heartbeat_at = time.monotonic()
            self._last_heartbeat_ok = True
            self._last_heartbeat_body = body

        config = self._sync_config(token)
        with self._state_lock:
            self._last_config_sync_at = time.monotonic()

        receipts = self._poll_commands(token)
        logs = self._maybe_upload_logs(token)
        latency_rows = self._tail_latency()

        with self._state_lock:
            self._ticks += 1
            self._last_tick_at = time.monotonic()

        return {
            "heartbeat": body,
            "config": config,
            "commands": receipts,
            "logs": logs,
            "latency_rows": latency_rows,
        }

    def _poll_commands(self, token: str) -> list[dict]:
        try:
            return command_executor.poll_and_run_detailed(
                self.client, token, self.settings, allow_restart=not self.embedded
            )
        except Exception as exc:  # noqa: BLE001 - 命令失败不影响后续采集
            logger.warning("agent command poll failed: {}", exc)
            return []

    def _maybe_upload_logs(self, token: str) -> int:
        with self._state_lock:
            self._log_tick += 1
            tick = self._log_tick
        if tick % 4 != 0:
            return 0
        try:
            logs = pipeline_inspect.collect_container_logs(self.settings)
            if logs:
                self.client.upload_logs(token, logs)
            return len(logs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("agent log upload failed: {}", exc)
            return 0

    def _tail_latency(self) -> int:
        """断点续读本机 pipeline 日志里的时延行；只推进游标，暂不上报。"""

        try:
            offset, rows = collectors.tail_turn_latency(
                self.settings.pipeline_log, self._turn_offset
            )
        except Exception:  # noqa: BLE001 - 采集失败不影响心跳
            return 0
        self._turn_offset = offset
        return len(rows)

    # ── 常驻循环（handler 契约） ─────────────────────────────────

    def run(self) -> None:
        """阻塞直到停止事件置位。

        ``ThreadManager.start()`` 会以 ``target=handler.run`` 起线程，
        ``stop()`` 会置位 ``handler.stop_event``，所以这里必须监听同一个事件。
        异常一律吞掉：语音链路优先，agent 失败只退避。
        """

        logger.info(
            "agent: embedded={} | console={} machine={} heartbeat={}s",
            self.embedded,
            self.settings.console_url,
            self.settings.machine_id,
            self.settings.heartbeat_s,
        )
        with self._state_lock:
            self._running = True
        backoff = BACKOFF_START_S
        try:
            while not self.stop_event.is_set():
                try:
                    self.tick()
                except Exception as exc:  # noqa: BLE001 - 语音链路优先，agent 失败只退避
                    self._record_error(exc)
                    self._wait(backoff)
                    backoff = min(backoff * 2, BACKOFF_MAX_S)
                    with self._state_lock:
                        self._backoff = backoff
                    continue
                backoff = BACKOFF_START_S
                with self._state_lock:
                    self._backoff = backoff
                    self._last_error = ""
                self._wait(self.settings.heartbeat_s)
        finally:
            with self._state_lock:
                self._running = False
            logger.info("agent: stopped")

    # ── 单步动作（控制接口触发） ─────────────────────────────────

    def heartbeat_once(self) -> dict:
        """立即发一次心跳，返回心跳体与 console 响应。"""

        self._acquire()
        try:
            token = self.ensure_token()
            cur_usage = self._read_usage()
            delta = collectors.usage_diff(self._prev_usage, cur_usage)
            self._prev_usage = cur_usage
            body = self._heartbeat_body(delta, int(time.monotonic() - self._started_at))
            response = self.client.heartbeat(token, body)
            with self._state_lock:
                self._last_heartbeat_at = time.monotonic()
                self._last_heartbeat_ok = True
                self._last_heartbeat_body = body
            return {"sent": True, "heartbeat": body, "console": response}
        finally:
            self._release()

    def _sync_config(self, token: str) -> dict | None:
        """跑一轮配置同步。

        内嵌形态下 pipeline 就是当前进程：从进程内部重启自己不可行，所以
        ``start`` 类参数不会被应用（配置同步会如实回报未生效的值）。
        """

        if self.embedded:
            return config_sync.sync_config(
                self.client, token, self.settings, allow_restart=False
            )
        return config_sync.sync_config(self.client, token, self.settings)

    def sync_config_once(self) -> dict:
        """立即跑一轮配置同步（拉取 → 落地 → 分流 → 回报 → 确认）。"""

        self._acquire()
        try:
            token = self.ensure_token()
            ack = self._sync_config(token)
            with self._state_lock:
                self._last_config_sync_at = time.monotonic()
            # sync_config 返回 None 表示 console 侧没有新版本（304）。
            return {"changed": ack is not None, "ack": ack}
        finally:
            self._release()

    def poll_commands_once(self, *, limit: int = 10) -> dict:
        """立即拉取并执行本机待办命令，返回逐条回执。"""

        self._acquire()
        try:
            token = self.ensure_token()
            receipts = command_executor.poll_and_run_detailed(
                self.client,
                token,
                self.settings,
                limit=limit,
                allow_restart=not self.embedded,
            )
            with self._state_lock:
                self._last_command_at = time.monotonic()
            return {"count": len(receipts), "receipts": receipts}
        finally:
            self._release()

    def run_command_once(self, kind: str, payload: dict | None = None) -> dict:
        """直接执行一条指定命令（类型白名单见 commands.execute）。"""

        self._acquire()
        try:
            token = self.ensure_token()
            ok, result, error = command_executor.execute_command(
                {"kind": kind, "payload": payload or {}},
                self.settings,
                self.client,
                token,
                not self.embedded,
            )
            with self._state_lock:
                self._last_command_at = time.monotonic()
            return {"ok": ok, "result": result, "error": error}
        finally:
            self._release()

    def register_once(self) -> dict:
        """用注册码换机器令牌并落盘；绝不回显令牌本身。"""

        self._acquire()
        try:
            if not self.settings.register_code:
                raise AgentNotRegisteredError("S2S_AGENT_REGISTER_CODE is not configured")
            token = self._register()
            if not token:
                raise AgentNotRegisteredError("the console did not return a machine token")
            return {
                "registered": True,
                "machine_id": self.settings.machine_id,
                "token_file": self.settings.token_file,
            }
        finally:
            self._release()

    def set_drain(self, drain: bool) -> dict:
        """排空 / 恢复本机实例（写 console 的实例期望态）。"""

        self._acquire()
        try:
            token = self.ensure_token()
            result = self.client.set_instance_drain(token, drain)
            return {"drain": drain, "console": result}
        finally:
            self._release()

    # ── 只读观测 ─────────────────────────────────────────────────

    def status(self) -> dict:
        """agent 运行态快照。"""

        now = time.monotonic()
        with self._state_lock:
            return {
                "enabled": True,
                "running": self._running,
                "embedded": self.embedded,
                "registered": bool(self.load_token()),
                "machine_id": self.settings.machine_id,
                "console_url": self.settings.console_url,
                "heartbeat_interval_s": self.settings.heartbeat_s,
                "agent_version": pipeline_inspect.package_version(),
                "uptime_s": round(now - self._started_at, 1),
                "ticks": self._ticks,
                "last_tick_at": _iso(self._last_tick_at),
                "last_heartbeat_at": _iso(self._last_heartbeat_at),
                "last_heartbeat_ok": self._last_heartbeat_ok,
                "last_config_sync_at": _iso(self._last_config_sync_at),
                "last_command_at": _iso(self._last_command_at),
                "last_error": self._last_error,
                "last_error_at": _iso(self._last_error_at),
                "backoff_s": self._backoff,
                "next_action_in_s": max(0.0, round(self._next_due_at - now, 1)),
            }

    def capability(self) -> dict:
        """能力与就绪自检。"""

        return {
            "agent_version": pipeline_inspect.package_version(),
            "protocol_version": 1,
            "capabilities": list(AGENT_CAPABILITIES),
            "actions": list(AGENT_ACTIONS),
            "embedded": self.embedded,
            # 内嵌形态下 pipeline 就是当前进程，从进程内部重启自己不可行。
            "restart_supported": not self.embedded,
            "console_url": self.settings.console_url,
            "console_configured": bool(self.settings.console_url),
            "machine_id": self.settings.machine_id,
            "machine_configured": bool(self.settings.machine_id),
            "register_code_configured": bool(self.settings.register_code),
            "token_ready": bool(self.load_token()),
            "pipeline_reachable": self._pipeline_reachable(),
        }

    def collect_workloads(self) -> list[dict]:
        """本机负载清单（声明式负载 + pipeline 实例）。"""

        return self._cached(
            "workloads", TTL_WORKLOADS_S, lambda: collectors.collect_workloads(self.settings)
        )

    def collect_metrics(self) -> dict:
        """节点 CPU / GPU / 内存指标。"""

        return self._cached("metrics", TTL_METRICS_S, pipeline_inspect.collect_node_metrics)

    def collect_deployment(self) -> dict:
        """运行时生效参数与仓库声明参数（密钥类参数已掩码）。"""

        return self._cached(
            "deployment",
            TTL_DEPLOYMENT_S,
            lambda: pipeline_inspect.collect_deployment_params(self.settings),
        )

    def collect_logs(self) -> list[dict]:
        """有界且脱敏的容器日志（不缓存：日志必须是最新的）。"""

        return pipeline_inspect.collect_container_logs(self.settings)

    def read_usage(self) -> dict:
        """本机 pipeline 的累计用量快照。"""

        usage = self._read_usage()
        return {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "responses": usage.responses,
            "audio_duration_s": usage.audio_duration_s,
            "window_s": usage.window_s,
        }

    def _pipeline_reachable(self) -> bool:
        """本机 pipeline 的观测端点是否可达。"""

        import httpx  # noqa: PLC0415 - 只在自检时需要

        port = collectors.pipeline_port(self.settings)
        try:
            httpx.get(f"http://127.0.0.1:{port}/v1/pool", timeout=2.0).raise_for_status()
        except Exception:  # noqa: BLE001 - 探活失败就是不可达
            return False
        return True


__all__ = [
    "AGENT_ACTIONS",
    "AGENT_CAPABILITIES",
    "AgentBusyError",
    "AgentNotRegisteredError",
    "EmbeddedAgent",
]
