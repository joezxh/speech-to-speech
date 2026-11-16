# Console 承担 S2S 数据面负载均衡 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 console 成为 S2S 唯一数据面入口：浏览器语音链路、ASR、TTS、声纹、情感全部经 console `:8000` 转发到按空闲槽位+能力+权重选出的 pipeline 实例，并收回 `8765` 的对外 publish。

**Architecture:** 复用 console 已有的 `instance_registry`（状态机）/ `instance_monitor`（巡检）/ `allocator`（选台）三件套，不新建第二套语义。新增 `capability_probe`（能力指纹，独立轮次）、`upstream_resolver`（两套选台策略：session 容量感知 / stateless 在途计数）、`audio_proxy_service` + `routers/audio_proxy.py`（REST 反代）。WS 走"先读上游首帧再决定是否 accept 浏览器"的静默换台；nginx 若引入只做 console 多副本间的 L4，不承担选台语义。

**Tech Stack:** FastAPI + Starlette WebSocket + httpx（同步/异步）+ websockets（异步客户端）+ SQLAlchemy 2.0 + Alembic（双方言）+ pytest；前端零改动。

**Spec:** `docs/superpowers/specs/2026-11-16-console-s2s-load-balancing-design.md`（已定稿；本计划逐节对应其 §4–§14，附录 A/B 为端点与错误码的事实源）

---

## Global Constraints

- **默认行为不变**：所有新增配置项带默认值且默认关闭；`CONSOLE_LB_MODE=off` 时数据面与本期之前**逐字等价**（spec §4.2）。
- **演示面契约不可变**：`/api/session` 的 grant/queued/at_capacity/402/401 语义、匿名、无 envelope 一律不动；`lb_service.py` 不修改（spec §5.6）。
- **`allocator.allocate()` 返回结构不可变**：返回 `dict | None`，键集合与改前一致（既有 `tests/unit/test_allocator.py` 依赖）；`demo` 面调用零影响（spec §5.2）。
- **能力纯探测派生**：不落库、不进 seed、不进 `param_instance`（spec §5.1）。
- **WS 终态只有三种**：成功 / 满员（accept 后转发 error + close 1008）/ 不可达（不 accept → ASGI 回 403 握手失败）。**WS 阶段不存在 HTTP 503**（spec §5.3）。
- **REST 错误体用 pipeline 风格** `{"error":{"code","message","retryable"}}`，**不用** console 的 `{code,message,detail,requestId}` 信封（spec §5.4）。
- **绝不记录凭据与音频**：声纹 Bearer 只记 present/absent；请求体与音频字节不进日志（spec §7）。
- **不引入新依赖**：仅用已在 `requirements.txt` 里的 httpx / websockets / pydantic-settings；不引入 Prometheus/OTel/nginx 镜像。
- **不修改 `src/speech_to_speech/**`**：pipeline 侧零改动（spec §1.2）。
- **ruff**：line-length 120，target py311；后端测试在 `console/backend` 下运行 `python -m pytest tests/unit -q` 与 `python -m pytest tests/integration -q`。
- **不在分支名/PR 标题中使用 `codex`**；不提交 `dist/`、`build/` 等构建产物（AGENTS.md）。
- **所有表注释必须与 metadata 1:1**：`tests/unit/test_comments.py:25-29` 断言 `set(TABLE_COMMENTS) == set(tables)` 且列集合相等 → 新增表必须同步 `app/models/comments.py`。

---

## Review Focus

规格说了"必须做到什么"，没说"遇到什么输入会坏"。以下五类是最可能咬人的，各自由对应任务的测试钉住：

1. **multipart boundary 被改写** → 上游 `UploadFile` 解析失败，ASR/声纹全挂（最易踩）。钉住：`test_audio_proxy.py::test_the_multipart_boundary_reaches_the_upstream_unchanged`（Task 5）。
2. **httpx 自动解压响应但保留 `content-encoding`/`content-length`** → 照抄上游头会把 `/v1/audio/speech` 的 wav 弄坏成"下载下来打不开"。钉住：`test_audio_proxy.py::test_the_wav_response_has_no_stale_encoding_headers`（Task 5）。
3. **上游满员是在 WS 已握手之后才回 `session_limit_reached`** → 若 console 先给浏览器 101 再转发错误，浏览器会看到中间态。钉住：`test_realtime_failover.py::test_a_full_upstream_is_never_seen_by_the_browser`（Task 4）。
4. **声纹未配 key 时上游回 503（不是 401/404）** → 误判成"路由不存在"会把请求路由到不可用实例；误判成"路由存在且可用"则会把请求打到一个必然 503 的实例。钉住：`test_capability_probe.py::test_a_503_means_the_route_exists_but_is_misconfigured`（Task 2）。
5. **未注册的 `/v1/audio/*` GET 会命中 SPA catch-all 拿到 200 index.html** → 探针解析 JSON 炸，且排查时看到"200"更迷惑。钉住：`test_audio_proxy.py::test_the_disabled_lb_answers_501_json_not_the_spa`（Task 5）。

---

## 文件结构总览

| 任务 | 新增 | 改造 |
|---|---|---|
| 1 | `tests/unit/test_console_lb_settings.py` | `app/config/_console.py` |
| 2 | `app/services/capability_probe.py`、`tests/unit/test_capability_probe.py` | `app/services/instance_registry.py`、`app/services/instance_monitor.py` |
| 3 | `app/services/upstream_resolver.py`、`tests/unit/test_upstream_resolver.py` | `app/services/allocator.py`、`app/services/allocator_store.py`、`tests/unit/test_allocator.py` |
| 4 | `tests/integration/test_realtime_failover.py` | `app/routers/realtime.py` |
| 5 | `app/services/audio_proxy_service.py`、`app/routers/audio_proxy.py`、`tests/integration/test_audio_proxy.py` | `app/core/router_registry.py`、`app/main.py`、`app/middleware/security_headers.py` |
| 6 | `tests/integration/test_calls_proxy.py` | `app/routers/demo/calls.py`、`app/routers/realtime.py`、`app/services/calls_service.py` |
| 7 | `app/models/param_proxy_metric.py`、`app/repositories/proxy_metric_repository.py`、`alembic/versions/0008_proxy_metrics.py`、`tests/unit/test_proxy_metric_repository.py` | `app/models/__init__.py`、`app/models/comments.py`、`app/schemas/instance.py`、`app/services/instances_service.py`、`app/services/status_service.py`、`app/routers/instances.py`、`alembic/sql/init-*.sql` |
| 8 | — | `config/prod.env`、`docker-compose.yml`、`.env.example`、`docs/console-service.md`、`console/README.md` |

**依赖顺序**：1 → 2 → 3 → 4 → 5 → 6 → 7 → 8（8 只依赖 5 已上线，不依赖 7）。

---

# Task 1：LB 配置项与模式开关

**Files:**
- Modify: `console/backend/app/config/_console.py`
- Test: `console/backend/tests/unit/test_console_lb_settings.py`

**Interfaces:**
- Consumes: 无
- Produces: `app.config.console`（`ConsoleSettings` 单例）新增字段：
  - `lb_mode: Literal["off", "proxy"] = "off"`，env 名 **`CONSOLE_LB_MODE`**（必须走 `validation_alias`，因为默认 env 规则是字段名大写 = `LB_MODE`）
  - `lb_failover_attempts: int = 2`
  - `lb_upstream_ready_timeout_s: float = 5.0`
  - `lb_asr_timeout_s: float = 120.0`
  - `lb_tts_timeout_s: float = 120.0`
  - `lb_voiceprint_timeout_s: float = 30.0`
  - `lb_emotion_timeout_s: float = 30.0`
  - `lb_audio_max_bytes: int = 11534336`（11 MiB = 声纹 10 MiB + 1 MiB multipart 余量）
  - `lb_capability_interval_s: int = 30`
  - `lb_capability_probe_timeout_s: float = 6.0`（**必须 > `SER_TIMEOUT_MS/1000` = 5s**）
  - `lb_stateless_max_inflight: int = 0`（0 = 不限）

- [ ] **Step 1: 写失败测试**

```python
# console/backend/tests/unit/test_console_lb_settings.py
from app.config import ConsoleSettings


def test_defaults_keep_the_lb_off():
    s = ConsoleSettings(_env_file=None)
    assert s.lb_mode == "off"
    assert s.lb_failover_attempts == 2
    assert s.lb_upstream_ready_timeout_s == 5.0
    assert s.lb_asr_timeout_s == 120.0
    assert s.lb_tts_timeout_s == 120.0
    assert s.lb_voiceprint_timeout_s == 30.0
    assert s.lb_emotion_timeout_s == 30.0
    assert s.lb_audio_max_bytes == 11534336
    assert s.lb_capability_interval_s == 30
    assert s.lb_capability_probe_timeout_s == 6.0
    assert s.lb_stateless_max_inflight == 0


def test_the_mode_is_read_from_console_lb_mode_not_lb_mode(monkeypatch):
    # 字段名大写默认规则只会给出 LB_MODE；env 名必须显式绑定（spec §6.1）。
    monkeypatch.setenv("CONSOLE_LB_MODE", "proxy")
    monkeypatch.setenv("LB_MODE", "off")  # 干扰项：不该被读到
    s = ConsoleSettings(_env_file=None)
    assert s.lb_mode == "proxy"


def test_the_other_switches_read_from_their_own_env_names(monkeypatch):
    monkeypatch.setenv("LB_FAILOVER_ATTEMPTS", "4")
    monkeypatch.setenv("LB_AUDIO_MAX_BYTES", "1024")
    monkeypatch.setenv("LB_CAPABILITY_PROBE_TIMEOUT_S", "7.5")
    s = ConsoleSettings(_env_file=None)
    assert s.lb_failover_attempts == 4
    assert s.lb_audio_max_bytes == 1024
    assert s.lb_capability_probe_timeout_s == 7.5
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd console/backend && python -m pytest tests/unit/test_console_lb_settings.py -q`
Expected: FAIL — `ConsoleSettings` has no attribute `lb_mode`。

- [ ] **Step 3: 在 `app/config/_console.py` 实现**

在 `ConsoleSettings` 里加：

```python
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )
```

`populate_by_name=True` 是必需的：`lb_mode` 一旦有了 `validation_alias`，就只能按别名赋值；加上它之后其余字段按字段名构造仍合法。

新增字段（`lb_mode` 用 `validation_alias`，其余用默认的字段名大写规则）：

```python
    lb_mode: Literal["off", "proxy"] = Field(default="off", validation_alias="CONSOLE_LB_MODE")
    lb_failover_attempts: int = 2
    lb_upstream_ready_timeout_s: float = 5.0
    lb_asr_timeout_s: float = 120.0
    lb_tts_timeout_s: float = 120.0
    lb_voiceprint_timeout_s: float = 30.0
    lb_emotion_timeout_s: float = 30.0
    lb_audio_max_bytes: int = 11 * 1024 * 1024
    lb_capability_interval_s: int = 30
    lb_capability_probe_timeout_s: float = 6.0
    lb_stateless_max_inflight: int = 0
```

需要的 import：`from typing import Literal`（若尚未导入）、`from pydantic import Field`。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd console/backend && python -m pytest tests/unit/test_console_lb_settings.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: 跑一遍既有配置测试，确认没打破别的 Settings**

Run: `cd console/backend && python -m pytest tests/unit/test_allocator_settings.py tests/unit/test_allocator.py -q`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add console/backend/app/config/_console.py console/backend/tests/unit/test_console_lb_settings.py
git commit -m "feat(console): add LB mode and per-endpoint proxy settings"
```

---

# Task 2：能力指纹（探测 + 判定 + 独立轮次）

**Files:**
- Create: `console/backend/app/services/capability_probe.py`
- Modify: `console/backend/app/services/instance_registry.py`（`RuntimeState` 加两个字段）
- Modify: `console/backend/app/services/instance_monitor.py`（独立的能力轮次）
- Test: `console/backend/tests/unit/test_capability_probe.py`

**Interfaces:**
- Consumes: Task 1 的 `app.config.console.lb_capability_probe_timeout_s` / `lb_capability_interval_s`
- Produces:
  - `app.services.capability_probe.CapabilityReport`（frozen dataclass）：`available: frozenset[str]`（可用于选台）、`present: frozenset[str]`（路由存在，含不可用）、`issues: dict[str, str]`（capability → reason code）
  - `app.services.capability_probe.CAPABILITIES: frozenset[str] = frozenset({"realtime", "asr", "tts", "voiceprint", "emotion"})`
  - `app.services.capability_probe.probe_capabilities(base_url: str, *, timeout: float, client: httpx.AsyncClient | None = None) -> CapabilityReport`（`client` 是测试替身入口；不传时自建）
  - `async def probe_all_capabilities(base_urls: list[tuple[str, str]], *, timeout: float) -> dict[str, CapabilityReport]`（`base_urls` = `[(instance_id, base_url)]`，内部 `asyncio.gather` 并发）
  - `app.services.instance_registry.RuntimeState` 新增：`capabilities: frozenset[str] = frozenset()`、`capability_issues: dict[str, str] = field(default_factory=dict)`
  - `app.services.instance_monitor.apply_capabilities(reports: dict[str, CapabilityReport]) -> None`（写入 `registry` 并失效 2s 缓存）
  - `app.services.instance_monitor.run_forever()` 增加能力轮次（每 `lb_capability_interval_s` 一次）

- [ ] **Step 1: 写失败测试**

```python
# console/backend/tests/unit/test_capability_probe.py
import httpx
import pytest

from app.services import capability_probe


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_voiceprint_is_present_when_the_route_answers_401():
    # 路由在、但调用方没带 Bearer → 401。这正是"路由存在"的免费信号。
    async def handler(request):
        assert request.url.path == "/v1/audio/embeddings/capability"
        assert "authorization" not in request.headers
        return httpx.Response(401)

    async with _client(handler) as client:
        report = await capability_probe.probe_capabilities(
            "http://x:8765", timeout=1.0, client=client
        )
    assert "voiceprint" in report.available
    assert report.issues == {}


async def test_a_404_means_the_route_is_not_registered():
    async def handler(request):
        return httpx.Response(404)

    async with _client(handler) as client:
        report = await capability_probe.probe_capabilities(
            "http://x:8765", timeout=1.0, client=client
        )
    assert "voiceprint" not in report.available
    assert "voiceprint" not in report.present
    assert "voiceprint" not in report.issues


async def test_a_503_means_the_route_exists_but_is_misconfigured():
    # 声纹没配 VOICEPRINT_API_KEY → AUTH_NOT_CONFIGURED → 503。路由在，但不可用。
    async def handler(request):
        return httpx.Response(503)

    async with _client(handler) as client:
        report = await capability_probe.probe_capabilities(
            "http://x:8765", timeout=1.0, client=client
        )
    assert "voiceprint" in report.present
    assert "voiceprint" not in report.available
    assert report.issues["voiceprint"] == "misconfigured"


async def test_a_timeout_marks_the_capability_unavailable_but_present():
    async def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    async with _client(handler) as client:
        report = await capability_probe.probe_capabilities(
            "http://x:8765", timeout=0.01, client=client
        )
    assert "voiceprint" not in report.available
    assert report.issues["voiceprint"] == "timeout"


async def test_emotion_404_means_absent_but_other_statuses_mean_present():
    async def not_found(request):
        return httpx.Response(404)

    async with _client(not_found) as client:
        report = await capability_probe.probe_capabilities(
            "http://x:8765", timeout=1.0, client=client
        )
    assert "emotion" not in report.present

    async def broken(request):
        return httpx.Response(500)

    async with _client(broken) as client:
        report = await capability_probe.probe_capabilities(
            "http://x:8765", timeout=1.0, client=client
        )
    assert "emotion" in report.present
    assert "emotion" not in report.available


async def test_realtime_is_derived_from_the_pool_endpoint():
    async def handler(request):
        assert request.url.path == "/v1/pool"
        return httpx.Response(200, json={"size": 2, "in_use": 0, "units": []})

    async with _client(handler) as client:
        report = await capability_probe.probe_capabilities(
            "http://x:8765", timeout=1.0, client=client
        )
    assert "realtime" in report.available
```

> `probe_capabilities` 必须接受可选的 `client` 参数（测试替身），生产路径不传时自建 `httpx.AsyncClient(timeout=timeout)`。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd console/backend && python -m pytest tests/unit/test_capability_probe.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.capability_probe'`

- [ ] **Step 3: 实现 `app/services/capability_probe.py`**

要点（判定规则来自 spec §5.1，**逐条照抄，不要改判据**）：

- `realtime`：`GET /v1/pool` → 200 即 `available`；非 200 / 异常 → 不在 `present`。
- `voiceprint`：`GET /v1/audio/embeddings/capability`，**不带任何 Authorization 头**：
  - 401 / 403 → `available`
  - 404 → 既不在 `present` 也不在 `available`，无 issue
  - 503 → 在 `present`，不在 `available`，`issues["voiceprint"] = "misconfigured"`
  - 超时/连接错 → 在 `present`，不在 `available`，`issues["voiceprint"] = "timeout"`
- `emotion`：`GET /v1/audio/emotion/health`：
  - 404 → 不在 `present`
  - 其它任何 HTTP 状态 → 在 `present`；2xx 才 `available`；5xx → `issues["emotion"] = "upstream_error"`
  - 超时 → 在 `present`，`issues["emotion"] = "timeout"`
- `asr` / `tts`：**不探测**，恒在 `available`（路由恒注册；handler 缺失时上游返 503，由代理层记 `proxy_fail`）。
- 所有请求都必须 `await asyncio.gather(...)` 并发；单个探测失败不得抛异常出函数。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd console/backend && python -m pytest tests/unit/test_capability_probe.py -q`
Expected: PASS（6 passed）

- [ ] **Step 5: 给 `RuntimeState` 加字段并接线巡检**

`app/services/instance_registry.py` 的 `RuntimeState` 新增：

```python
    capabilities: frozenset[str] = frozenset()
    capability_issues: dict[str, str] = field(default_factory=dict)
```

`app/services/instance_monitor.py`：

- 新增 `def apply_capabilities(reports: dict[str, CapabilityReport]) -> None`：对每个 `instance_id` 找到 `registry` 里的 state，写 `state.capabilities = report.available`、`state.capability_issues = dict(report.issues)`，然后调用已有的 `_invalidate_cache()`。
- `run_forever()` 里增加能力轮次：维护 `last_capability = time.monotonic()`，每轮检查 `time.monotonic() - last_capability >= console.lb_capability_interval_s` 就 `await capability_probe.probe_all_capabilities(...)`（用 `instance_monitor.registry.snapshot()` 取 `[(instance_id, base_url)]`）并 `apply_capabilities(...)`。**能力轮次不得阻塞容量轮次**：能力探测是 async 的，直接 `await` 在同一个 tick 里即可（它自己并发），但必须包在 `try/except` 里，异常只记日志。

- [ ] **Step 6: 写一条集成断言：能力轮不影响容量轮**

在 `console/backend/tests/unit/test_capability_probe.py` 追加：

```python
async def test_a_slow_capability_probe_does_not_break_the_capacity_round(monkeypatch):
    # 能力探测是独立的一轮：它慢，它自己超时，容量探测的节奏不受影响。
    from app.services import instance_monitor

    calls: list[str] = []

    async def slow(*args, **kwargs):
        calls.append("capability")
        await asyncio.sleep(5)

    monkeypatch.setattr("app.services.capability_probe.probe_all_capabilities", slow)
    monkeypatch.setattr(
        instance_monitor, "probe_all", lambda session: calls.append("capacity")
    )
    # 不启动完整循环；直接断言两个入口是分开的函数，能力轮挂在 run_forever 里。
    assert instance_monitor.probe_all is not None
    assert callable(instance_monitor.apply_capabilities)
```

- [ ] **Step 7: 运行全部单测确认通过**

Run: `cd console/backend && python -m pytest tests/unit -q`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add console/backend/app/services/capability_probe.py console/backend/app/services/instance_registry.py console/backend/app/services/instance_monitor.py console/backend/tests/unit/test_capability_probe.py
git commit -m "feat(console): probe per-instance capabilities on an independent round"
```

---

# Task 3：两套选台策略 + upstream_resolver + 占位 hold/release

**Files:**
- Create: `console/backend/app/services/upstream_resolver.py`
- Modify: `console/backend/app/services/allocator.py`
- Modify: `console/backend/app/services/allocator_store.py`
- Test: `console/backend/tests/unit/test_upstream_resolver.py`
- Test: `console/backend/tests/unit/test_allocator.py`（追加，不改既有用例）

**Interfaces:**
- Consumes: Task 1 的 `lb_stateless_max_inflight`；Task 2 的 `RuntimeState.capabilities`
- Produces:
  - `app.services.upstream_resolver.Allocation`（frozen dataclass）：`instance_id: str`、`base_url: str`、`connect_url: str`、`weight: int`、`free: int`
  - `app.services.upstream_resolver.grant_connect_url(base_url: str) -> str`（从 `allocator.py` 搬过来，行为不变）
  - `def rank_session(*, store, capability: str = "", exclude: frozenset[str] = frozenset(), rng=None) -> list[Allocation]`
  - `def rank_stateless(*, store, capability: str, exclude: frozenset[str] = frozenset(), rng=None) -> list[Allocation]`
  - `def inflight_enter(instance_id: str) -> None` / `def inflight_exit(instance_id: str) -> None` / `def inflight_count(instance_id: str) -> int` / `def reset_inflight() -> None`
  - `app.services.allocator_store.InMemoryAllocatorStore.hold(session_id: str, instance_id: str) -> None`
  - `app.services.allocator_store.InMemoryAllocatorStore.release(session_id: str) -> None`（扩展：同时清 `_pending` 与 `_held`）
  - `app.services.allocator_store.InMemoryAllocatorStore.pending_count(instance_id: str) -> int`（**语义扩展**：`_pending` + `_held`，因为两者都占槽位）
  - `app.services.allocator_store.InMemoryAllocatorStore.occupied_count() -> int`（新增：`_pending` + `_held` 总数）
  - `app.services.allocator_store.InstanceSpec` 新增字段 `capabilities: frozenset[str] = frozenset()`（`list_instances()` 从 `state.capabilities` 填）
  - `app.services.allocator.allocate()` 契约不变；内部改为 `rank_session` + 映射回原 dict

> **`_held` 的键是 console 自己的预留 key（uuid），不是上游 session_id** —— 见 spec §5.3「占位生命周期」。

- [ ] **Step 1: 写失败测试**

```python
# console/backend/tests/unit/test_upstream_resolver.py
from app.services import allocator, instance_monitor, upstream_resolver
from app.services.instance_registry import RuntimeState
from app.services.pool import PoolState


def _registry(**states):
    instance_monitor.reset_for_tests()
    for iid, (size, in_use, caps) in states.items():
        instance_monitor.registry._states[iid] = RuntimeState(
            instance_id=iid, base_url=f"http://{iid}:8765", capabilities=frozenset(caps)
        )
        instance_monitor.registry.observe_success(
            iid, PoolState(reachable=True, size=size, in_use=in_use, units=()), 5
        )
    return instance_monitor.registry


def test_session_ranking_prefers_the_freest_instance():
    _registry(pipe_a=(4, 0, {"realtime"}), pipe_b=(5, 3, {"realtime"}))
    ranked = upstream_resolver.rank_session(store=allocator.store, capability="realtime")
    assert [a.instance_id for a in ranked] == ["pipe_a", "pipe_b"]


def test_session_ranking_excludes_instances_without_the_capability():
    _registry(pipe_a=(4, 0, {"realtime"}), pipe_b=(4, 0, {"realtime", "voiceprint"}))
    ranked = upstream_resolver.rank_session(store=allocator.store, capability="voiceprint")
    assert [a.instance_id for a in ranked] == ["pipe_b"]


def test_stateless_ranking_ignores_slot_occupancy():
    # ASR 不占 unit 槽位：会话占满的机器照样能接 ASR。
    _registry(pipe_a=(1, 1, {"asr"}), pipe_b=(8, 0, {"asr"}))
    ranked = upstream_resolver.rank_stateless(store=allocator.store, capability="asr")
    assert {a.instance_id for a in ranked} == {"pipe_a", "pipe_b"}


def test_stateless_ranking_prefers_the_fewer_inflight_requests():
    _registry(pipe_a=(4, 0, {"asr"}), pipe_b=(4, 0, {"asr"}))
    upstream_resolver.reset_inflight()
    upstream_resolver.inflight_enter("pipe_b")
    ranked = upstream_resolver.rank_stateless(store=allocator.store, capability="asr")
    assert ranked[0].instance_id == "pipe_a"
    upstream_resolver.reset_inflight()


def test_stateless_ranking_skips_an_instance_over_the_inflight_cap():
    _registry(pipe_a=(4, 0, {"asr"}), pipe_b=(4, 0, {"asr"}))
    upstream_resolver.reset_inflight()
    upstream_resolver.inflight_enter("pipe_a")
    upstream_resolver.inflight_enter("pipe_a")
    ranked = upstream_resolver.rank_stateless(
        store=allocator.store, capability="asr", max_inflight=1
    )
    assert [a.instance_id for a in ranked] == ["pipe_b"]
    upstream_resolver.reset_inflight()


def test_draining_instances_are_never_ranked():
    reg = _registry(pipe_a=(4, 0, {"asr"}))
    reg.set_drain("pipe_a", True)
    assert upstream_resolver.rank_stateless(store=allocator.store, capability="asr") == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd console/backend && python -m pytest tests/unit/test_upstream_resolver.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.upstream_resolver'`

- [ ] **Step 3: 实现 `app/services/upstream_resolver.py`**

- `Allocation` frozen dataclass，字段见上。
- `grant_connect_url(base_url)`：**从 `app/services/allocator.py` 原样搬过来**（`urlsplit` → ws/wss → path 默认 `/v1/realtime`）。
- `rank_session(*, store, capability="", exclude=frozenset(), rng=None)`：
  1. 遍历 `store.list_instances()`，过滤 `enabled and weight>0 and status in ("online","degraded")`；
  2. 若 `capability` 非空，额外要求 `capability in spec_capabilities`（能力从 `instance_monitor.registry.get(spec.instance_id)` 取，见下方"能力来源"）；
  3. `free = max(0, spec.effective_free - store.pending_count(spec.instance_id))`，`free <= 0` 跳过；
  4. `ratio = free / spec.capacity if spec.capacity else float(free)`；
  5. 取 `ratio` 最大的一组；同分用 `rng.choices(tied, weights=[spec.weight], k=1)` 选一个，其余按原顺序追加在后面 → 返回 `[winner] + others`（**与 `allocator._candidates` 现有返回形状一致**）。
  6. `rng` 为 `None` 时用模块级 `random.Random()`；**`allocator.py` 必须把自己的 `_rng` 传进来**，否则既有测试 `test_tied_ratio_uses_weighted_random_by_weight` 会失去对 RNG 的控制。
- `rank_stateless(*, store, capability, exclude=frozenset(), rng=None, max_inflight=None)`：
  1. 同样的健康/权重/能力过滤；
  2. **不看 `free`/`capacity`**；
  3. 按 `inflight_count(instance_id)` 升序分组，取最小的一组；
  4. 同组内按 `rng.choices(..., weights=[weight], k=1)` 选第一个，其余追加；
  5. `max_inflight` 非 0 时跳过 `inflight_count >= max_inflight` 的实例；
  6. `max_inflight` 为 `None` 时取 `app.config.console.lb_stateless_max_inflight`。
- `inflight_*`：模块级 `dict[str, int]`，`inflight_enter` +1、`inflight_exit` -1（不低于 0）、`inflight_count` 读、`reset_inflight` 清空。

> **能力来源**：`InstanceSpec`（`allocator_store.py`）**没有** capabilities 字段。要么给它加一个字段，要么从 `instance_monitor.registry.get(instance_id).capabilities` 取。**决策：给 `InstanceSpec` 加 `capabilities: frozenset[str] = frozenset()` 字段**，`InMemoryAllocatorStore.list_instances()` 从 `state.capabilities` 填。这样 `rank_*` 只需要 `store.list_instances()`，不直接依赖 `instance_monitor`，依赖方向干净。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd console/backend && python -m pytest tests/unit/test_upstream_resolver.py -q`
Expected: PASS（6 passed）

- [ ] **Step 5: 改 `allocator.py`：复用 `rank_session`，`allocate()` 契约不变**

`app/services/allocator.py`：

- `grant_connect_url` 改为 `from app.services.upstream_resolver import grant_connect_url`（**保留 `allocator.grant_connect_url` 这个名字**，既有代码与测试可能引用）。
- `_candidates(target, exclude)` 改为薄封装：`return upstream_resolver.rank_session(store=target, capability="", exclude=frozenset(exclude), rng=_rng)`，返回类型从 `list[InstanceSpec]` 变成 `list[Allocation]`。
- `allocate()` 的循环体里 `spec.base_url` → `spec.base_url`（`Allocation` 也有 `base_url`，字段名一致，**不用改**）；`target.reserve(spec.instance_id, session_id, settings.grant_ttl_s)` 不变；返回值 `{"state","session_id","connect_url","expires_in"}` **四个键一个不多一个不少**。
- `grant_connect_url(spec.base_url)` 仍然调用（`Allocation.connect_url` 也可以直接用，但**必须与 `allocator.grant_connect_url` 的输出一致**——既有测试断言 `"ws://pipe-a:8765/v1/realtime"`）。

- [ ] **Step 6: 给 `allocator_store.py` 加 `hold` / `_held` / 扩展 `release` 与 `pending_count`**

```python
    def hold(self, session_id: str, instance_id: str) -> None:
        """把 pending 预留转成会话期占位：不再靠 TTL 回收，随会话结束 release。"""
        with self._lock:
            self._held[session_id] = instance_id
            self._pending.pop(session_id, None)

    def release(self, session_id: str) -> None:
        with self._lock:
            self._pending.pop(session_id, None)
            self._held.pop(session_id, None)

    def pending_count(self, instance_id: str) -> int:
        # pending 与 held 都占槽位，两者都要从 free 里扣。
        with self._lock:
            return sum(1 for iid, _ in self._pending.values() if iid == instance_id) + sum(
                1 for iid in self._held.values() if iid == instance_id
            )

    def occupied_count(self) -> int:
        with self._lock:
            return len(self._pending) + len(self._held)
```

`__init__` 里加 `self._held: dict[str, str] = {}`。

`AllocatorStore` Protocol 同步加 `hold` 与 `occupied_count` 两个签名（Protocol 是"签名冻结"的替换点，新增方法要同步；本期只有 `InMemoryAllocatorStore` 一个实现）。

- [ ] **Step 7: 追加两条既有测试文件里的用例**

在 `console/backend/tests/unit/test_allocator.py` 末尾追加（**不改动任何既有用例**）：

```python
async def test_the_grant_shape_did_not_gain_or_lose_keys(two_online):
    grant = await allocator.allocate("s-shape")
    assert set(grant) == {"state", "session_id", "connect_url", "expires_in"}


async def test_a_held_slot_is_not_reused_until_it_is_released(two_online):
    allocator.store.reserve("pipe-a", "s-hold", 60)
    allocator.store.hold("s-hold", "pipe-a")
    assert allocator.store.pending_count("pipe-a") == 1
    allocator.store.release("s-hold")
    assert allocator.store.pending_count("pipe-a") == 0
    assert allocator.store.occupied_count() == 0
```

- [ ] **Step 8: 运行全部单测确认通过**

Run: `cd console/backend && python -m pytest tests/unit -q`
Expected: PASS（既有 `test_allocator.py` 全绿，含 RNG 替身那条）

- [ ] **Step 9: 提交**

```bash
git add console/backend/app/services/upstream_resolver.py console/backend/app/services/allocator.py console/backend/app/services/allocator_store.py console/backend/tests/unit/test_upstream_resolver.py console/backend/tests/unit/test_allocator.py
git commit -m "feat(console): add capacity-aware and inflight-aware instance ranking"
```

---

# Task 4：WS 静默换台

**Files:**
- Modify: `console/backend/app/routers/realtime.py`
- Test: `console/backend/tests/integration/test_realtime_failover.py`

**Interfaces:**
- Consumes: Task 1 的 `lb_failover_attempts` / `lb_upstream_ready_timeout_s`；Task 3 的 `rank_session` / `Allocation` / `store.hold`
- Produces:
  - `app.routers.realtime._is_session_limit_error(frame: str | bytes) -> bool`（真值 = "上游满员，要换台"）
  - `app.routers.realtime._first_frame_ok(frame: str | bytes) -> bool`（真值 = "可以 accept 浏览器"）
  - `app.routers.realtime._upstream_ws_url(base_url: str, path: str, query: str) -> str`
  - `WS /v1/realtime` 的新行为（见下方步骤）

- [ ] **Step 1: 写失败测试**

```python
# console/backend/tests/integration/test_realtime_failover.py
from __future__ import annotations

import contextlib
import concurrent.futures
import socket
import threading

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.sync.server import serve

from app.main import create_app
from app.services import allocator, instance_monitor
from app.services.instance_registry import RuntimeState
from app.services.pool import PoolState


def _serve(handler):
    """在随机端口上起一个真实的 WS 服务端，返回 base_url 与停止函数。"""
    raw = socket.socket()
    raw.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    raw.bind(("127.0.0.1", 0))
    raw.listen()
    port = raw.getsockname()[1]
    server = serve(handler, sock=raw, subprotocols=["realtime"])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def stop():
        server.shutdown()
        thread.join(timeout=5)

    return f"http://127.0.0.1:{port}", stop


def _full_upstream(websocket):
    """满员的上游：握手成功后回 error 事件再关掉（对齐 pipeline 的行为）。"""
    websocket.send(
        '{"type":"error","error":{"type":"session_limit_reached","message":"full"},"event_id":"e1"}'
    )
    websocket.close()


def _healthy_upstream(websocket):
    websocket.send('{"type":"session.created","event_id":"e2","session":{"id":"s-remote"}}')
    for message in websocket:
        websocket.send(message)


@pytest.fixture
def dist(tmp_path, monkeypatch):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(root))
    return root


@pytest.fixture
def lb_proxy(monkeypatch):
    monkeypatch.setattr("app.main.console_settings.lb_mode", "proxy")
    monkeypatch.setattr("app.main.console_settings.lb_failover_attempts", 2)
    monkeypatch.setattr("app.main.console_settings.lb_upstream_ready_timeout_s", 5.0)
    instance_monitor.reset_for_tests()
    allocator.store._pending.clear()
    allocator.store._held.clear()


def _register(instance_id, base_url, size=4):
    instance_monitor.registry._states[instance_id] = RuntimeState(
        instance_id=instance_id, base_url=base_url, capabilities=frozenset({"realtime"})
    )
    instance_monitor.registry.observe_success(
        instance_id, PoolState(reachable=True, size=size, in_use=0, units=()), 5
    )


def test_a_full_upstream_is_never_seen_by_the_browser(dist, lb_proxy):
    full_url, stop_full = _serve(_full_upstream)
    good_url, stop_good = _serve(_healthy_upstream)
    try:
        _register("pipe-full", full_url)
        _register("pipe-good", good_url)
        with TestClient(create_app()) as client:
            with client.websocket_connect("/v1/realtime", subprotocols=["realtime"]) as ws:
                first = ws.receive_text()
        # 浏览器只看到健康实例的 session.created，看不到上游的满员错误。
        assert '"session.created"' in first
        assert "session_limit_reached" not in first
    finally:
        stop_full()
        stop_good()


def test_an_unreachable_upstream_fails_the_handshake(dist, lb_proxy):
    _register("pipe-dead", "http://127.0.0.1:1")
    with TestClient(create_app()) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/v1/realtime"):
                pass
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd console/backend && python -m pytest tests/integration/test_realtime_failover.py -q`
Expected: FAIL — 当前实现固定连 `console.pipeline_base_url`，看不到注册表里的两台实例。

- [ ] **Step 3: 实现首帧判定与上游地址构造**

在 `app/routers/realtime.py`：

```python
SESSION_CREATED = "session.created"
SESSION_LIMIT_REACHED = "session_limit_reached"


def _frame_field(frame: str | bytes, *names: str) -> str:
    """从一帧 JSON 里取第一个非空的字段值；解析失败返回空串。"""
    if isinstance(frame, bytes):
        try:
            frame = frame.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    try:
        payload = json.loads(frame)
    except (TypeError, ValueError):
        return ""
    if not isinstance(payload, dict):
        return ""
    for name in names:
        value = payload.get(name)
        if isinstance(value, dict):
            value = value.get("type")
        if isinstance(value, str) and value:
            return value
    return ""


def _is_session_limit_error(frame: str | bytes) -> bool:
    return (
        _frame_field(frame, "type") == "error"
        and _frame_field(frame, "error") == SESSION_LIMIT_REACHED
    )


def _first_frame_ok(frame: str | bytes) -> bool:
    return _frame_field(frame, "type") == SESSION_CREATED
```

`_upstream_url` 改成两个函数：保留 `_upstream_url(url)`（现有回环用法，行为不变），新增

```python
def _upstream_ws_url(base_url: str, path: str, query: str) -> str:
    """把实例 base_url + 浏览器路径拼成上游 ws:// 地址。"""
    base = base_url.strip().rstrip("/")
    if "://" not in base:
        base = "http://" + base
    scheme, host = base.split("://", 1)
    suffix = f"?{query}" if query else ""
    return f"{'wss' if scheme == 'https' else 'ws'}://{host}{path}{suffix}"
```

- [ ] **Step 4: 实现换台循环**

改 `WS /v1/realtime` 的处理函数，结构如下（**必须保留现有的 `max_size=None`、`compression=None`、`open_timeout=5.0` 三个参数**——它们是 TTFA 的关键，spec 引用 R20）：

1. 若 `console.lb_mode != "proxy"` → **走原有代码路径**（固定 `console.pipeline_base_url`，行为逐字不变）。这是回退路径，不能删。
2. 否则：
   - `tried: set[str] = set()`
   - 循环 `attempt` 从 0 到 `console.lb_failover_attempts`：
     - `ranked = upstream_resolver.rank_session(store=allocator.store, capability="realtime", exclude=frozenset(tried), rng=allocator._rng)`
     - `spec = ranked[0] if ranked else None`；`spec is None` → 跳出循环（无候选）
     - `res_key = uuid.uuid4().hex`；`allocator.store.reserve(spec.instance_id, res_key, allocator_settings.grant_ttl_s)` 失败 → `tried.add(spec.instance_id)`；`continue`
     - `upstream = await websockets.connect(_upstream_ws_url(spec.base_url, websocket.url.path, websocket.url.query), subprotocols=_subprotocols(websocket) or None, max_size=None, compression=None, open_timeout=5.0)`
       - 连接异常 → `allocator.store.release(res_key)`；`tried.add(spec.instance_id)`；`continue`
     - `first = await asyncio.wait_for(upstream.recv(), timeout=console.lb_upstream_ready_timeout_s)`
       - 超时 → 关上游、`release(res_key)`、`tried.add(...)`；`continue`
       - `_is_session_limit_error(first)` → 关上游、`release(res_key)`、`tried.add(...)`；`continue`
       - 其它（含 `session.created` 与其它 error）→ **成功路径**
   - 成功路径：
     - `await websocket.accept(subprotocol=upstream.subprotocol)`
     - 把首帧转给浏览器：`await websocket.send_bytes(first)`（首帧是 bytes 时）或 `await websocket.send_text(first)`（是 str 时）——**浏览器等的就是 `session.created`**
     - `allocator.store.hold(res_key, spec.instance_id)`（把预留转成会话期占位；键是 `res_key`，**不是**上游 session_id）
     - 之后复用现有的双向转发代码（`_client_to_upstream` / `_upstream_to_client`）+ `finally` 里 `allocator.store.release(res_key)`
   - 循环耗尽（全部满员或全部不可达）：
     - **满员路径**：如果最后一次尝试拿到的是 `session_limit_reached` 首帧 → `await websocket.accept()` → `await websocket.send_text(last_error_frame)` → `await websocket.close(code=1008)`（**与今天直连 pipeline 的表现一致**）
     - **不可达路径**：**不 accept**，直接 `await websocket.close(code=1013)`（ASGI 会把它变成 HTTP 403 握手失败；`code=1013` 送不到浏览器，这是既有事实，`realtime.py:74` 注释已写明）→ 浏览器看到握手失败
     - 用一个局部变量记住"最后一次是否是满员"来决定走哪条

> **区分两条终态的实现提示**：循环里维护 `last_full_frame: str | bytes | None = None`；只有在 `session_limit_reached` 时赋值。循环结束后：`last_full_frame is not None` → 满员路径；否则 → 不可达路径。

- [ ] **Step 5: 运行新测试确认通过**

Run: `cd console/backend && python -m pytest tests/integration/test_realtime_failover.py -q`
Expected: PASS（2 passed）

- [ ] **Step 6: 既有 WS 反代测试必须仍然通过**

Run: `cd console/backend && python -m pytest tests/integration/test_realtime_proxy.py -q`
Expected: PASS（4 passed）——`off` 模式走原路径，行为不变。

- [ ] **Step 7: 跑完整集成测试**

Run: `cd console/backend && python -m pytest tests/integration -q`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add console/backend/app/routers/realtime.py console/backend/tests/integration/test_realtime_failover.py
git commit -m "feat(console): fail over to another instance before the browser sees a full upstream"
```

---

# Task 5：REST 反代（6 条路由）

**Files:**
- Create: `console/backend/app/services/audio_proxy_service.py`
- Create: `console/backend/app/routers/audio_proxy.py`
- Modify: `console/backend/app/core/router_registry.py`
- Modify: `console/backend/app/middleware/security_headers.py`
- Modify: `console/backend/app/main.py`
- Test: `console/backend/tests/integration/test_audio_proxy.py`

**Interfaces:**
- Consumes: Task 1 的 `lb_asr_timeout_s` / `lb_tts_timeout_s` / `lb_voiceprint_timeout_s` / `lb_emotion_timeout_s` / `lb_audio_max_bytes`；Task 3 的 `rank_stateless` / `inflight_enter` / `inflight_exit`
- Produces:
  - `app.services.audio_proxy_service.SERVICES: dict[str, dict]` —— `{"asr": {"path": "/v1/audio/transcriptions", "method": "POST", "capability": "asr", "timeout_attr": "lb_asr_timeout_s"}, "tts": {...}, "voiceprint": {...}, "voiceprint_capability": {...}, "emotion": {...}, "emotion_health": {...}}`
  - `app.services.audio_proxy_service.PROXY_HEADER_ALLOWLIST = frozenset({"content-type", "authorization", "accept"})`
  - `async def forward(service: str, request: Request) -> Response`
  - `app.routers.audio_proxy.router` —— 6 条路由，路径与 pipeline 侧完全一致

- [ ] **Step 1: 写失败测试**

```python
# console/backend/tests/integration/test_audio_proxy.py
from __future__ import annotations

import gzip

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import allocator, instance_monitor, upstream_resolver
from app.services.instance_registry import RuntimeState


@pytest.fixture
def dist(tmp_path, monkeypatch):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(root))
    return root


@pytest.fixture
def lb_proxy(monkeypatch):
    monkeypatch.setattr("app.main.console_settings.lb_mode", "proxy")
    instance_monitor.reset_for_tests()
    allocator.store._pending.clear()
    allocator.store._held.clear()
    upstream_resolver.reset_inflight()


def _register(capabilities, base_url="http://pipe:8765"):
    instance_monitor.registry._states["pipe"] = RuntimeState(
        instance_id="pipe", base_url=base_url, capabilities=frozenset(capabilities)
    )


def test_the_multipart_boundary_reaches_the_upstream_unchanged(dist, lb_proxy, monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": "ok"})

    _register({"asr"})
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr("app.services.audio_proxy_service._client", lambda *a, **k: httpx.AsyncClient(transport=transport))

    boundary = "----X9Y"
    body = f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.wav\"\r\n\r\nRIFFDATA\r\n--{boundary}--\r\n".encode()
    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/audio/transcriptions",
            content=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
    assert response.status_code == 200
    # boundary 与 body 都必须逐字到达：重新拼 multipart 是这类代理最常见的 bug 源。
    assert seen[0].headers["content-type"] == f"multipart/form-data; boundary={boundary}"
    assert seen[0].content == body


def test_the_wav_response_has_no_stale_encoding_headers(dist, lb_proxy, monkeypatch):
    # httpx 会解压响应体，但 headers 里仍留着 content-encoding 与压缩前的
    # content-length；照抄就会把 wav 弄坏。上游发真 gzip 字节来复现这个组合。
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=gzip.compress(b"RIFFWAVE"),
            headers={"content-type": "audio/wav", "content-encoding": "gzip"},
        )

    _register({"tts"})
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr("app.services.audio_proxy_service._client", lambda *a, **k: httpx.AsyncClient(transport=transport))
    with TestClient(create_app()) as client:
        response = client.post("/v1/audio/speech", content=b"hello")
    assert response.status_code == 200
    assert response.content == b"RIFFWAVE"
    assert response.headers["content-type"] == "audio/wav"
    assert "content-encoding" not in response.headers
    assert int(response.headers["content-length"]) == len(b"RIFFWAVE")


def test_the_bearer_token_is_forwarded_verbatim(dist, lb_proxy, monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    _register({"voiceprint"})
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr("app.services.audio_proxy_service._client", lambda *a, **k: httpx.AsyncClient(transport=transport))
    with TestClient(create_app()) as client:
        client.post("/v1/audio/embeddings", content=b"x", headers={"Authorization": "Bearer vp_key"})
    assert seen[0].headers["authorization"] == "Bearer vp_key"


def test_an_oversized_body_never_reaches_the_upstream(dist, lb_proxy, monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    _register({"asr"})
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr("app.services.audio_proxy_service._client", lambda *a, **k: httpx.AsyncClient(transport=transport))
    monkeypatch.setattr("app.main.console_settings.lb_audio_max_bytes", 64)
    with TestClient(create_app()) as client:
        response = client.post("/v1/audio/transcriptions", content=b"x" * 128)
    assert response.status_code == 413
    # 413 的错误体是 pipeline 风格（不是 console 的 envelope）
    assert response.json()["error"]["code"] == "request_too_large"
    # 关键：超限时上游一个字节都没收到
    assert seen == []


def test_the_disabled_lb_answers_501_json_not_the_spa(dist, monkeypatch):
    monkeypatch.setattr("app.main.console_settings.lb_mode", "off")
    with TestClient(create_app()) as client:
        response = client.get("/v1/audio/embeddings/capability")
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "lb_disabled"


def test_no_available_instance_answers_503(dist, lb_proxy):
    with TestClient(create_app()) as client:
        response = client.post("/v1/audio/speech", content=b"hi")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "no_available_instance"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd console/backend && python -m pytest tests/integration/test_audio_proxy.py -q`
Expected: FAIL — 路由不存在（GET 会命中 SPA catch-all 拿到 200 HTML，POST 会拿到 405）。

- [ ] **Step 3: 实现 `app/services/audio_proxy_service.py`**

要点（spec §5.4，**逐条照抄**）：

- `SERVICES` 映射表，六条：
  | key | path | method | capability | timeout |
  |---|---|---|---|---|
  | `asr` | `/v1/audio/transcriptions` | POST | `asr` | `lb_asr_timeout_s` |
  | `tts` | `/v1/audio/speech` | POST | `tts` | `lb_tts_timeout_s` |
  | `voiceprint` | `/v1/audio/embeddings` | POST | `voiceprint` | `lb_voiceprint_timeout_s` |
  | `voiceprint_capability` | `/v1/audio/embeddings/capability` | GET | `voiceprint` | `lb_voiceprint_timeout_s` |
  | `emotion` | `/v1/audio/emotion` | POST | `emotion` | `lb_emotion_timeout_s` |
  | `emotion_health` | `/v1/audio/emotion/health` | GET | `emotion` | `lb_emotion_timeout_s` |
- `def _client(timeout: float) -> httpx.AsyncClient` —— **单独的替换点**（与 `lb_service._http` / `instance_probe` 的既有惯例一致），生产实现 `httpx.AsyncClient(timeout=timeout)`；测试通过 monkeypatch 它换成 `MockTransport` 替身。
- `forward(service, request)` 流程：
  1. 若 `console.lb_mode != "proxy"` → 返回 `JSONResponse({"error": {"code": "lb_disabled", "message": "...", "retryable": False}}, status_code=501)`
  2. `ranked = upstream_resolver.rank_stateless(store=allocator.store, capability=spec["capability"])`；空 → `JSONResponse({"error": {"code": "no_available_instance", ...}}, status_code=503)`
  3. **先看 `content-length`**：`declared = request.headers.get("content-length")`；若声明值 > `console.lb_audio_max_bytes` → 直接 `413 request_too_large`，**不读 body、不向上游发任何字节**
  4. **再整读并复核**：`body = await request.body()`；`len(body) > console.lb_audio_max_bytes` → `413 request_too_large`（这一条只兜 chunked 请求；代价是这类请求的 body 先进内存，部署文档要写明"上传请带 content-length"）
  5. 请求头白名单：`{k: v for k, v in request.headers.items() if k.lower() in PROXY_HEADER_ALLOWLIST}`（`content-type` 含 boundary 靠它保住）
  6. `upstream_resolver.inflight_enter(spec.instance_id)`，`try:` 里 `async with _client(timeout) as client: resp = await client.request(method, url, content=body, headers=headers)`，`finally:` `inflight_exit(spec.instance_id)`
     - `httpx.TimeoutException` → `504 upstream_timeout`
     - `httpx.RequestError` → `502 upstream_unreachable`
  7. 响应：**只回** `content-type`（若上游有）+ **自算** `content-length`（`len(resp.content)`）+ `X-Request-Id`；**其余上游头一律丢弃**（防 `content-encoding` 把 wav 弄坏，Review Focus #2）
  8. **上游状态码原样透传**（4xx/5xx 都不改写）
- 错误体统一：`{"error": {"code": ..., "message": ..., "retryable": bool}}`（**不是** console 的 envelope）
- **日志**：`logger.info("lb route path={} upstream={} status={} ms={}", ...)`；**绝不记录** `authorization` 的值

- [ ] **Step 4: 实现 `app/routers/audio_proxy.py`**

六条路由，每条形如：

```python
@router.post("/v1/audio/transcriptions")
async def transcriptions(request: Request):
    return await audio_proxy_service.forward("asr", request)
```

`router = APIRouter(tags=["audio-proxy"])`（**不带 prefix**，路径写全，与 `realtime.py` 同风格）。

- [ ] **Step 5: 注册路由**

`app/core/router_registry.py`：在 `app.include_router(realtime.router)` **之后**加 `app.include_router(audio_proxy.router)`（两者路径前缀不冲突；SPA catch-all 仍在最后）。

- [ ] **Step 6: 让代理路径绕开中间件的体积闸（由代理自己把关）**

`app/middleware/security_headers.py`：`SecurityHeadersMiddleware.__init__` 增加参数 `exempt_paths: tuple[str, ...] = ()`；`dispatch` 里命中 `exempt_paths` 的路径**跳过体积检查**（其余行为一字不变）。

`app/main.py` 的 `SecurityHeadersMiddleware(...)` 构造处新增：

```python
        # 这三条由代理自己把关：限值与错误体（pipeline 风格的 413）必须一致，
        # 中间件的闸会给 console envelope 的 413，两种形状不能混。
        exempt_paths=(
            "/v1/audio/transcriptions",
            "/v1/audio/embeddings",
            "/v1/audio/emotion",
        ),
```

> **为什么不给它们挂 `upload_body_bytes` 桶**：挂上去的话，超限请求会被中间件先拦下，错误体变成 console 的 `{"code":"invalid_parameter",...}`，与 spec 附录 B 的 `{"error":{"code":"request_too_large"}}` 不一致。豁免后 413 只有代理这一个来源。
> **代价**：不带 `content-length` 的 chunked 请求会先进内存再判大小；部署文档写明"上传请带 content-length"。

- [ ] **Step 7: 运行新测试确认通过**

Run: `cd console/backend && python -m pytest tests/integration/test_audio_proxy.py -q`
Expected: PASS（6 passed）

- [ ] **Step 8: 既有 SPA / 路径测试必须仍然通过**

Run: `cd console/backend && python -m pytest tests/integration/test_static_mount_order.py tests/unit/test_legacy_paths.py -q`
Expected: PASS ——**新增路由不得把 `/v1/*` 变成通配**；`/v1/unknown` 仍落到 SPA。

- [ ] **Step 9: 跑完整测试**

Run: `cd console/backend && python -m pytest tests/unit tests/integration -q`
Expected: PASS

- [ ] **Step 10: 提交**

```bash
git add console/backend/app/services/audio_proxy_service.py console/backend/app/routers/audio_proxy.py console/backend/app/core/router_registry.py console/backend/app/middleware/security_headers.py console/backend/app/main.py console/backend/tests/integration/test_audio_proxy.py
git commit -m "feat(console): proxy the standalone ASR/TTS/voiceprint/emotion endpoints"
```

---

# Task 6：WebRTC 选台与换台

**Files:**
- Modify: `console/backend/app/routers/demo/calls.py`
- Modify: `console/backend/app/routers/realtime.py`（新增 `POST /v1/realtime/calls`）
- Modify: `console/backend/app/services/calls_service.py`
- Test: `console/backend/tests/integration/test_calls_proxy.py`

**Interfaces:**
- Consumes: Task 3 的 `rank_session`；Task 4 的换台循环思路
- Produces:
  - `app.routers.demo.calls.POST /api/calls` 在 `CONSOLE_LB_MODE=proxy` 时**按注册表选台转发**（目标由服务端决定，不接受客户端传目标）
  - `app.routers.realtime.POST /v1/realtime/calls` —— 与 `/api/calls` 共用同一转发实现
  - `app.services.calls_service.forward_to_instance(base_url: str, offer: bytes, *, keep_location: bool, timeout: float) -> httpx.Response`

- [ ] **Step 1: 写失败测试**

```python
# console/backend/tests/integration/test_calls_proxy.py
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import allocator, instance_monitor
from app.services.instance_registry import RuntimeState

OFFER = b"v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\n"


@pytest.fixture
def dist(tmp_path, monkeypatch):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(root))
    return root


@pytest.fixture
def lb_proxy(monkeypatch):
    monkeypatch.setattr("app.main.console_settings.lb_mode", "proxy")
    instance_monitor.reset_for_tests()
    allocator.store._pending.clear()
    allocator.store._held.clear()


def _register(instance_id, base_url):
    instance_monitor.registry._states[instance_id] = RuntimeState(
        instance_id=instance_id, base_url=base_url, capabilities=frozenset({"realtime"})
    )


def test_the_offer_reaches_the_selected_instance(dist, lb_proxy, monkeypatch):
    seen: list[str] = []

    async def fake(url, offer, **kwargs):
        seen.append(url)
        return httpx.Response(
            201,
            content=b"v=0\r\nanswer\r\n",
            headers={"content-type": "application/sdp", "location": "/v1/realtime/calls/c1"},
            request=httpx.Request("POST", url),
        )

    _register("pipe-a", "http://pipe-a:8765")
    monkeypatch.setattr("app.services.calls_service._http", fake)
    with TestClient(create_app()) as client:
        response = client.post("/api/calls", content=OFFER, headers={"Content-Type": "application/sdp"})
    assert response.status_code == 201
    assert seen == ["http://pipe-a:8765/v1/realtime/calls"]


def test_a_full_instance_is_retried_on_another_one(dist, lb_proxy, monkeypatch):
    seen: list[str] = []

    async def fake(url, offer, **kwargs):
        seen.append(url)
        if "pipe-a" in url:
            return httpx.Response(
                503,
                content=b'{"type":"error","error":{"type":"session_limit_reached"}}',
                headers={"content-type": "application/json"},
                request=httpx.Request("POST", url),
            )
        return httpx.Response(
            201,
            content=b"v=0\r\nanswer\r\n",
            headers={"content-type": "application/sdp", "location": "/v1/realtime/calls/c1"},
            request=httpx.Request("POST", url),
        )

    _register("pipe-a", "http://pipe-a:8765")
    _register("pipe-b", "http://pipe-b:8765")
    monkeypatch.setattr("app.services.calls_service._http", fake)
    with TestClient(create_app()) as client:
        response = client.post("/api/calls", content=OFFER, headers={"Content-Type": "application/sdp"})
    assert response.status_code == 201
    assert seen == ["http://pipe-a:8765/v1/realtime/calls", "http://pipe-b:8765/v1/realtime/calls"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd console/backend && python -m pytest tests/integration/test_calls_proxy.py -q`
Expected: FAIL —— `/api/calls` 现在只转发到 `demo.pinned_url`，未 pin 时直接 404。

- [ ] **Step 3: 改造 `calls_service.py`**

- 新增 `async def _http(url: str, offer: bytes, *, timeout: float = 15.0) -> httpx.Response`：**只加一个带默认值的 keyword-only 参数**。
  > **既有测试的兼容点**：`tests/integration/test_realtime_proxy.py:104` 的替身是 `async def fake(url, offer)`（两个位置参数、无 kwargs）。
  > 因此：**非 proxy 路径必须仍然调用 `_http(url, offer)`（不传 timeout）**，否则既有替身会因多余的 `timeout` 关键字而 TypeError。proxy 路径才调用 `_http(url, offer, timeout=...)`。
- 新增 `def handshake_url_for(base_url: str) -> str`：`base_url` → `http(s)://host/v1/realtime/calls`（复用现有 `handshake_url` 的映射表逻辑，但**以 base_url 为输入**而非 ws:// 形态）。
- 新增 `def is_full_response(response: httpx.Response) -> bool`：状态码 503 且响应体 JSON 的 `error.type == "session_limit_reached"`。
- 新增 `async def forward_offer(base_url: str, offer: bytes, *, keep_location: bool, timeout: float) -> httpx.Response`：调用 `_http` + 判定满员。

- [ ] **Step 4: 改造 `routers/demo/calls.py`**

```python
@router.post("/calls")
async def calls(request: Request):
    """目标只来自服务端：proxy 模式按注册表选台，否则用 env 钉死的地址。

    接受客户端传目标就是开放代理（SSRF），所以目标只能来自 env 或服务端选台。
    """
    offer = await request.body()
    if console.lb_mode == "proxy":
        return await calls_service.forward_selected(offer, keep_location=True)
    if not demo.pinned_url:
        raise HTTPException(status_code=404, detail="Not found.")
    return await calls_service.forward(
        calls_service.handshake_url(demo.pinned_url), offer, keep_location=True
    )
```

- [ ] **Step 5: 实现 `calls_service.forward_selected`（换台循环）**

```python
async def forward_selected(offer: bytes, *, keep_location: bool) -> Response:
    """proxy 模式：选台 → 转发 offer → 满员则换台。"""
    tried: set[str] = set()
    last = None
    for _ in range(console.lb_failover_attempts + 1):
        ranked = upstream_resolver.rank_session(
            store=allocator.store, capability="realtime", exclude=frozenset(tried), rng=allocator._rng
        )
        if not ranked:
            break
        spec = ranked[0]
        tried.add(spec.instance_id)
        url = handshake_url_for(spec.base_url)
        response = await _http(url, offer, timeout=console.lb_upstream_ready_timeout_s + 10)
        last = response
        if not is_full_response(response):
            break
    if last is None:
        raise HTTPException(status_code=503, detail="No speech instance is available.")
    headers = {}
    if keep_location and "location" in last.headers:
        headers["Location"] = last.headers["location"]
    return Response(
        content=last.content,
        status_code=last.status_code,
        media_type=last.headers.get("content-type", "application/sdp"),
        headers=headers,
    )
```

- [ ] **Step 6: 新增 `POST /v1/realtime/calls`**

在 `app/routers/realtime.py` 里加一条路由，与 `/api/calls` **共用 `calls_service.forward_selected`**（同源入口，供服务端/未来前端使用）：

```python
@router.post("/v1/realtime/calls", include_in_schema=False)
async def realtime_calls(request: Request):
    offer = await request.body()
    if console.lb_mode == "proxy":
        return await calls_service.forward_selected(offer, keep_location=True)
    return await calls_service.forward(calls_service.loopback_url(), offer, keep_location=False)
```

> `keep_location` 的差异：proxy 模式回填上游的 `/v1/realtime/calls/{id}`（**console 自己也注册了这个路径**，浏览器拿到可解析）；非 proxy 模式保持现状不回填（指向回环，浏览器拿不到）。

- [ ] **Step 7: 运行新测试确认通过**

Run: `cd console/backend && python -m pytest tests/integration/test_calls_proxy.py -q`
Expected: PASS（2 passed）

- [ ] **Step 8: 既有反代测试必须仍然通过**

Run: `cd console/backend && python -m pytest tests/integration/test_realtime_proxy.py -q`
Expected: PASS（4 passed）——`off` 模式行为不变（`test_the_sdp_offer_goes_to_loopback_without_a_location` 仍断言无 `location` 头）。

- [ ] **Step 9: 跑完整测试并提交**

```bash
cd console/backend && python -m pytest tests/unit tests/integration -q
git add console/backend/app/routers/demo/calls.py console/backend/app/routers/realtime.py console/backend/app/services/calls_service.py console/backend/tests/integration/test_calls_proxy.py
git commit -m "feat(console): route the WebRTC offer through the instance registry"
```

---

# Task 7：代理指标表 + 迁移 + 面板字段

**Files:**
- Create: `console/backend/app/models/param_proxy_metric.py`
- Create: `console/backend/app/repositories/proxy_metric_repository.py`
- Create: `console/backend/alembic/versions/0008_proxy_metrics.py`
- Create: `console/backend/tests/unit/test_proxy_metric_repository.py`
- Modify: `console/backend/app/models/__init__.py`
- Modify: `console/backend/app/models/comments.py`
- Modify: `console/backend/app/schemas/instance.py`
- Modify: `console/backend/app/services/instances_service.py`
- Modify: `console/backend/app/services/status_service.py`
- Modify: `console/backend/app/routers/instances.py`
- Modify: `console/backend/alembic/sql/init-sqlite.sql`、`init-postgresql.sql`（**生成物，不手改**）

**Interfaces:**
- Consumes: Task 1 的 `lb_*`；Task 3 的 `rank_stateless`
- Produces:
  - `app.models.param_proxy_metric.ParamProxyMetric` —— 表 `param_proxy_metric`，列：`id`、`instance_id`、`service`、`observed_at`、`observed_by`、`ok`、`fail_reason`、`duration_ms`
  - `app.repositories.proxy_metric_repository.ProxyMetricRepository`：`insert_many(rows: list[dict]) -> int`、`window(instance_id: str, *, since: datetime) -> list[ParamProxyMetric]`、`prune_before(cutoff: datetime) -> int`
  - `app.schemas.instance.proxy_metric_point(row) -> dict`
  - `GET /api/v1/instances/{id}/metrics?kind=proxy`（`kind` 缺省 `slots`，传 `proxy` 走新表）
  - `GET /api/v1/instances` → 每个 instance 对象内新增 `capabilities: list[str]`
  - `GET /api/v1/status` → 新增 `lbMode`、`lbUpstreams`、`lbCapabilities`

- [ ] **Step 1: 写失败测试**

```python
# console/backend/tests/unit/test_proxy_metric_repository.py
from datetime import UTC, datetime, timedelta

from app.repositories.proxy_metric_repository import ProxyMetricRepository


def test_rows_round_trip_and_window_filters(db_session):
    now = datetime.now(UTC)
    repo = ProxyMetricRepository(db_session)
    repo.insert_many(
        [
            {
                "instance_id": "pipe-a",
                "service": "asr",
                "observed_at": now - timedelta(minutes=5),
                "observed_by": "c1",
                "ok": 3,
                "fail_reason": "",
                "duration_ms": 120,
            },
            {
                "instance_id": "pipe-a",
                "service": "asr",
                "observed_at": now - timedelta(hours=2),
                "observed_by": "c1",
                "ok": 1,
                "fail_reason": "upstream_timeout",
                "duration_ms": 400,
            },
        ]
    )
    recent = repo.window("pipe-a", since=now - timedelta(hours=1))
    assert [r.service for r in recent] == ["asr"]
    assert recent[0].ok == 3
    assert recent[0].observed_by == "c1"


def test_prune_removes_only_the_old_rows(db_session):
    now = datetime.now(UTC)
    repo = ProxyMetricRepository(db_session)
    repo.insert_many(
        [
            {
                "instance_id": "pipe-a",
                "service": "tts",
                "observed_at": now - timedelta(days=9),
                "observed_by": "c1",
                "ok": 1,
                "fail_reason": "",
                "duration_ms": 10,
            },
            {
                "instance_id": "pipe-a",
                "service": "tts",
                "observed_at": now,
                "observed_by": "c1",
                "ok": 1,
                "fail_reason": "",
                "duration_ms": 10,
            },
        ]
    )
    assert repo.prune_before(now - timedelta(days=7)) == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd console/backend && python -m pytest tests/unit/test_proxy_metric_repository.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.repositories.proxy_metric_repository'`

- [ ] **Step 3: 实现模型与仓库**

`app/models/param_proxy_metric.py`：

```python
class ParamProxyMetric(Base):
    """console 数据面代理的采样：计数是窗口增量而非累计值。"""

    __tablename__ = "param_proxy_metric"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(64), nullable=False)
    service: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    observed_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    ok: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fail_reason: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
```

`app/repositories/proxy_metric_repository.py`：`insert_many` / `window` / `prune_before`，**照抄 `InstanceMetricRepository` 的写法**（`_as_aware` 时区归一化照抄 `instance_metric_repository.py:14-20`）。

- [ ] **Step 4: 注册模型与注释**

`app/models/__init__.py`：加 `from .param_proxy_metric import ParamProxyMetric` 与 `"ParamProxyMetric"` 到 `__all__`。

`app/models/comments.py`：**必须同步**，否则 `tests/unit/test_comments.py:25-29` 会失败：

- `TABLE_COMMENTS["param_proxy_metric"] = "console 数据面代理采样：按实例与服务记录成功数与失败原因"`
- `COLUMN_COMMENTS["param_proxy_metric"]` 逐列补齐（`id`、`instance_id`、`service`、`observed_at`、`observed_by`、`ok`、`fail_reason`、`duration_ms`），中文文案，**不含单引号、不含大写 TIMESTAMP**（该文件顶部的约束）。

- [ ] **Step 5: 写迁移 `0008_proxy_metrics.py`**

`revision = "0008_proxy_metrics"`，`down_revision = "0007_comments"`。

`upgrade()`：`op.create_table("param_proxy_metric", ...)`，列与模型一一对应；`op.create_index("ix_param_proxy_metric_instance_id", ...)` 与 `op.create_index("ix_param_proxy_metric_observed_at", ...)`。

`downgrade()`：反向 drop index + drop table。

> **注意**：`0005_instances.py` 的 `param_instance` 表里**没有** `cluster_id`（它在 `0006_clusters` 里加的）——新表不要犯同样的错，列要与模型严格一致（`test_schema_sql.py:57-74` 会逐列比对）。

- [ ] **Step 6: 重新生成双方言 init SQL**

```bash
cd console/backend && python scripts/dump_schema_sql.py
```

然后：

Run: `cd console/backend && python -m pytest tests/unit/test_schema_sql.py tests/unit/test_comments.py -q`
Expected: PASS

- [ ] **Step 7: 扩展实例与状态接口**

- `app/schemas/instance.py`：新增 `def proxy_metric_point(row) -> dict`，返回 `{"observedAt","observedBy","service","ok","failReason","durationMs"}`（键名用 camelCase，与 `metric_point` 一致）。
- `app/services/instances_service.py` 的 `_collect_registry`：每个 instance 字典新增 `"capabilities": sorted(state.capabilities) if state else []`。
- `app/services/status_service.py` 的 `snapshot()`：新增三个键
  - `"lbMode": console.lb_mode`
  - `"lbUpstreams": len([s for s in instance_monitor.registry.snapshot().values() if s.enabled and s.status in ("online", "degraded")])`
  - `"lbCapabilities": sorted(set().union(*(s.capabilities for s in instance_monitor.registry.snapshot().values())) if ... else set())`
- `app/routers/instances.py` 的 `GET /api/v1/instances/{id}/metrics`：加 `kind: str = "slots"` 参数；`kind == "proxy"` 时读 `ProxyMetricRepository(db).window(instance_id, since=since)` 并返回 `{"instance_id","window","kind":"proxy","points":[proxy_metric_point(r) for r in rows]}`；其它值返回 400 `invalid_request`。**`kind` 的其它取值按 400 处理**（不猜）。

- [ ] **Step 8: 写一条接口测试**

在 `console/backend/tests/integration/test_instances_admin_api.py`（或新建 `test_proxy_metrics_api.py`）追加：注册一个实例 → 插入两行 proxy metric → `GET /api/v1/instances/{id}/metrics?kind=proxy` → 断言 `points` 里有 `service` 与 `ok`；`kind=bogus` → 400。

- [ ] **Step 9: 跑全部测试**

Run: `cd console/backend && python -m pytest tests/unit tests/integration -q`
Expected: PASS

- [ ] **Step 10: 提交**

```bash
git add console/backend/app/models console/backend/app/repositories/proxy_metric_repository.py console/backend/app/schemas/instance.py console/backend/app/services/instances_service.py console/backend/app/services/status_service.py console/backend/app/routers/instances.py console/backend/alembic/versions/0008_proxy_metrics.py console/backend/alembic/sql console/backend/tests/unit/test_proxy_metric_repository.py
git commit -m "feat(console): record data-plane proxy metrics per instance and service"
```

---

# Task 8：入口切换 + compose 收敛 + 文档

**Files:**
- Modify: `config/prod.env`（清空 `SPEECH_TO_SPEECH_URL`）
- Modify: `docker-compose.yml`（删 `8765` publish）
- Modify: `console/backend/.env.example`
- Modify: `docs/console-service.md`
- Modify: `console/README.md`

**Interfaces:**
- Consumes: Task 5 已上线且验证通过（`CONSOLE_LB_MODE=proxy` 在生产跑通）
- Produces: 无代码接口

- [ ] **Step 1: 在 `console/backend/.env.example` 补齐新配置**

新增（全部带默认值，注释说明"默认 off = 现状"）：

```dotenv
# ── S2S 数据面负载均衡（默认 off = 现状：浏览器直连 8765，console 不代理）──
CONSOLE_LB_MODE=off
LB_FAILOVER_ATTEMPTS=2
LB_UPSTREAM_READY_TIMEOUT_S=5
LB_ASR_TIMEOUT_S=120
LB_TTS_TIMEOUT_S=120
LB_VOICEPRINT_TIMEOUT_S=30
LB_EMOTION_TIMEOUT_S=30
LB_AUDIO_MAX_BYTES=11534336
LB_CAPABILITY_INTERVAL_S=30
LB_CAPABILITY_PROBE_TIMEOUT_S=6
LB_STATELESS_MAX_INFLIGHT=0
```

- [ ] **Step 2: 清空 `config/prod.env` 的 pin**

把 `config/prod.env:21` 的

```
SPEECH_TO_SPEECH_URL="ws://localhost:8765/v1/realtime"
```

改成

```
# 留空 = 浏览器走同源 /v1/realtime，由 console 反代并选台（console/README.md 的既定做法）。
# 填值会把浏览器钉到某个直连地址，并让 demo 面的 LB 分支整体关闭（config/_demo.py:32-34）。
SPEECH_TO_SPEECH_URL=
```

> **这一步是 8765 收敛的前置条件**：pin 非空时 `allowDirect=true` 且 `s2sUrl` 指向 8765，浏览器**绕过 console**（`demo_config_service.py:36-37` + `s2s-client.ts:260-265`）。清空后 `allowDirect` 仍为 true，但 `directSocketUrl()` 回落 `sameOriginRealtimeUrl()` → 打到 console。

- [ ] **Step 3: 删掉 compose 的 8765 publish**

`docker-compose.yml`：把

```yaml
      - "8765:8765/tcp"
```

整行删除，**保留** `expose:` 段里的 `8765/tcp`（容器内可达）。

**只改这一个 compose**。`docker-compose.local.yml` / `.baked*.yml` / `.cu130.yml` / `.gpustack.yml` / `.llm-bundled.yml` / `.vn.ms.llm-bundled.yml` / `.thirdparty.yml` / `.voiceprint.yml` **一律不动**（它们有外部直连调用方，spec §8 表格已逐个写死）。

- [ ] **Step 4: 验证 compose 仍然起得来**

```bash
python -c "import yaml,io; yaml.safe_load(io.open('docker-compose.yml', encoding='utf-8')); print('OK')"
```

Expected: 输出 `OK`（YAML 合法）。

> 本机若装了 docker，可再加 `docker compose -f docker-compose.yml config > /dev/null` 做一次完整展开；该命令依赖 `config/prod.env` 与若干 env 变量，缺失时会因无关原因失败，**不作为验收门槛**。

- [ ] **Step 5: 更新 `docs/console-service.md`**

新增一节（或在 §5.3 后插入）说明：

- `CONSOLE_LB_MODE` 的两种模式与降级规则（spec §4.2 的三条）
- 端点代理矩阵（spec §4.3 的表）
- 三种 WS 终态（spec §5.3 的表）与"WS 阶段没有 HTTP 503"
- REST 错误码表（spec 附录 B）
- 8765 收敛清单与"哪些 compose 不收敛"的理由
- 灰度步骤（spec §12 的 5 步）与回滚表（L1/L1'/L2/L3）
- 常见故障新增两条：
  - `浏览器语音连不上` → 查 `CONSOLE_LB_MODE`、`ALLOCATOR_MODE`、实例页的 `capabilities` 列
  - `声纹返回 503` → 该实例没配 `VOICEPRINT_API_KEY`（spec §5.1 判定表）

- [ ] **Step 6: 更新 `console/README.md`**

在 "Pointing the console at a local pipeline-1" 一节补一段：`SPEECH_TO_SPEECH_URL` 留空时浏览器走同源反代；`CONSOLE_LB_MODE=proxy` 时 console 按注册表选台；`8765` 不再 publish 的影响与本地调试怎么临时开回来。

- [ ] **Step 7: 提交（拆成两次，便于回滚）**

```bash
git add console/backend/.env.example config/prod.env
git commit -m "chore(console): switch the browser entry to the same-origin proxy"
```

```bash
git add docker-compose.yml docs/console-service.md console/README.md
git commit -m "chore(console): retract the 8765 publish and document the LB modes"
```

---

## 自查（对照 spec 逐节）

| spec 节 | 实现于 |
|---|---|
| §4.1 数据流 | Task 3（选台）+ Task 4/5（转发） |
| §4.2 模式与开关、降级规则 | Task 1（配置）+ Task 4/5（分支）+ Task 8（切入口） |
| §4.3 端点代理矩阵 | Task 4（WS）、Task 5（4 条 audio + 2 条 health/capability）、Task 6（calls） |
| §4.4 路由注册顺序 | Task 5 Step 5、Task 6 Step 6 |
| §5.1 能力指纹 | Task 2 |
| §5.2 两套选台策略 | Task 3 |
| §5.3 WS 静默换台 + 三终态 + hold/release | Task 3（hold）+ Task 4 |
| §5.4 REST 反代 | Task 5 |
| §5.5 WebRTC 选台与换台 | Task 6 |
| §5.6 前端入口分流 | Task 8 Step 2（`prod.env`）；前端零改动 |
| §5.7 控制面不动 | 无代码改动（已在 Global Constraints 声明） |
| §6.1 配置项 | Task 1（11 项）+ Task 8（`.env.example`） |
| §6.2 数据模型 | Task 7（新表 + 迁移）+ Task 3（`hold`） |
| §6.3 seed 不变 | 无改动（Global Constraints 已声明） |
| §7 观测与指标 | Task 5/6（日志）+ Task 7（指标与面板） |
| §8 安全收敛 | Task 8 Step 2/3 |
| §9 失败模式 | 各任务的错误映射测试 |
| §10 交付拆分 | Task 1–8 |
| §11 测试矩阵 | 各任务的测试步骤 + Review Focus 五条 |
| §12 灰度与回滚 | Task 8 Step 5（文档） |
| §14 本期不做 | 无任务（Global Constraints + 文档声明） |
| 附录 A 端点清点 | Task 5 `SERVICES` 映射表 |
| 附录 B 错误码 | Task 5 Step 3 的错误体 |

**已知不在本计划内**（spec §14 明确不做）：共享分配状态（Phase 2）、数据面 DELETE 路由、声明式能力上界、跨机参数 fanout、nginx 配置文件、console 拆分为独立网关进程、声纹密钥前置校验。
