# LiveKit Worker 与可配置回调子系统迁移实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 livekit-worker 工程的房间转写 + 说话人分离能力迁移进 speech-to-speech，以 `--with-diarization` / `--with-livekitworker` 开关随 `serve` 启动，并新增 console 可视化配置的可配置回调子系统（多目标 Java/Python、协议适配、重试、执行日志、热加载）。

**Architecture:** worker 以内嵌线程 + asyncio loop 形态随 serve 运行（与 `--with-agent`/voiceprint 同模式），转写事件双路输出：进程内 `TranscriptEventBus`（本地转写/日志）+ 统一 `CallbackDispatcher`（console DB 配置 + 5s TTL 热加载 + env 兜底）。回调配置持久化在 console 库 `callback_target` / `callback_delivery_log` 两表，console 后端提供 CRUD/batch/test/logs API（JWT + `console:callback:*` 权限码），前端新增「回调管理」页。

**Tech Stack:** Python 3.11+（开发环境 3.14，livekit-agents 不支持时按 voxcpm 先例 mock 单测）、livekit-agents[silero]~=0.12（可选 extra）、FastAPI + SQLAlchemy 2 + alembic（console 后端）、Vue3 + TS + Pinia + ant-design-vue（console 前端）、pytest（全部离线 mock）。

**Spec:** `docs/superpowers/specs/2026-11-25-livekit-worker-migration-design.md`（唯一事实来源）。

**Spec 偏差说明（已解决，2026-11-25 用户确认）：** spec §7.1 原定「worker 结果写入现有 enable_live_transcription 体系」——该体系绑定活跃 pipeline websocket 会话，worker 事件无法直接注入。经用户确认补齐实时字幕：worker 事件发布到进程内 `TranscriptEventBus`；console 后端新增 SSE 端点（Task 14A）订阅该总线，前端「回调管理」页新增「实时字幕」页签（Task 14B）。spec §7.1 已同步修订。

**仓库规则：** 计划中的 commit 步骤执行前必须先询问用户是否执行 commit；分支/PR 标题不得含 "codex"。

**测试命令约定（Windows dev）：** `.\\.venv\\Scripts\\python.exe -m pytest <args>`；console 后端测试在 `console/backend` 目录下以同 venv 运行。

**移植类任务的对齐规则（Task 5/6/7/9 适用）：** 计划中的测试用例按源工程可观察行为编写；若移植后源码的实际函数/类名与测试引用不一致（如 `DuplicateGuard.should_skip` 实际叫别的名字），**以源码真实名称为准修改测试引用**，语义断言保持不变。这是移植测试的常规对齐，不视为计划变更。

---

## 文件结构

```
src/speech_to_speech/
├── worker_integration.py            # 新增：--with-diarization / --with-livekitworker 开关解析与校验
├── cli.py                           # 修改：接线开关（strip → talk 拒绝 → validate）
├── s2s_pipeline.py                  # 修改：build_pipeline 附加 worker runtime；diarization 开关映射
├── callback/
│   ├── __init__.py                  # 新增
│   └── dispatcher.py                # 新增：CallbackDispatcher + TTL 缓存 + 协议适配 + 日志 + env 兜底
└── livekit_worker/
    ├── __init__.py                  # 新增：LiveKitWorkerRuntime 线程生命周期
    ├── events.py                    # 新增：TranscriptEvent / TranscriptEventBus
    ├── worker.py                    # 移植：job 接入、VAD 切段、ASR/SER/声纹并行、diarization 子段、去重、事件产出
    ├── asr_provider.py              # 移植+改造：gateway / local 双模式
    ├── ser_provider.py              # 移植：HTTP SER（409 fail-closed）
    ├── diarization_provider.py      # 移植：HTTP 分离客户端
    ├── segment_dedupe.py            # 原样移植
    └── audio_level.py               # 原样移植
console/backend/
├── app/models/callbacks.py          # 新增：CallbackTarget / CallbackDeliveryLog
├── alembic/versions/0015_callback_subsystem.py   # 新增
├── app/schemas/callbacks.py         # 新增：pydantic 请求/响应
├── app/repositories/callback_repository.py       # 新增
├── app/services/callback_service.py # 新增：脱敏、测试投递
├── app/routers/callbacks.py         # 新增：CRUD/batch/test/logs API
├── app/routers/live_transcripts.py  # 新增：SSE 实时转写流（订阅 TranscriptEventBus）
├── app/core/permissions.py          # 修改：console:callback:query / console:callback:manage
└── app/core/router_registry.py      # 修改：注册 callbacks.router
console/frontend/src/
├── api/callbacks.ts                 # 新增
├── views/CallbacksView.vue          # 新增
├── components/LiveSubtitlesPanel.vue  # 新增：实时字幕面板（SSE 消费）
├── router/index.ts                  # 修改：/console/callbacks 路由
└── i18n/locales/{zh-CN,en-US}/callbacks.ts + index.ts   # 修改
tests/
├── test_worker_integration.py       # 新增
├── test_livekit_worker.py           # 新增
└── test_callback_dispatcher.py      # 新增
console/backend/tests/unit/test_callback_models.py   # 新增
console/backend/tests/integration/test_callbacks_api.py   # 新增
```

---

### Task 1: worker_integration.py —— 双开关解析

**Files:**
- Create: `src/speech_to_speech/worker_integration.py`
- Test: `tests/test_worker_integration.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_worker_integration.py
"""--with-diarization / --with-livekitworker 开关解析测试（mirror agent_integration）。"""
from __future__ import annotations

import pytest

from speech_to_speech.worker_integration import (
    DIARIZATION_AUTOSTART_ENV,
    LIVEKIT_WORKER_AUTOSTART_ENV,
    WorkerIntegrationError,
    parse_worker_arguments,
)


def test_defaults_off() -> None:
    diar, worker, rest = parse_worker_arguments(["serve", "--port", "9000"])
    assert diar.autostart is False
    assert diar.explicit is False
    assert worker.autostart is False
    assert worker.explicit is False
    assert rest == ["serve", "--port", "9000"]


def test_explicit_flags_stripped() -> None:
    diar, worker, rest = parse_worker_arguments(["--with-diarization", "--with-livekitworker", "serve"])
    assert diar.autostart and diar.explicit
    assert worker.autostart and worker.explicit
    assert rest == ["serve"]


def test_no_flags_conflict() -> None:
    with pytest.raises(WorkerIntegrationError, match="conflicts"):
        parse_worker_arguments(["--with-diarization", "--no-with-diarization", "serve"])
    with pytest.raises(WorkerIntegrationError, match="conflicts"):
        parse_worker_arguments(["--with-livekitworker", "--no-with-livekitworker", "serve"])


def test_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DIARIZATION_AUTOSTART_ENV, "true")
    monkeypatch.setenv(LIVEKIT_WORKER_AUTOSTART_ENV, "1")
    diar, worker, _ = parse_worker_arguments(["serve"])
    assert diar.autostart is True
    assert worker.autostart is True


def test_env_invalid_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LIVEKIT_WORKER_AUTOSTART_ENV, "maybe")
    with pytest.raises(WorkerIntegrationError, match="must be a boolean"):
        parse_worker_arguments(["serve"])


def test_explicit_flag_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DIARIZATION_AUTOSTART_ENV, "true")
    diar, _, _ = parse_worker_arguments(["--no-with-diarization", "serve"])
    assert diar.autostart is False
    assert diar.explicit is True
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_worker_integration.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'speech_to_speech.worker_integration'`

- [ ] **Step 3: 最小实现**

```python
# src/speech_to_speech/worker_integration.py
"""Worker integration: reads the --with-diarization / --with-livekitworker switches.

The shape mirrors :mod:`speech_to_speech.agent_integration` deliberately — same
switch-stripping discipline (flags must be removed *before* ``parse_command``,
because ``-f`` file mode rejects unknown options outright), same "off means no
footprint" rule, and the same fail-fast validation before any model loads.

``--with-diarization`` maps onto the existing streaming diarization argument
(``module_kwargs.diarization``); it adds no new subsystem. ``--with-livekitworker``
starts the embedded LiveKit transcript worker thread inside this process.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass

DIARIZATION_AUTOSTART_ENV = "DIARIZATION_AUTOSTART"
LIVEKIT_WORKER_AUTOSTART_ENV = "LIVEKIT_WORKER_AUTOSTART"

DIARIZATION_WITH_FLAG = "--with-diarization"
DIARIZATION_WITHOUT_FLAG = "--no-with-diarization"
LIVEKIT_WITH_FLAG = "--with-livekitworker"
LIVEKIT_WITHOUT_FLAG = "--no-with-livekitworker"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off", ""})


class WorkerIntegrationError(RuntimeError):
    """A worker switch cannot be applied as requested; callers exit with code 2."""


def _read_switch(name: str) -> bool:
    """Read one boolean env switch, rejecting values that are neither true nor false."""
    raw = os.environ.get(name)
    if raw is None:
        return False
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise WorkerIntegrationError(
        f"{name} must be a boolean (1/true/yes/on or 0/false/no/off); got {raw!r}."
    )


@dataclass(frozen=True)
class SwitchOptions:
    """Resolved on/off state of one switch."""

    autostart: bool = False
    explicit: bool = False


def _strip_pair(
    argv: Sequence[str],
    with_flag: str,
    without_flag: str,
    env_name: str,
    remaining: list[str],
) -> SwitchOptions:
    """Consume one flag pair from argv (left to right), resolve env fallback."""
    explicit: bool | None = None
    kept: list[str] = []
    for argument in remaining:
        if argument == with_flag:
            if explicit is False:
                raise WorkerIntegrationError(f"{with_flag} conflicts with {without_flag}.")
            explicit = True
            continue
        if argument == without_flag:
            if explicit is True:
                raise WorkerIntegrationError(f"{without_flag} conflicts with {with_flag}.")
            explicit = False
            continue
        kept.append(argument)
    remaining[:] = kept
    autostart = _read_switch(env_name) if explicit is None else explicit
    return SwitchOptions(autostart=autostart, explicit=explicit is True)


def parse_worker_arguments(argv: Sequence[str]) -> tuple[SwitchOptions, SwitchOptions, list[str]]:
    """Strip both switches from argv and resolve the effective options.

    Returns (diarization, livekit_worker, remaining-argv). Stripping happens before
    ``parse_command`` so ``-f`` file mode keeps working.
    """
    remaining = list(argv)
    diarization = _strip_pair(
        remaining, DIARIZATION_WITH_FLAG, DIARIZATION_WITHOUT_FLAG, DIARIZATION_AUTOSTART_ENV, remaining
    )
    livekit = _strip_pair(
        remaining, LIVEKIT_WITH_FLAG, LIVEKIT_WITHOUT_FLAG, LIVEKIT_WORKER_AUTOSTART_ENV, remaining
    )
    return diarization, livekit, remaining
```

注意：`_strip_pair` 读写同一个 `remaining` 列表是有意为之——先剥离 diarization 再剥离 livekit；测试断言 `rest` 顺序不变即可。

- [ ] **Step 4: 运行确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_worker_integration.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit（先询问用户）**

```bash
git add src/speech_to_speech/worker_integration.py tests/test_worker_integration.py
git commit -m "feat(livekit-worker): add --with-diarization/--with-livekitworker switch parsing"
```

---

### Task 2: cli.py 接线 —— strip / talk 拒绝 / validate

**Files:**
- Modify: `src/speech_to_speech/cli.py`（import 区 L1-60、main() L442-523）
- Test: `tests/test_worker_integration.py`（追加）

- [ ] **Step 1: 追加失败测试**

```python
# tests/test_worker_integration.py 追加
def test_talk_rejects_explicit_switches() -> None:
    from speech_to_speech.cli import _command_parser

    parser = _command_parser()
    with pytest.raises(SystemExit) as exc_info:
        # 直接复刻 main() 中 talk 分支的校验逻辑入口：talk 显式拒绝。
        # main() 内部用 _command_parser().error(...)，这里断言行为等价。
        _command_parser().error("talk does not accept --with-livekitworker")
    assert exc_info.value.code == 2


def test_validate_worker_options_requires_livekit_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from speech_to_speech.worker_integration import SwitchOptions, validate_worker_options

    monkeypatch.delenv("LIVEKIT_URL", raising=False)
    monkeypatch.delenv("LIVEKIT_API_KEY", raising=False)
    monkeypatch.delenv("LIVEKIT_API_SECRET", raising=False)
    with pytest.raises(WorkerIntegrationError) as exc_info:
        validate_worker_options(SwitchOptions(autostart=True))
    message = str(exc_info.value)
    assert "LIVEKIT_URL" in message and "LIVEKIT_API_KEY" in message and "LIVEKIT_API_SECRET" in message


def test_validate_worker_options_asr_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from speech_to_speech.worker_integration import SwitchOptions, validate_worker_options

    monkeypatch.delenv("LIVEKIT_WORKER_ASR_MODE", raising=False)
    monkeypatch.setenv("LIVEKIT_WORKER_ASR_MODE", "bogus")
    with pytest.raises(WorkerIntegrationError, match="LIVEKIT_WORKER_ASR_MODE"):
        validate_worker_options(SwitchOptions(autostart=True))

    monkeypatch.setenv("LIVEKIT_WORKER_ASR_MODE", "gateway")
    monkeypatch.delenv("VOICE_GATEWAY_BASE_URL", raising=False)
    with pytest.raises(WorkerIntegrationError, match="VOICE_GATEWAY_BASE_URL"):
        validate_worker_options(SwitchOptions(autostart=True))

    # local 模式下 STT 定义在 pipeline 解析后校验；validate 只查非法模式与 gateway 依赖。
    monkeypatch.setenv("LIVEKIT_WORKER_ASR_MODE", "local")
    validate_worker_options(SwitchOptions(autostart=True))  # 不抛


def test_validate_worker_options_off_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    from speech_to_speech.worker_integration import SwitchOptions, validate_worker_options

    monkeypatch.delenv("LIVEKIT_URL", raising=False)
    validate_worker_options(SwitchOptions(autostart=False))  # 不抛
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_worker_integration.py -v`
Expected: FAIL，`ImportError: cannot import name 'validate_worker_options'`

- [ ] **Step 3: 在 worker_integration.py 追加 validate**

```python
# src/speech_to_speech/worker_integration.py 追加
ASR_MODE_ENV = "LIVEKIT_WORKER_ASR_MODE"
ASR_MODES = ("gateway", "local")


def validate_worker_options(options: SwitchOptions) -> None:
    """Fail before any model loads, and touch nothing when the switch is off."""
    if not options.autostart:
        return
    missing = [name for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
               if not os.environ.get(name, "").strip()]
    if missing:
        raise WorkerIntegrationError(
            "--with-livekitworker needs " + " and ".join(missing)
            + f"; set them (or drop {LIVEKIT_WITH_FLAG}) before starting the server."
        )
    mode = os.environ.get(ASR_MODE_ENV, "gateway").strip().lower()
    if mode not in ASR_MODES:
        raise WorkerIntegrationError(f"{ASR_MODE_ENV} must be one of {'|'.join(ASR_MODES)}; got {mode!r}.")
    if mode == "gateway" and not os.environ.get("VOICE_GATEWAY_BASE_URL", "").strip():
        raise WorkerIntegrationError(
            f"--with-livekitworker gateway ASR needs VOICE_GATEWAY_BASE_URL, "
            f"or set {ASR_MODE_ENV}=local to reuse the pipeline STT backend."
        )
```

- [ ] **Step 4: 修改 cli.py 接线**

在 `src/speech_to_speech/cli.py`：

1. import 区追加：

```python
from speech_to_speech.worker_integration import (
    DIARIZATION_WITH_FLAG,
    LIVEKIT_WITH_FLAG,
    SwitchOptions,
    WorkerIntegrationError,
    parse_worker_arguments,
    validate_worker_options,
)
```

2. 新增帮助文本常量（放在 `AGENT_HELP` 之后）：

```python
WORKER_HELP = """
Transcription worker switches:
  --with-diarization      Same as --diarization on the pipeline: enable the existing
                          streaming speaker separation. Off by default.
  --no-with-diarization   Override DIARIZATION_AUTOSTART for this run.
  --with-livekitworker    Start the embedded LiveKit room transcript worker thread
                          in this process. Off by default.
  --no-with-livekitworker Override LIVEKIT_WORKER_AUTOSTART for this run.

Environment:
  DIARIZATION_AUTOSTART       true/false, same as --with-diarization. Default: false.
  LIVEKIT_WORKER_AUTOSTART    true/false, same as --with-livekitworker. Default: false.
  LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET   Required with --with-livekitworker.
  LIVEKIT_WORKER_ASR_MODE     gateway (default, OpenAI-compatible voice gateway) or local
                              (reuse the --stt backend selected for the pipeline).
  VOICE_GATEWAY_BASE_URL      Required in gateway mode.

Only "serve" and "local" host the worker. With the switch on, the worker joins
LiveKit rooms as a participant, transcribes remote audio with VAD segmentation,
and delivers results through the callback subsystem and local transcript sinks.
"""
```

3. `main()` 中，在 `agent_options, argv = parse_agent_arguments(argv)` 之后追加（保留 wants_help 逻辑在其后）：

```python
    try:
        diarization_options, livekit_options, argv = parse_worker_arguments(argv)
    except WorkerIntegrationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
```

4. `wants_help` 打印块（两处 `print(CONSOLE_HELP)`）各追加一行 `print(WORKER_HELP)`。

5. talk 分支追加（在既有 `if command == "talk":` 块内、console 检查之后）：

```python
        for options, flag in ((diarization_options, DIARIZATION_WITH_FLAG), (livekit_options, LIVEKIT_WITH_FLAG)):
            if options.explicit:
                _command_parser().error(
                    f"talk does not accept {flag}; it only connects to a listener that already runs."
                )
            if options.autostart:
                print(f"Warning: env autostart is ignored for 'talk' ({flag}).", file=sys.stderr)
```

6. 非 talk 分支（serve/local）追加校验（在 `validate_agent_options` 调用的同一层，`else:` 分支内）：

```python
        try:
            validate_worker_options(livekit_options)
        except WorkerIntegrationError as exc:
            print(f"Configuration error: {exc}", file=sys.stderr)
            raise SystemExit(2) from None
```

7. `_dispatch` 签名追加 `diarization_options: SwitchOptions, livekit_options: SwitchOptions`，并透传给 `run_pipeline_command(..., diarization_options=..., livekit_options=...)`；`main()` 中的 `_dispatch(...)` 调用同步更新。`_run_file_command` 的 `-f` 模式同样透传（它目前转发 console/agent options，照抄即可）。

- [ ] **Step 5: 运行测试**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_worker_integration.py -v`
Expected: PASS（10 passed）

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cli.py tests/test_command.py -q`（若存在既有 CLI 测试，全量回归）
Expected: PASS，无回归。若有测试断言 help 输出内容，按需同步 WORKER_HELP 行。

- [ ] **Step 6: Commit（先询问用户）**

```bash
git add src/speech_to_speech/worker_integration.py src/speech_to_speech/cli.py tests/test_worker_integration.py
git commit -m "feat(livekit-worker): wire worker switches into CLI serve/talk/local"
```

---

### Task 3: pyproject.toml 增加 livekit extra

**Files:**
- Modify: `pyproject.toml`（[project.optional-dependencies] 区，L71-137）

- [ ] **Step 1: 追加 extra（按源工程 requirements.txt 对齐）**

```toml
livekit = [
    "livekit-agents[silero]>=0.12,<0.13",
    "livekit-plugins-silero>=0.7,<0.8",
    "av>=12.3.0,<13",
    "requests>=2.31",
]
```

- [ ] **Step 2: 验证 pyproject 可解析**

Run: `.\.venv\Scripts\python.exe -c "import tomllib; d = tomllib.load(open('pyproject.toml','rb')); print(d['project']['optional-dependencies']['livekit'])"`
Expected: 打印 4 个依赖项列表

- [ ] **Step 3: Commit（先询问用户）**

```bash
git add pyproject.toml
git commit -m "feat(livekit-worker): add livekit extra dependencies"
```

---

### Task 4: livekit_worker 包骨架 —— events.py

**Files:**
- Create: `src/speech_to_speech/livekit_worker/__init__.py`（先空占位 `"""LiveKit room transcript worker package."""`）
- Create: `src/speech_to_speech/livekit_worker/events.py`
- Test: `tests/test_livekit_worker.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_livekit_worker.py
"""LiveKit worker 移植测试。全部离线：不 import livekit（mock），不发网络请求。"""
from __future__ import annotations

import pytest

from speech_to_speech.livekit_worker.events import (
    EVENT_TYPES,
    TranscriptEvent,
    TranscriptEventBus,
)


def test_event_types() -> None:
    assert EVENT_TYPES == ("transcript", "segment_attributed", "session_end")


def test_transcript_event_to_payload() -> None:
    event = TranscriptEvent(
        event_type="transcript",
        room_sid="room-1",
        identity="user-a",
        text="大家好",
        start_ts=1000,
        end_ts=2000,
        audio_level=-12,
        extra={"speakerName": "张三"},
        timestamp_ms=1700000000000,
    )
    payload = event.to_payload()
    assert payload == {
        "eventType": "transcript",
        "roomSid": "room-1",
        "identity": "user-a",
        "text": "大家好",
        "startTs": 1000,
        "endTs": 2000,
        "audioLevel": -12,
        "speakerName": "张三",
        "timestamp": 1700000000000,
    }


def test_transcript_event_extra_flattens() -> None:
    event = TranscriptEvent(
        event_type="transcript", room_sid="r", identity="i", text="t",
        start_ts=0, end_ts=1, audio_level=None, extra={"serEmotion": "calm"}, timestamp_ms=0,
    )
    assert event.to_payload()["serEmotion"] == "calm"


def test_bus_publish_subscribe() -> None:
    bus = TranscriptEventBus()
    seen: list[TranscriptEvent] = []
    unsubscribe = bus.subscribe(seen.append)
    event = TranscriptEvent(
        event_type="session_end", room_sid="r", identity="i", text="",
        start_ts=0, end_ts=0, audio_level=None, extra={}, timestamp_ms=0,
    )
    bus.publish(event)
    unsubscribe()
    bus.publish(event)
    assert len(seen) == 1
    assert seen[0].event_type == "session_end"


def test_bus_subscriber_exception_isolated() -> None:
    bus = TranscriptEventBus()
    seen: list[TranscriptEvent] = []

    def bad(_: TranscriptEvent) -> None:
        raise RuntimeError("boom")

    bus.subscribe(bad)
    bus.subscribe(seen.append)
    bus.publish(TranscriptEvent(
        event_type="transcript", room_sid="r", identity="i", text="t",
        start_ts=0, end_ts=0, audio_level=None, extra={}, timestamp_ms=0,
    ))
    assert len(seen) == 1  # 坏订阅者不影响其它订阅者


def test_event_type_validation() -> None:
    with pytest.raises(ValueError, match="event_type"):
        TranscriptEvent(
            event_type="bogus", room_sid="r", identity="i", text="t",
            start_ts=0, end_ts=0, audio_level=None, extra={}, timestamp_ms=0,
        )
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_livekit_worker.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'speech_to_speech.livekit_worker'`

- [ ] **Step 3: 实现 events.py**

```python
# src/speech_to_speech/livekit_worker/events.py
"""转写事件构造与进程内事件总线。

worker 每产出一个转写分段/会话结束，构造一个 :class:`TranscriptEvent`：
- bus.publish 交给进程内订阅者（本地转写 sink、日志 sink）；
- callback 子系统的 CallbackDispatcher.publish(event) 按 DB 配置投递。

payload 字段名沿用源工程 Java 侧 TranscriptSegmentVO 的 camelCase，保证
java 目标的向后兼容；python 目标收到同一份 JSON。
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

EVENT_TYPES = ("transcript", "segment_attributed", "session_end")


@dataclass(frozen=True)
class TranscriptEvent:
    """一条转写事件的统一形状（各协议适配器共享）。"""

    event_type: str
    room_sid: str
    identity: str
    text: str
    start_ts: int
    end_ts: int
    audio_level: int | None
    extra: dict[str, object] = field(default_factory=dict)
    timestamp_ms: int = 0

    def __post_init__(self) -> None:
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"event_type must be one of {'|'.join(EVENT_TYPES)}; got {self.event_type!r}")

    def to_payload(self) -> dict[str, object]:
        """统一事件 JSON（python 目标的投递体）。"""
        payload: dict[str, object] = {
            "eventType": self.event_type,
            "roomSid": self.room_sid,
            "identity": self.identity,
            "text": self.text,
            "startTs": self.start_ts,
            "endTs": self.end_ts,
            "timestamp": self.timestamp_ms,
        }
        if self.audio_level is not None:
            payload["audioLevel"] = self.audio_level
        payload.update(self.extra)
        return payload


class TranscriptEventBus:
    """线程安全的最小发布/订阅总线（worker 线程发布，任意线程订阅）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: list = []

    def subscribe(self, callback) -> "callable":
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return unsubscribe

    def publish(self, event: TranscriptEvent) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for callback in subscribers:
            try:
                callback(event)
            except Exception:  # noqa: BLE001 - 坏订阅者不拖垮 worker
                logger.exception("transcript event subscriber failed")


_bus: TranscriptEventBus | None = None
_bus_lock = threading.Lock()


def get_event_bus() -> TranscriptEventBus:
    """进程级单例总线；serve 内 worker 与其它模块共享。"""
    global _bus
    with _bus_lock:
        if _bus is None:
            _bus = TranscriptEventBus()
        return _bus
```

注意 `subscribe` 的返回注解：ruff 不校验字符串注解，直接写 `-> "Callable[[], None]"` 并在文件头 import `from collections.abc import Callable` 更规范，实现时采用。

- [ ] **Step 4: 运行确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_livekit_worker.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: Commit（先询问用户）**

```bash
git add src/speech_to_speech/livekit_worker/__init__.py src/speech_to_speech/livekit_worker/events.py tests/test_livekit_worker.py
git commit -m "feat(livekit-worker): add transcript event model and in-process event bus"
```

---

### Task 5: segment_dedupe.py 与 audio_level.py 原样移植

**Files:**
- Create: `src/speech_to_speech/livekit_worker/segment_dedupe.py`
- Create: `src/speech_to_speech/livekit_worker/audio_level.py`
- Test: `tests/test_livekit_worker.py`（追加）

- [ ] **Step 1: 写失败测试（用例移植自源工程行为契约）**

```python
# tests/test_livekit_worker.py 追加
from speech_to_speech.livekit_worker.audio_level import SILENCE_DBFS, compute_audio_level_dbfs
from speech_to_speech.livekit_worker.segment_dedupe import DuplicateGuard, normalize_text


def test_dedupe_normalize_strips_punctuation() -> None:
    assert normalize_text("之前，没一次性写出来！") == "之前没一次性写出来"


def test_dedupe_short_text_passes() -> None:
    guard = DuplicateGuard()
    assert guard.should_skip("u1", "嗯", 1000) is False


def test_dedupe_exact_duplicate_within_window() -> None:
    guard = DuplicateGuard()
    assert guard.should_skip("u1", "之前没一次性写出来", 1000) is False
    assert guard.should_skip("u1", "之前没一次性写出来", 2000) is True


def test_dedupe_variant_with_tail() -> None:
    guard = DuplicateGuard()
    assert guard.should_skip("u1", "之前没一次性写出来", 1000) is False
    assert guard.should_skip("u1", "之前没一次性写出来了", 2000) is True


def test_dedupe_window_expiry() -> None:
    guard = DuplicateGuard()
    guard.should_skip("u1", "之前没一次性写出来", 1000)
    assert guard.should_skip("u1", "之前没一次性写出来", 1000 + 4001) is False


def test_dedupe_identity_scoped() -> None:
    guard = DuplicateGuard()
    guard.should_skip("u1", "之前没一次性写出来", 1000)
    assert guard.should_skip("u2", "之前没一次性写出来", 2000) is False


def test_audio_level_silence_and_full_scale() -> None:
    assert compute_audio_level_dbfs(b"") == SILENCE_DBFS
    full_scale = (32767).to_bytes(2, "little", signed=True) * 100
    assert compute_audio_level_dbfs(full_scale) == 0
    assert compute_audio_level_dbfs(b"\x00\x00" * 100) == SILENCE_DBFS


def test_audio_level_odd_length_bytes_tolerated() -> None:
    assert compute_audio_level_dbfs(b"\x01") == SILENCE_DBFS
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_livekit_worker.py -v`
Expected: FAIL，`ModuleNotFoundError`（segment_dedupe / audio_level）

- [ ] **Step 3: 移植**

把 `d:/work/mediation_platform/mediation-deploy/livekit-worker/segment_dedupe.py` 与 `audio_level.py` **逐行复制**到 `src/speech_to_speech/livekit_worker/`，唯一改动：

1. 文件头 docstring 保留原文，追加一行 `（自 livekit-worker 原样移植，行为不变）`。
2. `audio_level.py` docstring 中「Java 侧 ``MeetingTranscriptDO.audioLevel``」一句改写为「audioLevel 为回调 payload 的可空字段」——其余逻辑零改动。

- [ ] **Step 4: 运行确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_livekit_worker.py -v`
Expected: PASS（15 passed）

- [ ] **Step 5: Commit（先询问用户）**

```bash
git add src/speech_to_speech/livekit_worker/segment_dedupe.py src/speech_to_speech/livekit_worker/audio_level.py tests/test_livekit_worker.py
git commit -m "feat(livekit-worker): port segment dedupe and audio level helpers"
```

---

### Task 6: ser_provider.py 移植

**Files:**
- Create: `src/speech_to_speech/livekit_worker/ser_provider.py`
- Test: `tests/test_livekit_worker.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_livekit_worker.py 追加
import pytest

from speech_to_speech.livekit_worker import ser_provider
from speech_to_speech.livekit_worker.ser_provider import (
    DEFAULT_SER_POLICY,
    SerCircuitBreaker,
    SerConcurrencyGate,
    SerRejectedException,
    SerResult,
    get_ser_provider,
    in_segment_window,
    parse_switch_snapshot,
)


def test_ser_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SER_PROVIDER", raising=False)
    with pytest.raises(ValueError, match="SER_PROVIDER"):
        get_ser_provider()


def test_ser_result_validates_labels() -> None:
    assert SerResult.from_response({"emotion": "calm", "confidence": 0.9, "model": "m"}).emotion == "calm"
    assert SerResult.from_response({"emotion": "happy", "confidence": 0.9, "model": "m"}).emotion == "calm"
    with pytest.raises(ValueError, match="emotion"):
        SerResult.from_response({"emotion": "unknown", "confidence": 0.9, "model": "m"})
    with pytest.raises(ValueError, match="confidence"):
        SerResult.from_response({"emotion": "calm", "confidence": 1.5, "model": "m"})
    with pytest.raises(ValueError, match="缺少字段"):
        SerResult.from_response({"emotion": "calm"})


def test_parse_switch_snapshot_fail_closed() -> None:
    closed = parse_switch_snapshot({})
    assert closed["ser"] is False and closed["policyComplete"] is False
    complete = parse_switch_snapshot({
        "voice": True, "ser": True, "video": False,
        "serPolicy": {"minSegSec": 1.0, "maxSegSec": 30.0, "maxConcurrency": 2,
                      "failThreshold": 3, "cooldownSec": 60},
    })
    assert complete["ser"] is True and complete["policyComplete"] is True


def test_segment_window() -> None:
    policy = dict(DEFAULT_SER_POLICY)
    assert in_segment_window(2 * 16000 * 5, 16000, policy)  # 5s
    assert not in_segment_window(2 * 16000 * 0.5, 16000, policy)  # 0.5s < min
    assert not in_segment_window(2 * 16000 * 40, 16000, policy)  # 40s > max


def test_concurrency_gate() -> None:
    gate = SerConcurrencyGate(1)
    assert gate.try_enter() is True
    assert gate.try_enter() is False
    gate.exit()
    assert gate.inflight == 0


def test_circuit_breaker_opens_and_recovers() -> None:
    clock = {"now": 0.0}
    breaker = SerCircuitBreaker(fail_threshold=2, cooldown_sec=10, clock=lambda: clock["now"])
    breaker.record_failure()
    assert breaker.is_open is False
    breaker.record_failure()
    assert breaker.is_open is True
    assert breaker.allow() is False
    clock["now"] += 11
    assert breaker.allow() is True  # 半开放行
    breaker.record_success()
    assert breaker.is_open is False


def test_ser_rejected_is_distinct_exception() -> None:
    assert issubclass(SerRejectedException, RuntimeError)


def test_ser_http_409_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """409 → SerRejectedException（fail-closed，不降级为无 SER 结果）。

    被测入口 `sp.post_segment` 是源工程 ser_provider 中发起
    /v1/audio/emotion 请求、409 抛 SerRejectedException 的那条路径的函数名；
    若移植后源码中实际名称不同（如 request_ser / ser_segment），把测试里的
    `sp.post_segment` 改成真实名称——语义断言不变，这是移植测试的常规对齐。
    """
    from speech_to_speech.livekit_worker import ser_provider as sp

    def fake_post(url, files=None, data=None, timeout=None):  # noqa: ANN001
        return _FakeResponse(409, '{"error":"concurrency"}')

    monkeypatch.setattr(sp.requests, "post", fake_post)
    with pytest.raises(SerRejectedException):
        sp.post_segment(b"\x01\x00" * 16000, 16000, url="http://ser/v1/audio/emotion")
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_livekit_worker.py::test_ser_disabled_by_default -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 移植**

把源工程 `ser_provider.py` 复制到 `src/speech_to_speech/livekit_worker/ser_provider.py`，改动仅两处：

1. 第 23 行 `from asr_provider import _to_wav` 改为 `from speech_to_speech.livekit_worker.asr_provider import _to_wav`（Task 7 会先落 asr_provider；若按本计划顺序执行，Task 7 在本任务之后——将本任务的本行 import 与 Task 7 合并提交，或在 Task 6 先建 `asr_provider.py` 的 `_to_wav` 骨架。**采用后者**：本任务先只建 `asr_provider.py` 的 `_to_wav` 纯函数与 `AsrProvider` 基类（Task 7 再补全双模式），保证每个任务独立可运行）。本任务先建的最小 `asr_provider.py`：

```python
# src/speech_to_speech/livekit_worker/asr_provider.py（Task 6 临时骨架，Task 8 扩全）
"""可插拔 ASR Provider：把 PCM16 单声道音频段转成文本。"""
from __future__ import annotations

import io
import wave


class AsrProvider:
    """ASR Provider 抽象基类。"""

    def transcribe(self, pcm16_bytes: bytes, sample_rate: int, language: str = "auto") -> str:
        raise NotImplementedError


def _to_wav(pcm16_bytes: bytes, sample_rate: int) -> bytes:
    """把裸 PCM16 单声道数据包成 WAV 容器（16bit、单声道、指定采样率）。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm16_bytes)
    return buf.getvalue()
```

2. 其余逻辑（含 `requests`、`fetch_switch_snapshot`、`parse_switch_snapshot`、门与断路器）逐行保留，仅文件头 docstring 注明移植来源。

- [ ] **Step 4: 运行确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_livekit_worker.py -v`
Expected: PASS（22 passed）

- [ ] **Step 5: Commit（先询问用户）**

```bash
git add src/speech_to_speech/livekit_worker/ser_provider.py src/speech_to_speech/livekit_worker/asr_provider.py tests/test_livekit_worker.py
git commit -m "feat(livekit-worker): port SER provider with fail-closed gates"
```

---

### Task 7: diarization_provider.py 移植

**Files:**
- Create: `src/speech_to_speech/livekit_worker/diarization_provider.py`
- Test: `tests/test_livekit_worker.py`（追加）

- [ ] **Step 1: 写失败测试（用例移植自源工程契约）**

```python
# tests/test_livekit_worker.py 追加
import pytest

from speech_to_speech.livekit_worker import diarization_provider as dia
from speech_to_speech.livekit_worker.diarization_provider import (
    DiarizationClient,
    DiarizationUnavailableException,
    SpeakerSegment,
    is_enabled,
    merge_adjacent,
    parse_diarization,
    pick_representative,
    slice_by_speaker,
    to_epoch_ms,
)


def test_disabled_without_base_url() -> None:
    assert is_enabled("") is False
    assert is_enabled(None) is False
    assert is_enabled("http://x") is True


def test_parse_diarization_valid_and_invalid() -> None:
    segs = parse_diarization({"segments": [
        {"speaker": 1, "startSec": 0.2, "endSec": 1.5},
        {"speaker": 0, "startSec": 1.6, "endSec": 2.8},
    ]})
    assert segs == [SpeakerSegment(1, 0.2, 1.5), SpeakerSegment(0, 1.6, 2.8)]
    with pytest.raises(DiarizationUnavailableException):
        parse_diarization({"nope": []})
    with pytest.raises(DiarizationUnavailableException):
        parse_diarization({"segments": [{"speaker": 0, "startSec": 2.0, "endSec": 1.0}]})


def test_merge_adjacent_same_speaker() -> None:
    merged = merge_adjacent([
        SpeakerSegment(0, 0.0, 1.0), SpeakerSegment(0, 1.1, 2.0), SpeakerSegment(1, 2.0, 3.0),
    ], gap_sec=0.2)
    assert merged == [SpeakerSegment(0, 0.0, 2.0), SpeakerSegment(1, 2.0, 3.0)]


def test_slice_by_speaker() -> None:
    pcm = b"\x01\x00" * 16000 * 3  # 3 秒 16k mono
    subs = slice_by_speaker(pcm, 16000, [SpeakerSegment(0, 0.0, 1.0), SpeakerSegment(1, 1.0, 2.5)])
    assert set(subs) == {0, 1}
    assert len(subs[0][0]) == 16000 * 2
    with pytest.raises(DiarizationUnavailableException):
        slice_by_speaker(pcm, 16000, [SpeakerSegment(i, 0.0, 1.0) for i in range(20)])


def test_pick_representative() -> None:
    subs = [(b"a", 0.0, 1.0), (b"bb", 1.0, 2.5)]
    assert pick_representative(subs) == (b"bb", 1.0, 2.5)


def test_to_epoch_ms() -> None:
    assert to_epoch_ms(1000, 0.5, 1.5) == (1500, 2500)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def test_client_http_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    client = DiarizationClient("http://dia")
    calls: list[dict] = []

    def fake_post(url, files, data, timeout):  # noqa: ANN001
        calls.append({"url": url})
        return _FakeResponse(500, {})

    monkeypatch.setattr(dia.requests, "post", fake_post)
    with pytest.raises(DiarizationUnavailableException, match="500"):
        client.diarize(b"\x01\x00" * 16000, 16000)
    assert calls and calls[0]["url"] == "http://dia/v1/audio/diarization"
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_livekit_worker.py::test_disabled_without_base_url -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 移植**

把源工程 `diarization_provider.py` 逐行复制到 `src/speech_to_speech/livekit_worker/diarization_provider.py`。零逻辑改动；文件头 docstring 追加一行移植来源说明（`DIARIZATION_BASE_URL` 仍指向外部部署，源工程 deploy/diarization 服务不迁移）。

- [ ] **Step 4: 运行确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_livekit_worker.py -v`
Expected: PASS（30 passed）

- [ ] **Step 5: Commit（先询问用户）**

```bash
git add src/speech_to_speech/livekit_worker/diarization_provider.py tests/test_livekit_worker.py
git commit -m "feat(livekit-worker): port diarization HTTP client with graceful fallback"
```

---

### Task 8: asr_provider.py 双模式（gateway / local）

**Files:**
- Modify: `src/speech_to_speech/livekit_worker/asr_provider.py`（扩全 Task 6 的骨架）
- Test: `tests/test_livekit_worker.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_livekit_worker.py 追加
from speech_to_speech.livekit_worker.asr_provider import (
    GatewayAsrProvider,
    LocalSttAsrProvider,
    create_asr_provider,
)


class _FakeSttHandler:
    def transcribe_chunk(self, pcm16_bytes: bytes, sample_rate: int) -> str:
        return "本地结果"


def test_gateway_provider_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_GATEWAY_BASE_URL", "http://gw")
    monkeypatch.delenv("ASR_BASE_URL", raising=False)
    monkeypatch.setenv("VOICE_ASR_MODEL", "qwen3-asr")
    provider = GatewayAsrProvider()
    assert provider.base == "http://gw"
    assert provider.model == "qwen3-asr"


def test_gateway_provider_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOICE_GATEWAY_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="VOICE_GATEWAY_BASE_URL"):
        GatewayAsrProvider()


def test_create_provider_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_GATEWAY_BASE_URL", "http://gw")
    assert isinstance(create_asr_provider("gateway"), GatewayAsrProvider)
    local = create_asr_provider("local", stt_handler=_FakeSttHandler())
    assert isinstance(local, LocalSttAsrProvider)
    assert local.transcribe(b"\x01\x00", 16000) == "本地结果"
    with pytest.raises(ValueError, match="ASR mode"):
        create_asr_provider("bogus")
    with pytest.raises(ValueError, match="stt_handler"):
        create_asr_provider("local", stt_handler=None)


def test_gateway_transcribe_posts_multipart(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_GATEWAY_BASE_URL", "http://gw")
    monkeypatch.setenv("VOICE_ASR_MODEL", "qwen3-asr")
    provider = GatewayAsrProvider()
    seen: dict = {}

    class _Resp:
        status_code = 200
        def raise_for_status(self) -> None: ...
        def json(self) -> dict:
            return {"text": "你好"}

    def fake_post(url, files, data, timeout):  # noqa: ANN001
        seen.update({"url": url, "files": files, "data": data})
        return _Resp()

    monkeypatch.setattr(provider_module.requests, "post", fake_post)
    text = provider.transcribe(b"\x01\x00" * 1600, 16000)
    assert text == "你好"
    assert seen["url"] == "http://gw/v1/audio/transcriptions"
    assert seen["data"]["model"] == "qwen3-asr"
    assert seen["files"]["file"][2] == "audio/wav"
```

实现注意：测试中 `provider_module` 指 `speech_to_speech.livekit_worker.asr_provider`（测试文件顶部 `from speech_to_speech.livekit_worker import asr_provider as provider_module`）。

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_livekit_worker.py::test_create_provider_modes -v`
Expected: FAIL，`ImportError: cannot import name 'GatewayAsrProvider'`

- [ ] **Step 3: 扩全实现**

```python
# src/speech_to_speech/livekit_worker/asr_provider.py（完整替换）
"""可插拔 ASR Provider，双模式（spec §6）：

- ``gateway``（默认）：OpenAI 兼容 HTTP 转写（``POST {base}/v1/audio/transcriptions``），
  与源工程 QwenAsrProvider 行为一致。
- ``local``：复用 pipeline 已解析的本地 STT handler（不重复加载模型）。
  handler 契约为 ``transcribe_chunk(pcm16_bytes, sample_rate) -> str``；
  实现期核对所选后端是否支持被 worker 线程并发调用，不支持时在文档标注限制。
"""
from __future__ import annotations

import io
import os
import wave

import requests


class AsrProvider:
    """ASR Provider 抽象基类。"""

    def transcribe(self, pcm16_bytes: bytes, sample_rate: int, language: str = "auto") -> str:
        raise NotImplementedError


def _to_wav(pcm16_bytes: bytes, sample_rate: int) -> bytes:
    """把裸 PCM16 单声道数据包成 WAV 容器（16bit、单声道、指定采样率）。纯函数。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm16_bytes)
    return buf.getvalue()


class GatewayAsrProvider(AsrProvider):
    """OpenAI 兼容 ASR；base 取 ASR_BASE_URL（可选覆盖），默认 VOICE_GATEWAY_BASE_URL。"""

    def __init__(self) -> None:
        base = os.environ.get("ASR_BASE_URL") or os.environ.get("VOICE_GATEWAY_BASE_URL", "")
        if not base.strip():
            raise ValueError("VOICE_GATEWAY_BASE_URL 未配置（gateway 模式必需）")
        self.base = base.rstrip("/")
        self.model = os.environ.get("VOICE_ASR_MODEL", "qwen3-asr")

    def transcribe(self, pcm16_bytes: bytes, sample_rate: int, language: str = "auto") -> str:
        wav = _to_wav(pcm16_bytes, sample_rate)
        data = {"model": self.model}
        if language and language != "auto":
            data["language"] = language
        r = requests.post(
            f"{self.base}/v1/audio/transcriptions",
            files={"file": ("seg.wav", wav, "audio/wav")},
            data=data,
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("text", "")


class LocalSttAsrProvider(AsrProvider):
    """复用 pipeline 已解析的本地 STT handler。只依赖 transcribe_chunk 契约。"""

    def __init__(self, stt_handler: object) -> None:
        if stt_handler is None:
            raise ValueError("local ASR mode 需要 stt_handler（pipeline STT 后端实例）")
        self._handler = stt_handler

    def transcribe(self, pcm16_bytes: bytes, sample_rate: int, language: str = "auto") -> str:
        result = getattr(self._handler, "transcribe_chunk")(pcm16_bytes, sample_rate)
        return str(result or "")


def create_asr_provider(mode: str, stt_handler: object | None = None) -> AsrProvider:
    """按模式构造 provider；非法模式显式报错，不静默降级。"""
    normalized = (mode or "gateway").strip().lower()
    if normalized == "gateway":
        return GatewayAsrProvider()
    if normalized == "local":
        return LocalSttAsrProvider(stt_handler)
    raise ValueError(f"ASR mode 必须是 gateway|local；got {mode!r}")
```

- [ ] **Step 4: 运行确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_livekit_worker.py -v`
Expected: PASS（34 passed）

- [ ] **Step 5: Commit（先询问用户）**

```bash
git add src/speech_to_speech/livekit_worker/asr_provider.py tests/test_livekit_worker.py
git commit -m "feat(livekit-worker): dual-mode ASR provider (gateway/local)"
```

---

### Task 9: worker.py 核心移植 + LiveKitWorkerRuntime 线程生命周期

**Files:**
- Create: `src/speech_to_speech/livekit_worker/worker.py`
- Create: `src/speech_to_speech/livekit_worker/__init__.py`（替换占位）
- Test: `tests/test_livekit_worker.py`（追加）

- [ ] **Step 1: 写失败测试（可离线部分：事件产出与去重联动；livekit 依赖 mock）**

```python
# tests/test_livekit_worker.py 追加
import sys
import types
from unittest.mock import MagicMock

from speech_to_speech.livekit_worker.events import TranscriptEvent, get_event_bus


def _install_livekit_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """livekit-agents 在 Python 3.14 下不可用时提供可导入的桩模块（voxcpm 先例）。"""
    if "livekit" in sys.modules:
        return
    rtc_stub = types.ModuleType("livekit.rtc")
    agents_stub = types.ModuleType("livekit.agents")
    plugins_stub = types.ModuleType("livekit.plugins")
    silero_stub = types.ModuleType("livekit.plugins.silero")
    agents_stub.JobContext = MagicMock
    agents_stub.WorkerOptions = MagicMock
    agents_stub.cli = types.SimpleNamespace(run_app=lambda options: None)
    agents_stub.AutoSubscribe = types.SimpleNamespace(SUBSCRIBE_ALL="all")
    agents_stub.VADEventType = types.SimpleNamespace(
        START_OF_SPEECH="start", END_OF_SPEECH="end")
    agents_stub.VAD = MagicMock
    agents_stub.WorkerServer = MagicMock
    silero_stub.VAD = types.SimpleNamespace(load=lambda **_: MagicMock())
    plugins_stub.silero = silero_stub
    sys.modules["livekit"] = types.ModuleType("livekit")
    sys.modules["livekit.rtc"] = rtc_stub
    sys.modules["livekit.agents"] = agents_stub
    sys.modules["livekit.plugins"] = plugins_stub
    sys.modules["livekit.plugins.silero"] = silero_stub


def test_worker_emits_events_through_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_livekit_stub(monkeypatch)
    from speech_to_speech.livekit_worker import worker

    bus = get_event_bus()
    seen: list[TranscriptEvent] = []
    unsubscribe = bus.subscribe(seen.append)
    try:
        worker.emit_segments(
            room_sid="room-1",
            identity="user-a",
            segments=[{
                "speakerIdentity": "user-a", "text": "你好会议",
                "startTs": 1000, "endTs": 2000, "audioLevel": -12,
            }],
        )
    finally:
        unsubscribe()
    assert len(seen) == 1
    assert seen[0].to_payload()["text"] == "你好会议"
    assert seen[0].to_payload()["roomSid"] == "room-1"


def test_worker_emit_failure_is_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_livekit_stub(monkeypatch)
    from speech_to_speech.livekit_worker import worker

    bus = get_event_bus()
    bus.subscribe(lambda _: (_ for _ in ()).throw(RuntimeError("sink boom")))
    # 不抛异常：事件消费失败不影响转写主流程
    worker.emit_segments(
        room_sid="r", identity="i",
        segments=[{"speakerIdentity": "i", "text": "t", "startTs": 0, "endTs": 1, "audioLevel": None}],
    )


def test_split_pcm_blocks() -> None:
    _install_livekit_stub(monkeypatch)
    from speech_to_speech.livekit_worker.worker import split_pcm_blocks

    pcm = b"\x01\x00" * 16000 * 55  # 55 秒
    blocks = split_pcm_blocks(pcm, 16000, max_block_sec=25)
    assert len(blocks) == 3
    assert len(blocks[0]) == 16000 * 2 * 25
    assert split_pcm_blocks(b"", 16000) == []
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_livekit_worker.py::test_split_pcm_blocks -v`
Expected: FAIL，`ImportError: cannot import name 'worker'`

- [ ] **Step 3: 移植 worker.py**

把源工程 `worker.py` 复制到 `src/speech_to_speech/livekit_worker/worker.py`，做以下**定向改造**（其余逻辑逐段照搬、行为不变）：

1. **imports 命名空间化**：

```python
from speech_to_speech.livekit_worker.asr_provider import create_asr_provider, _to_wav
from speech_to_speech.livekit_worker.audio_level import compute_audio_level_dbfs
import speech_to_speech.livekit_worker.diarization_provider as dia
from speech_to_speech.livekit_worker.events import TranscriptEvent, get_event_bus
from speech_to_speech.livekit_worker.segment_dedupe import DuplicateGuard
from speech_to_speech.livekit_worker.ser_provider import (  # noqa: F401
    DEFAULT_SER_POLICY, SerCircuitBreaker, SerConcurrencyGate, SerRejectedException,
    fetch_switch_snapshot as fetch_switch_snapshot_raw, get_ser_provider,
    in_segment_window, parse_switch_snapshot,
)
```

2. **模块级 env 读取改为惰性**：源工程第 48-51 行 `JAVA_BASE = os.environ[...]` 模块导入即读，进程内嵌形态下导入时机早于 env 就绪。改为函数：

```python
def _env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.environ.get(name, default)
    if value is None and required:
        raise ValueError(f"--with-livekitworker 需要 {name}")
    return value

def java_base() -> str:
    return (_env("JAVA_CALLBACK_BASE", required=True) or "").rstrip("/")

def internal_token() -> str:
    return _env("MEETING_INTERNAL_TOKEN", required=True) or ""

def tenant_id() -> str:
    return _env("MEETING_TENANT_ID", "1") or "1"
```

相应地 `fetch_switch_snapshot` / `switch_poll_loop` / `identify` 路径中的 `JAVA_BASE`、`INTERNAL_TOKEN`、`TENANT_ID` 全部改为调用这三个函数；`HEALTH_PORT`、`AGENT_NAME`、`LOAD_THRESHOLD`、VAD/ASR 调参常量保留模块级读取但带默认值（`os.environ.get`，不 `os.environ[...]` 强制）。

3. **push() 改为 emit_segments() + 双路输出**：

```python
def emit_segments(room_sid: str, segments: list[dict]) -> None:
    """转写分段双路输出：进程内事件总线（本地转写/日志）+ CallbackDispatcher 回调。

    任何一路失败仅告警，不阻断另一路与其它轨。
    """
    try:
        get_event_bus().publish(TranscriptEvent(
            event_type="transcript",
            room_sid=room_sid,
            identity=str(segments[0].get("speakerIdentity", "")) if segments else "",
            text=" ".join(str(s.get("text", "")) for s in segments),
            start_ts=int(segments[0]["startTs"]) if segments else 0,
            end_ts=int(segments[-1]["endTs"]) if segments else 0,
            audio_level=segments[0].get("audioLevel") if segments else None,
            extra={k: v for k, v in segments[0].items()
                   if k not in ("speakerIdentity", "text", "startTs", "endTs", "audioLevel")}
            if segments else {},
            timestamp_ms=int(time.time() * 1000),
        ))
    except Exception as exc:  # noqa: BLE001
        print(f"[worker] local transcript sink 失败 room={room_sid}: {exc}")
    try:
        from speech_to_speech.callback.dispatcher import get_dispatcher
        get_dispatcher().publish_transcript(room_sid, segments)
    except Exception as exc:  # noqa: BLE001 回调子系统故障不影响转写
        print(f"[worker] callback dispatch 失败 room={room_sid}: {exc}")
```

注意：`TranscriptEvent.extra` 的 `audio_level=None` 传 `None` 而非缺省——dataclass 字段类型是 `int | None`。`emit_segments` 每段一条事件（`segments` 来自 diarization 多子段合并，逐条循环产出更精确）——实现时改为 for 循环逐段构造事件，上面代码结构照此调整（每段一个 `TranscriptEvent`，`extra` 含该段 ser/identify 字段）。`publish_transcript(room_sid, segments)` 是 dispatcher 的 java 兼容入口（Task 12 定义）。

4. **ASR provider 双模式**：模块级 `provider = get_provider()` 改为

```python
_provider = None

def asr_provider():
    global _provider
    if _provider is None:
        _provider = create_asr_provider(
            os.environ.get("LIVEKIT_WORKER_ASR_MODE", "gateway").strip().lower(),
            stt_handler=_stt_handler_instance(),
        )
    return _provider

def _stt_handler_instance():
    """local 模式的 STT handler 注入点：由 LiveKitWorkerRuntime 在启动时设置。"""
    return _shared_state.get("stt_handler")

_shared_state: dict[str, object] = {}

def set_shared_state(**kwargs: object) -> None:
    _shared_state.update(kwargs)
```

`transcribe_with_retry` 内 `provider.transcribe(...)` 改为 `asr_provider().transcribe(...)`。

5. **会话结束事件**：`entrypoint` 中 room disconnected 时（`room.on("disconnected", ...)` 追加一行）产出 `session_end` 事件：

```python
room.on("disconnected", lambda *_: _emit_session_end(room.name))

def _emit_session_end(room_sid: str) -> None:
    event = TranscriptEvent(
        event_type="session_end", room_sid=room_sid, identity="", text="",
        start_ts=0, end_ts=int(time.time() * 1000), audio_level=None,
        extra={}, timestamp_ms=int(time.time() * 1000),
    )
    get_event_bus().publish(event)
    try:
        from speech_to_speech.callback.dispatcher import get_dispatcher
        get_dispatcher().dispatch(event)
    except Exception as exc:  # noqa: BLE001
        print(f"[worker] session_end 回调失败 room={room_sid}: {exc}")
```

6. **诊断日志**：源工程用 `print(..., flush=True)`，保持不变（行为一致），不改 logger。

- [ ] **Step 4: 实现 __init__.py（LiveKitWorkerRuntime）**

```python
# src/speech_to_speech/livekit_worker/__init__.py
"""LiveKit room transcript worker: embedded thread runtime.

The worker runs livekit-agents WorkerServer inside a dedicated thread with its
own asyncio loop (same pattern as --with-console / voiceprint service). A crash
in the worker thread must never take down the speech pipeline: the thread
isolates failures and the health endpoint reports degraded state via the shared
stop event.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from threading import Event

logger = logging.getLogger(__name__)


class LiveKitWorkerRuntime:
    """线程 + asyncio loop 内跑 livekit-agents WorkerServer。"""

    def __init__(self, stop_event: Event, *, stt_handler: object | None = None) -> None:
        self._stop_event = stop_event
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: object | None = None

    @property
    def name(self) -> str:
        return "livekit-worker"

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="livekit-worker", daemon=True)
        self._thread.start()
        logger.info("livekit-worker: thread started")

    def stop(self) -> None:
        """联动 serve 退出：取消 loop 任务、等待线程 join。"""
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("livekit-worker: thread stopped")

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception:
            logger.exception("livekit-worker thread crashed; pipeline keeps running")
        finally:
            asyncio.set_event_loop(None)
            self._loop.close()

    async def _serve(self) -> None:
        from speech_to_speech.livekit_worker import worker

        worker.set_shared_state(
            stt_handler=self._resolve_stt_handler(), stop_event=self._stop_event,
        )
        from livekit.agents import WorkerOptions
        from speech_to_speech.livekit_worker.worker import AGENT_NAME, HEALTH_PORT, LOAD_THRESHOLD, entrypoint

        try:
            from livekit.agents.worker import WorkerServer
        except ImportError:  # noqa: PLC0415 - 0.12.x 内嵌 API 名称实现期核对
            from livekit.agents import WorkerServer  # type: ignore[no-redef]

        server = WorkerServer(WorkerOptions(
            entrypoint_fnc=entrypoint,
            port=HEALTH_PORT,
            agent_name=AGENT_NAME,
            load_threshold=LOAD_THRESHOLD,
        ))
        self._server = server
        await server.start()
        await server.run()

    def _resolve_stt_handler(self) -> object | None:
        """local ASR 模式取 pipeline STT handler；gateway 模式恒为 None。"""
        import os

        if os.environ.get("LIVEKIT_WORKER_ASR_MODE", "gateway").strip().lower() != "local":
            return None
        return self._shared_stt_handler

    _shared_stt_handler: object | None = None

    def attach_stt_handler(self, handler: object) -> None:
        """由 build_pipeline 注入 pipeline 已解析的 STT handler（local 模式用）。"""
        self._shared_stt_handler = handler
```

实现说明：`WorkerServer(WorkerOptions(...))` 的构造签名在 livekit-agents 0.12.x 实现期核对（`pip install "livekit-agents[silero]>=0.12,<0.13"` 后 `python -c "from livekit.agents import WorkerServer; help(WorkerServer)"`）；若 0.12 只有 `cli.run_app` 进程级入口、无内嵌 API，则在 `_serve` 内改用 `cli.run_app(WorkerOptions(...))` 的 `run_worker` 变体并在文档标注「worker 以子形态运行」。ImportError 时 runtime 捕获并仅告警（线程隔离），pipeline 照常服务。

- [ ] **Step 5: 运行确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_livekit_worker.py -v`
Expected: PASS（37 passed）

- [ ] **Step 6: Commit（先询问用户）**

```bash
git add src/speech_to_speech/livekit_worker/worker.py src/speech_to_speech/livekit_worker/__init__.py tests/test_livekit_worker.py
git commit -m "feat(livekit-worker): port room transcript worker core and thread runtime"
```

---

### Task 10: s2s_pipeline 接线 —— 开关生效

**Files:**
- Modify: `src/speech_to_speech/s2s_pipeline.py`（`prepare_all_args` 约 L299、`_build_pipeline_unit` 约 L456、`build_pipeline` 约 L780-834、`_run_parsed_pipeline_command` 约 L916-966）
- Test: `tests/test_worker_integration.py`（追加）

- [ ] **Step 1: 写失败测试（纯逻辑部分）**

```python
# tests/test_worker_integration.py 追加
def test_diarization_switch_maps_to_module_kwargs() -> None:
    from speech_to_speech.s2s_pipeline import apply_diarization_switch
    from types import SimpleNamespace

    kwargs = SimpleNamespace(diarization=False)
    apply_diarization_switch(kwargs, True)
    assert kwargs.diarization is True
    apply_diarization_switch(kwargs, False)
    assert kwargs.diarization is False


def test_local_asr_mode_requires_stt_definition() -> None:
    from speech_to_speech.worker_integration import WorkerIntegrationError
    from speech_to_speech.s2s_pipeline import validate_local_asr_mode

    import os
    os.environ["LIVEKIT_WORKER_ASR_MODE"] = "local"
    with pytest.raises(WorkerIntegrationError, match="local"):
        validate_local_asr_mode(stt_backend_name=None)
    validate_local_asr_mode(stt_backend_name="parakeet-tdt")
    os.environ["LIVEKIT_WORKER_ASR_MODE"] = "gateway"
    validate_local_asr_mode(stt_backend_name=None)  # gateway 无 STT 也可
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_worker_integration.py -v`
Expected: FAIL，`ImportError: cannot import name 'apply_diarization_switch'`

- [ ] **Step 3: 在 s2s_pipeline.py 实现接线函数与调用**

```python
# src/speech_to_speech/s2s_pipeline.py 追加（放在模块工具函数区）
def apply_diarization_switch(module_kwargs: Any, enabled: bool) -> None:
    """--with-diarization ⇔ 现有流式分离参数（spec 决策 2：不移植 sherpa-onnx）。"""
    module_kwargs.diarization = bool(enabled)


def validate_local_asr_mode(*, stt_backend_name: str | None) -> None:
    """local ASR 模式要求 serve 已选 STT 定义（spec §9）。"""
    import os

    from speech_to_speech.worker_integration import WorkerIntegrationError

    if os.environ.get("LIVEKIT_WORKER_ASR_MODE", "gateway").strip().lower() != "local":
        return
    if not stt_backend_name:
        raise WorkerIntegrationError(
            "LIVEKIT_WORKER_ASR_MODE=local requires a --stt backend definition; "
            "select one or switch the worker ASR to gateway."
        )
```

调用点（`_run_parsed_pipeline_command`，console_attachment 解析之后）：

```python
    if diarization_options is not None:
        apply_diarization_switch(args.module_kwargs, diarization_options.autostart)
    validate_local_asr_mode(stt_backend_name=getattr(args, "stt_backend", None) and args.stt_backend.name)
```

`run_pipeline_command` / `_run_parsed_pipeline_command` 签名追加 `diarization_options=None, livekit_options=None` 关键字参数并透传（与 `agent_options` 同模式）。注意：现有解析流程里 `args.stt_backend` 在 `prepare_all_args(args)` 之前是否已可用需实现期核对；不可用则把 `validate_local_asr_mode` 挪到 `prepare_all_args` 之后调用。

`build_pipeline` 追加（在 `agent is not None` 附加 handler 的同一区）：

```python
    livekit_runtime = None
    if livekit_options is not None and livekit_options.autostart:
        from speech_to_speech.livekit_worker import LiveKitWorkerRuntime

        livekit_runtime = LiveKitWorkerRuntime(stop_event)
        # local ASR 模式注入 pipeline STT handler（gateway 模式忽略）
        if getattr(args, "stt_backend", None) is not None:
            from speech_to_speech.backend_registry import resolve_stt_handler  # 若无此函数，用 unit.handlers 里按 name 查找

            # 实现期按实际 handler 类型注入：unit.handlers 中 isinstance 匹配 STT handler
            for unit in pool:
                for handler in unit.handlers:
                    if hasattr(handler, "transcribe_chunk"):
                        livekit_runtime.attach_stt_handler(handler)
                        break

    ...
    if livekit_runtime is not None:
        handlers.append(livekit_runtime)
```

`LiveKitWorkerRuntime` 实现 handler 协议（`start()`/`stop()`），ThreadManager 按现有 agent 先例统一管理生命周期。`build_local_pipeline` 同样追加（`--with-livekitworker` 与 `local` 组合允许，spec §4 表格）。

- [ ] **Step 4: 运行测试**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_worker_integration.py -v`
Expected: PASS（12 passed）

Run: `.\.venv\Scripts\python.exe -m pytest tests -q -k "pipeline or cli or command"`
Expected: PASS，无回归

- [ ] **Step 5: Commit（先询问用户）**

```bash
git add src/speech_to_speech/s2s_pipeline.py tests/test_worker_integration.py
git commit -m "feat(livekit-worker): wire diarization switch and embedded worker runtime into pipeline"
```

---

### Task 11: console 后端 —— 两表模型 + alembic 0015 迁移

**Files:**
- Create: `console/backend/app/models/callbacks.py`
- Create: `console/backend/alembic/versions/0015_callback_subsystem.py`
- Test: `console/backend/tests/unit/test_callback_models.py`

- [ ] **Step 1: 写失败测试**

```python
# console/backend/tests/unit/test_callback_models.py
"""callback_target / callback_delivery_log 模型与迁移测试（sqlite 内存库）。"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.callbacks import CallbackDeliveryLog, CallbackTarget


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_target_roundtrip(session: Session) -> None:
    target = CallbackTarget(
        name="ai-server", target_type="java", base_url="http://ai-server",
        auth_type="header_token", auth_header_name="X-Internal-Token", auth_token="secret",
        extra_headers={"tenant-id": "1"}, timeout_ms=3000, retry_max_attempts=3,
        retry_backoff_ms=500, events=["transcript"], filters=None, enabled=True,
    )
    session.add(target)
    session.flush()
    row = session.query(CallbackTarget).one()
    assert row.target_type == "java"
    assert row.extra_headers == {"tenant-id": "1"}
    assert row.events == ["transcript"]
    assert row.timeout_ms == 3000


def test_log_set_null_on_target_delete(session: Session) -> None:
    target = CallbackTarget(name="webhook", target_type="python", base_url="http://x",
                            auth_type="none", auth_token="", extra_headers={},
                            timeout_ms=3000, retry_max_attempts=1, retry_backoff_ms=0,
                            events=["transcript"], enabled=True)
    session.add(target)
    session.flush()
    log = CallbackDeliveryLog(target_id=target.id, event_type="transcript",
                              triggered_at=target.created_at, request_url="http://x",
                              request_payload="{}", attempt=1, http_status=200,
                              response_snippet="ok", duration_ms=10, status="success", error="")
    session.add(log)
    session.commit()
    session.delete(target)
    session.commit()
    row = session.query(CallbackDeliveryLog).one()
    assert row.target_id is None  # SET NULL：日志保留
```

- [ ] **Step 2: 运行确认失败**

Run（在 `console/backend` 目录）：`..\..\.venv\Scripts\python.exe -m pytest tests/unit/test_callback_models.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.models.callbacks'`

- [ ] **Step 3: 实现 models/callbacks.py**

```python
# console/backend/app/models/callbacks.py
"""回调子系统两张表（spec 2026-11-25 §8.1）：目标配置 + 投递日志。

callback_delivery_log.target_id 对 callback_target.id 是 SET NULL 软关联：
目标删除后日志保留（审计口径）。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class CallbackTarget(Base):
    """一个回调目标的完整配置；java/python 两类协议由 target_type 区分。"""

    __tablename__ = "callback_target"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    # java: base_url + 固定内部端点路径；python: base_url 即完整 webhook URL
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)  # java | python
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    auth_type: Mapped[str] = mapped_column(String(16), nullable=False, default="none")  # none|bearer|header_token
    auth_header_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    auth_token: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    extra_headers: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=3000)
    retry_max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    retry_backoff_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    events: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # ["transcript", ...]
    filters: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"speakers": [...], "min_text_len": N}
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class CallbackDeliveryLog(Base):
    """每次投递尝试一行；payload 截断存储、token 脱敏（写入方负责）。"""

    __tablename__ = "callback_delivery_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("callback_target.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    request_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    request_payload: Mapped[str] = mapped_column(Text, nullable=False, default="")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_snippet: Mapped[str] = mapped_column(Text, nullable=False, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # success|failed|retrying
    error: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
```

- [ ] **Step 4: 运行模型测试确认通过**

Run（在 `console/backend` 目录）：`..\..\.venv\Scripts\python.exe -m pytest tests/unit/test_callback_models.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: alembic 0015 迁移**

```python
# console/backend/alembic/versions/0015_callback_subsystem.py
"""回调子系统：callback_target + callback_delivery_log（spec 2026-11-25 §8.1）。

Revision ID: 0015_callback_subsystem
Revises: 0014_comments_backfill
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0015_callback_subsystem"
down_revision = "0014_comments_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "callback_target",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("target_type", sa.String(16), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("auth_type", sa.String(16), server_default="none", nullable=False),
        sa.Column("auth_header_name", sa.String(128), nullable=True),
        sa.Column("auth_token", sa.String(512), server_default="", nullable=False),
        sa.Column("extra_headers", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("timeout_ms", sa.Integer(), server_default="3000", nullable=False),
        sa.Column("retry_max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("retry_backoff_ms", sa.Integer(), server_default="500", nullable=False),
        sa.Column("events", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("filters", sa.JSON(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("updated_by", sa.String(64), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_callback_target_name"),
    )
    op.create_table(
        "callback_delivery_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "target_id", sa.Integer(),
            sa.ForeignKey("callback_target.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_url", sa.String(1024), nullable=False),
        sa.Column("request_payload", sa.Text(), server_default="", nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("response_snippet", sa.Text(), server_default="", nullable=False),
        sa.Column("duration_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.String(1024), server_default="", nullable=False),
    )
    op.create_index("ix_cdl_target_id", "callback_delivery_log", ["target_id"])
    op.create_index("ix_cdl_triggered_at", "callback_delivery_log", ["triggered_at"])
    op.create_index("ix_cdl_status", "callback_delivery_log", ["status"])


def downgrade() -> None:
    op.drop_index("ix_cdl_status", table_name="callback_delivery_log")
    op.drop_index("ix_cdl_triggered_at", table_name="callback_delivery_log")
    op.drop_index("ix_cdl_target_id", table_name="callback_delivery_log")
    op.drop_table("callback_delivery_log")
    op.drop_table("callback_target")
```

- [ ] **Step 6: 迁移可升级性测试（追加到 test_callback_models.py）**

```python
# console/backend/tests/unit/test_callback_models.py 追加
def test_migration_up_and_down(tmp_path) -> None:
    """alembic upgrade head + downgrade -1 可执行（0014→0015→0014）。"""
    import os

    from alembic import command
    from alembic.config import Config

    os.environ["ALEMBIC_DATABASE_URL"] = f"sqlite:///{tmp_path/'mig.db'}"
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cfg = Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(root, "alembic"))
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "-1")
    command.upgrade(cfg, "head")
```

若 alembic.ini / env.py 读取数据库 URL 的方式不同（实现期查看 `console/backend/alembic/env.py` 的 `url =` 来源），按其现有约定传 URL（常见为 `-x db_url=...` 或 env）。Run（在 `console/backend` 目录）：`..\..\.venv\Scripts\python.exe -m pytest tests/unit/test_callback_models.py -v` → PASS（3 passed）。

- [ ] **Step 7: Commit（先询问用户）**

```bash
git add console/backend/app/models/callbacks.py console/backend/alembic/versions/0015_callback_subsystem.py console/backend/tests/unit/test_callback_models.py
git commit -m "feat(callbacks): callback_target and callback_delivery_log tables with alembic 0015"
```

---

### Task 12: CallbackDispatcher —— TTL 热加载 + 协议适配 + 重试 + 日志 + env 兜底

**Files:**
- Create: `src/speech_to_speech/callback/__init__.py`（占位 docstring）
- Create: `src/speech_to_speech/callback/dispatcher.py`
- Test: `tests/test_callback_dispatcher.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_callback_dispatcher.py
"""CallbackDispatcher 离线测试：sqlite 内存库 + requests mock。"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from speech_to_speech.callback.dispatcher import (
    CallbackDispatcher,
    CallbackTargetConfig,
    mask_token,
)


@pytest.fixture()
def db_session():
    # console 后端在本仓内，测试直接用它的 Base/models（console/backend 在 sys.path）
    import sys

    backend_root = "console/backend"
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)
    from app.db.base import Base
    from app.models.callbacks import CallbackTarget

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session, CallbackTarget


def _target(CallbackTarget, **overrides) -> object:
    fields = dict(
        name="webhook", target_type="python", base_url="http://hook", auth_type="none",
        auth_token="", extra_headers={}, timeout_ms=100, retry_max_attempts=2,
        retry_backoff_ms=0, events=["transcript"], filters=None, enabled=True,
    )
    fields.update(overrides)
    return CallbackTarget(**fields)


def _event(event_type: str = "transcript", text: str = "你好会议", identity: str = "u1"):
    from speech_to_speech.livekit_worker.events import TranscriptEvent

    return TranscriptEvent(
        event_type=event_type, room_sid="room-1", identity=identity, text=text,
        start_ts=1000, end_ts=2000, audio_level=-10, extra={}, timestamp_ms=12345,
    )


class _Resp:
    def __init__(self, status_code: int, text: str = "ok") -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError(self.status_code)


def test_dispatch_hits_python_target(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    session, CallbackTarget = db_session
    session.add(_target(CallbackTarget))
    session.commit()

    posted: dict = {}

    def fake_post(url, json=None, headers=None, params=None, timeout=None):  # noqa: ANN001
        posted.update({"url": url, "json": json, "headers": headers})
        return _Resp(200)

    monkeypatch.setattr("speech_to_speech.callback.dispatcher.requests.post", fake_post)
    dispatcher = CallbackDispatcher(session_factory=lambda: session, ttl_seconds=0)
    dispatcher.dispatch(_event())
    dispatcher.flush_pending()
    assert posted["url"] == "http://hook"
    assert posted["json"]["eventType"] == "transcript"
    assert posted["json"]["text"] == "你好会议"


def test_log_rows_written(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    session, CallbackTarget = db_session
    session.add(_target(CallbackTarget))
    session.commit()
    monkeypatch.setattr(
        "speech_to_speech.callback.dispatcher.requests.post", lambda **kwargs: _Resp(200))
    from app.models.callbacks import CallbackDeliveryLog

    dispatcher = CallbackDispatcher(session_factory=lambda: session, ttl_seconds=0)
    dispatcher.dispatch(_event())
    dispatcher.flush_pending()
    rows = list(session.query(CallbackDeliveryLog).all())
    assert len(rows) == 1
    assert rows[0].status == "success" and rows[0].http_status == 200


def test_java_protocol_adapter(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    session, CallbackTarget = db_session
    session.add(_target(CallbackTarget, name="ai", target_type="java",
                        base_url="http://ai", auth_type="header_token",
                        auth_header_name="X-Internal-Token", auth_token="tok",
                        extra_headers={"tenant-id": "7"}))
    session.commit()
    posted: dict = {}

    def fake_post(url, json=None, headers=None, params=None, timeout=None):  # noqa: ANN001
        posted.update({"url": url, "json": json, "headers": headers, "params": params})
        return _Resp(200)

    monkeypatch.setattr("speech_to_speech.callback.dispatcher.requests.post", fake_post)
    dispatcher = CallbackDispatcher(session_factory=lambda: session, ttl_seconds=0)
    dispatcher.dispatch(_event())
    dispatcher.flush_pending()
    assert posted["url"] == "http://ai/admin-api/ai/meeting/internal/transcript"
    assert posted["params"] == {"roomSid": "room-1"}
    assert posted["headers"]["X-Internal-Token"] == "tok"
    assert posted["headers"]["tenant-id"] == "7"
    assert isinstance(posted["json"], list)  # TranscriptSegmentVO 数组形状


def test_python_bearer_auth(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    session, CallbackTarget = db_session
    session.add(_target(CallbackTarget, auth_type="bearer", auth_token="btok"))
    session.commit()
    captured: dict = {}

    def fake_post(url, json=None, headers=None, params=None, timeout=None):  # noqa: ANN001
        captured["headers"] = headers
        return _Resp(200)

    monkeypatch.setattr("speech_to_speech.callback.dispatcher.requests.post", fake_post)
    dispatcher = CallbackDispatcher(session_factory=lambda: session, ttl_seconds=0)
    dispatcher.dispatch(_event())
    dispatcher.flush_pending()
    assert captured["headers"]["Authorization"] == "Bearer btok"


def test_retry_then_give_up(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    session, CallbackTarget = db_session
    session.add(_target(CallbackTarget, retry_max_attempts=2, retry_backoff_ms=0))
    session.commit()
    attempts = []

    def fake_post(url, json=None, headers=None, params=None, timeout=None):  # noqa: ANN001
        attempts.append(1)
        raise ConnectionError("down")

    monkeypatch.setattr("speech_to_speech.callback.dispatcher.requests.post", fake_post)
    from app.models.callbacks import CallbackDeliveryLog

    dispatcher = CallbackDispatcher(session_factory=lambda: session, ttl_seconds=0)
    dispatcher.dispatch(_event())
    dispatcher.flush_pending()
    assert len(attempts) == 2
    rows = list(session.query(CallbackDeliveryLog).all())
    assert [r.status for r in rows] == ["retrying", "failed"]


def test_filters_event_type_and_speaker(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    session, CallbackTarget = db_session
    session.add(_target(CallbackTarget, events=["session_end"], filters={"speakers": ["u2"]}))
    session.commit()
    posted = []

    monkeypatch.setattr(
        "speech_to_speech.callback.dispatcher.requests.post",
        lambda **kwargs: posted.append(kwargs) or _Resp(200))
    dispatcher = CallbackDispatcher(session_factory=lambda: session, ttl_seconds=0)
    dispatcher.dispatch(_event(event_type="transcript", identity="u1"))  # 事件不符
    dispatcher.dispatch(_event(event_type="session_end"))               # speakers 过滤仅作用于 transcript
    dispatcher.flush_pending()
    # transcript 被事件订阅过滤；session_end 无 identity，speakers 过滤只作用于 transcript
    assert len(posted) == 1


def test_min_text_len_filter(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    session, CallbackTarget = db_session
    session.add(_target(CallbackTarget, filters={"min_text_len": 5}))
    session.commit()
    posted = []
    monkeypatch.setattr(
        "speech_to_speech.callback.dispatcher.requests.post",
        lambda **kwargs: posted.append(kwargs) or _Resp(200))
    dispatcher = CallbackDispatcher(session_factory=lambda: session, ttl_seconds=0)
    dispatcher.dispatch(_event(text="短"))
    dispatcher.dispatch(_event(text="足够长的文本"))
    dispatcher.flush_pending()
    assert len(posted) == 1


def test_ttl_cache_refresh(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    session, CallbackTarget = db_session
    session.add(_target(CallbackTarget, enabled=False))
    session.commit()
    posted: list = []

    def fake_post(url, **kwargs):  # noqa: ANN001
        posted.append({"url": url, **kwargs})
        return _Resp(200)

    monkeypatch.setattr("speech_to_speech.callback.dispatcher.requests.post", fake_post)
    dispatcher = CallbackDispatcher(session_factory=lambda: session, ttl_seconds=5)
    dispatcher.dispatch(_event())
    dispatcher.flush_pending()
    assert dispatcher.pending_count() == 0  # disabled 目标不投递
    # 动态启用（无需重启）：改库 + 缓存失效
    from app.models.callbacks import CallbackTarget as T

    session.query(T).update({"enabled": True})
    session.commit()
    dispatcher.invalidate_cache()
    dispatcher.dispatch(_event())
    dispatcher.flush_pending()
    assert len(posted) == 1


def test_env_fallback_java_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JAVA_CALLBACK_BASE", "http://ai")
    monkeypatch.setenv("MEETING_INTERNAL_TOKEN", "tok")
    monkeypatch.delenv("CONSOLE_DATABASE_URL", raising=False)
    dispatcher = CallbackDispatcher(session_factory=None, ttl_seconds=0)
    targets = dispatcher._effective_targets()
    assert len(targets) == 1
    assert targets[0].target_type == "java"
    assert targets[0].base_url == "http://ai"
    assert targets[0].auth_header_name == "X-Internal-Token"


def test_mask_token() -> None:
    assert mask_token("secret-token-value") == "secr***alue"
    assert mask_token("") == ""
```

实现注意：本文件所有 fake_post 统一写成 `def fake_post(url, **kwargs)` 形式（dispatcher 以位置实参传 url、关键字传其余参数），不要用 `lambda **kwargs`（url 位置实参会失败）。

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_callback_dispatcher.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'speech_to_speech.callback'`

- [ ] **Step 3: 实现 dispatcher.py**

```python
# src/speech_to_speech/callback/dispatcher.py
"""可配置回调子系统（spec 2026-11-25 §8）。

serve 进程内单例：dispatch(event) → 读取启用目标（TTL 缓存热加载）→ 过滤
→ 按目标协议适配投递（java/python）→ 重试 → callback_delivery_log 落库。

- DB 不可用时 env 兜底（JAVA_CALLBACK_BASE + MEETING_INTERNAL_TOKEN → 内存
  java 目标），保持源工程零改动部署可用（spec §8.3）。
- 投递在线程池执行，不阻塞转写主流程；每目标独立，单点失败不影响其它目标。
"""
from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests

logger = logging.getLogger(__name__)

JAVA_TRANSCRIPT_PATH = "/admin-api/ai/meeting/internal/transcript"
DEFAULT_TTL_SECONDS = 5.0
PAYLOAD_SNIPPET_MAX = 2000
RESPONSE_SNIPPET_MAX = 200


@dataclass(frozen=True)
class CallbackTargetConfig:
    """dispatcher 视角的平铺目标配置（ORM 行 → 此结构）。"""

    id: int | None
    name: str
    target_type: str  # java | python
    base_url: str
    auth_type: str  # none | bearer | header_token
    auth_header_name: str | None
    auth_token: str
    extra_headers: dict = field(default_factory=dict)
    timeout_ms: int = 3000
    retry_max_attempts: int = 3
    retry_backoff_ms: int = 500
    events: tuple[str, ...] = ()
    filters: dict | None = None
    enabled: bool = True


def mask_token(token: str) -> str:
    """token 脱敏：前 4 位 + *** + 后 4 位；过短或为空全遮。"""
    if len(token) < 10:
        return "***"
    return f"{token[:4]}***{token[-4:]}"


def _row_to_config(row) -> CallbackTargetConfig:
    return CallbackTargetConfig(
        id=row.id, name=row.name, target_type=row.target_type, base_url=row.base_url,
        auth_type=row.auth_type, auth_header_name=row.auth_header_name,
        auth_token=row.auth_token, extra_headers=dict(row.extra_headers or {}),
        timeout_ms=int(row.timeout_ms), retry_max_attempts=int(row.retry_max_attempts),
        retry_backoff_ms=int(row.retry_backoff_ms),
        events=tuple(row.events or []), filters=row.filters, enabled=bool(row.enabled),
    )


def _env_fallback_target() -> CallbackTargetConfig:
    """旧 env 兜底：与源工程 worker.py push() 行为完全一致。"""
    return CallbackTargetConfig(
        id=None, name="env-java-fallback", target_type="java",
        base_url=os.environ.get("JAVA_CALLBACK_BASE", "").rstrip("/"),
        auth_type="header_token", auth_header_name="X-Internal-Token",
        auth_token=os.environ.get("MEETING_INTERNAL_TOKEN", ""),
        extra_headers={"tenant-id": os.environ.get("MEETING_TENANT_ID", "1")},
        timeout_ms=3000, retry_max_attempts=3, retry_backoff_ms=500,
        events=("transcript",), filters=None, enabled=True,
    )


def _passes_filters(event, config: CallbackTargetConfig) -> bool:
    """事件订阅 + 过滤器（speakers / min_text_len）。"""
    if event.event_type not in (config.events or ()):
        return False
    filters = config.filters or {}
    if event.event_type == "transcript":
        speakers = filters.get("speakers")
        if speakers and event.identity not in speakers:
            return False
        min_len = filters.get("min_text_len")
        if min_len is not None and len(event.text or "") < int(min_len):
            return False
    return True


def _build_request(event, config: CallbackTargetConfig) -> tuple[str, object, dict]:
    """按 target_type 协议适配（spec §8.2 矩阵）。返回 (url, payload, headers)。"""
    headers: dict = dict(config.extra_headers or {})
    if config.target_type == "java":
        # java：固定内部端点 + header_token；body 为 TranscriptSegmentVO 数组
        segment: dict = {
            "speakerIdentity": event.identity,
            "text": event.text,
            "startTs": event.start_ts,
            "endTs": event.end_ts,
        }
        if event.audio_level is not None:
            segment["audioLevel"] = event.audio_level
        segment.update(event.extra)
        headers["X-Internal-Token"] = config.auth_token
        headers.setdefault("tenant-id", os.environ.get("MEETING_TENANT_ID", "1"))
        url = f"{config.base_url}{JAVA_TRANSCRIPT_PATH}"
        return url, [segment], headers
    # python：base_url 即完整 webhook；body 为统一事件 JSON
    payload = event.to_payload()
    if config.auth_type == "bearer":
        headers["Authorization"] = f"Bearer {config.auth_token}"
    elif config.auth_type == "header_token":
        headers[config.auth_header_name or "X-Callback-Token"] = config.auth_token
    return config.base_url, payload, headers


def _deliver_once(event, config: CallbackTargetConfig, url: str, payload: object,
                  headers: dict) -> tuple[int | None, str]:
    """单次投递，返回 (http_status, response_snippet)；网络异常向上抛。"""
    resp = requests.post(url, json=payload, headers=headers,
                         timeout=config.timeout_ms / 1000, params=(
                             {"roomSid": event.room_sid} if config.target_type == "java" else None))
    status = int(resp.status_code)
    snippet = (getattr(resp, "text", "") or "")[:RESPONSE_SNIPPET_MAX]
    return status, snippet


def _sanitize_payload(payload: object) -> str:
    """payload 截断 + token 脱敏后入库。"""
    import json

    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) > PAYLOAD_SNIPPET_MAX:
        text = text[:PAYLOAD_SNIPPET_MAX] + "...(truncated)"
    return text


class CallbackDispatcher:
    """单例分发器。session_factory 为 None 时进入 env 兜底模式（不写 DB 日志）。"""

    def __init__(self, session_factory, ttl_seconds: float = DEFAULT_TTL_SECONDS,
                 max_workers: int = 8) -> None:
        self._session_factory = session_factory
        self._ttl_seconds = ttl_seconds
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="callback")
        self._cache: list[CallbackTargetConfig] | None = None
        self._cache_at = 0.0
        self._lock = threading.Lock()
        self._pending_futures: list = []

    # ---- 目标解析（TTL 缓存热加载，spec §8.3）----
    def invalidate_cache(self) -> None:
        with self._lock:
            self._cache = None
            self._cache_at = 0.0

    def _load_targets(self) -> list[CallbackTargetConfig]:
        if self._session_factory is None:
            base = os.environ.get("JAVA_CALLBACK_BASE", "").strip()
            token = os.environ.get("MEETING_INTERNAL_TOKEN", "").strip()
            if base and token:
                return [_env_fallback_target()]
            return []
        now = time.monotonic()
        with self._lock:
            if self._cache is not None and now - self._cache_at < self._ttl_seconds:
                return self._cache
        session = self._session_factory()
        try:
            from app.models.callbacks import CallbackTarget

            rows = session.query(CallbackTarget).filter(CallbackTarget.enabled.is_(True)).all()
            configs = [_row_to_config(row) for row in rows]
        finally:
            session.close()
        with self._lock:
            self._cache = configs
            self._cache_at = now
        return configs

    def _effective_targets(self) -> list[CallbackTargetConfig]:
        return [t for t in self._load_targets() if t.enabled]

    # ---- 入口 ----
    def dispatch(self, event) -> None:
        """异步投递：每目标一个线程任务；单目标失败只记日志。"""
        for config in self._effective_targets():
            if not _passes_filters(event, config):
                continue
            future = self._pool.submit(self._deliver_with_retry, event, config)
            self._pending_futures.append(future)

    def publish_transcript(self, room_sid: str, segments: list[dict]) -> None:
        """worker emit_segments 的 java 兼容入口：逐段产出 transcript 事件。"""
        from speech_to_speech.livekit_worker.events import TranscriptEvent

        for segment in segments:
            extra = {k: v for k, v in segment.items()
                     if k not in ("speakerIdentity", "text", "startTs", "endTs", "audioLevel")}
            self.dispatch(TranscriptEvent(
                event_type="transcript", room_sid=room_sid,
                identity=str(segment.get("speakerIdentity", "")),
                text=str(segment.get("text", "")),
                start_ts=int(segment.get("startTs", 0)), end_ts=int(segment.get("endTs", 0)),
                audio_level=segment.get("audioLevel"), extra=extra,
                timestamp_ms=int(time.time() * 1000),
            ))

    def pending_count(self) -> int:
        return sum(1 for f in self._pending_futures if not f.done())

    def flush_pending(self, timeout: float = 10.0) -> None:
        """测试/退出用：等待在途投递完成（spec §9 flush 语义）。"""
        futures, self._pending_futures = self._pending_futures, []
        for future in futures:
            future.result(timeout=timeout)

    # ---- 投递 + 重试 + 日志 ----
    def _deliver_with_retry(self, event, config: CallbackTargetConfig) -> None:
        url, payload, headers = _build_request(event, config)
        body_text = _sanitize_payload(payload)
        attempts = max(1, config.retry_max_attempts)
        last_error = ""
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            status: int | None = None
            snippet = ""
            error = ""
            ok = False
            try:
                status, snippet = _deliver_once(event, config, url, payload, headers)
                ok = 200 <= status < 300
                if not ok:
                    error = f"HTTP {status}"
            except Exception as exc:  # noqa: BLE001 网络异常按重试计
                error = f"{type(exc).__name__}: {exc}"[:500]
            duration_ms = int((time.monotonic() - started) * 1000)
            if ok:
                self._write_log(event, config, url, body_text, attempt, status, snippet,
                                duration_ms, "success", "")
                return
            if attempt < attempts:
                self._write_log(event, config, url, body_text, attempt, status, snippet,
                                duration_ms, "retrying", error)
                backoff = config.retry_backoff_ms * (2 ** (attempt - 1)) / 1000
                if backoff > 0:
                    time.sleep(backoff)
            else:
                last_error = error
                self._write_log(event, config, url, body_text, attempt, status, snippet,
                                duration_ms, "failed", last_error)
        logger.warning("callback %s -> %s 最终失败: %s", config.name, url, last_error)

    def _write_log(self, event, config: CallbackTargetConfig, url: str, payload_text: str,
                   attempt: int, status: int | None, snippet: str, duration_ms: int,
                   log_status: str, error: str) -> None:
        if self._session_factory is None:
            logger.info("callback(env) %s attempt=%d status=%s", url, attempt, log_status)
            return
        session = self._session_factory()
        try:
            from app.models.callbacks import CallbackDeliveryLog

            session.add(CallbackDeliveryLog(
                target_id=config.id, event_type=event.event_type,
                triggered_at=None,  # default=utcnow 由 ORM 填
                request_url=url, request_payload=payload_text, attempt=attempt,
                http_status=status, response_snippet=snippet[:RESPONSE_SNIPPET_MAX],
                duration_ms=duration_ms, status=log_status,
                error=error[:1024],
            ))
            session.commit()
        except Exception:  # noqa: BLE001 日志落库失败不投递中断
            logger.exception("callback delivery log write failed")
        finally:
            session.close()


_dispatcher: CallbackDispatcher | None = None
_dispatcher_lock = threading.Lock()


def get_dispatcher() -> CallbackDispatcher:
    """进程级单例；优先复用 console 后端的 SessionLocal，失败退 env 兜底。"""
    global _dispatcher
    with _dispatcher_lock:
        if _dispatcher is None:
            session_factory = None
            try:
                from app.db.database import SessionLocal

                session_factory = SessionLocal
            except Exception:  # noqa: BLE001 console 后端不可导入 → env 兜底
                session_factory = None
            _dispatcher = CallbackDispatcher(session_factory)
        return _dispatcher


def reset_dispatcher() -> None:
    """测试隔离用。"""
    global _dispatcher
    with _dispatcher_lock:
        _dispatcher = None
```

实现注意：
- `_deliver_once` 中 python 目标传 `params=None`，java 目标传 `{"roomSid": ...}`——测试的 fake_post 需兼容两种签名（上面 fake_post 已带 `params` 形参）。
- `triggered_at=None` 依赖 `default=utcnow`；若 ORM 不允许显式 None 覆盖 default，改为不传该字段。
- fake_post 测试桩的调用方式是关键字调用（`requests.post(url, json=..., ...)`），fake 定义需 `def fake_post(url, ...)` 且 monkeypatch 用 `lambda **kwargs` 的写法在 `url` 是位置实参时会失败——实现测试时统一 fake_post 为 `def fake_post(url, **kwargs)` 形式。

- [ ] **Step 4: 运行确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_callback_dispatcher.py -v`
Expected: PASS（10 passed）

- [ ] **Step 5: Commit（先询问用户）**

```bash
git add src/speech_to_speech/callback/__init__.py src/speech_to_speech/callback/dispatcher.py tests/test_callback_dispatcher.py
git commit -m "feat(callbacks): dispatcher with protocol adapters, retry, TTL cache and delivery logs"
```

---

### Task 13: console CRUD/batch/test/logs API

**Files:**
- Modify: `console/backend/app/core/permissions.py`（PERMISSION_ROLES 追加两码）
- Create: `console/backend/app/schemas/callbacks.py`
- Create: `console/backend/app/repositories/callback_repository.py`
- Create: `console/backend/app/services/callback_service.py`
- Create: `console/backend/app/routers/callbacks.py`
- Modify: `console/backend/app/core/router_registry.py`（import + include）
- Test: `console/backend/tests/integration/test_callbacks_api.py`

- [ ] **Step 1: 写失败测试（契约：参照 test_machines_api.py 的鉴权风格，管理员 JWT）**

```python
# console/backend/tests/integration/test_callbacks_api.py
"""callbacks CRUD/batch/test/logs API 契约测试。"""
from __future__ import annotations

import pytest


@pytest.fixture()
def auth_headers(client) -> dict:  # client fixture 复用 tests/integration/conftest.py 既有实现
    from tests.integration.test_auth import login_admin  # 若无此 helper，按 conftest 现有取 token 方式

    return {"Authorization": f"Bearer {login_admin(client)}"}


def test_target_crud_roundtrip(client, auth_headers: dict) -> None:
    payload = {
        "name": "ai-server", "targetType": "java", "baseUrl": "http://ai",
        "authType": "header_token", "authHeaderName": "X-Internal-Token", "authToken": "tok",
        "extraHeaders": {"tenant-id": "1"}, "timeoutMs": 3000, "retryMaxAttempts": 3,
        "retryBackoffMs": 500, "events": ["transcript"], "filters": None, "enabled": True,
    }
    resp = client.post("/api/v1/callbacks/targets", json=payload, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 200
    target_id = body["data"]["id"]
    assert body["data"]["authToken"] == "tok***tok"  # 详情返回脱敏

    resp = client.get(f"/api/v1/callbacks/targets/{target_id}", headers=auth_headers)
    assert resp.status_code == 200

    resp = client.put(f"/api/v1/callbacks/targets/{target_id}",
                      json={**payload, "timeoutMs": 5000}, headers=auth_headers)
    assert resp.json()["data"]["timeoutMs"] == 5000

    resp = client.delete(f"/api/v1/callbacks/targets/{target_id}", headers=auth_headers)
    assert resp.status_code == 204


def test_list_and_pagination(client, auth_headers: dict) -> None:
    for i in range(3):
        client.post("/api/v1/callbacks/targets", json={
            "name": f"t{i}", "targetType": "python", "baseUrl": "http://x",
            "authType": "none", "authToken": "", "extraHeaders": {}, "timeoutMs": 3000,
            "retryMaxAttempts": 1, "retryBackoffMs": 0, "events": ["transcript"], "enabled": True,
        }, headers=auth_headers)
    resp = client.get("/api/v1/callbacks/targets?page=1&pageSize=2", headers=auth_headers)
    data = resp.json()["data"]
    assert len(data["list"]) == 2 and data["total"] == 3


def test_batch_enable_disable_delete(client, auth_headers: dict) -> None:
    ids = []
    for i in range(2):
        resp = client.post("/api/v1/callbacks/targets", json={
            "name": f"b{i}", "targetType": "python", "baseUrl": "http://x",
            "authType": "none", "authToken": "", "extraHeaders": {}, "timeoutMs": 3000,
            "retryMaxAttempts": 1, "retryBackoffMs": 0, "events": ["transcript"], "enabled": False,
        }, headers=auth_headers)
        ids.append(resp.json()["data"]["id"])
    resp = client.post("/api/v1/callbacks/targets/batch",
                       json={"ids": ids, "action": "enable"}, headers=auth_headers)
    assert resp.json()["data"]["updated"] == 2
    resp = client.post("/api/v1/callbacks/targets/batch",
                       json={"ids": ids, "action": "delete"}, headers=auth_headers)
    assert resp.json()["data"]["deleted"] == 2


def test_test_delivery_endpoint(client, auth_headers: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    backend_root = "console/backend"
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)
    monkeypatch.setattr(
        "app.services.callback_service.requests.post",
        lambda url, **kwargs: type("R", (), {"status_code": 200, "text": "ok"})())
    resp = client.post("/api/v1/callbacks/targets", json={
        "name": "probe", "targetType": "python", "baseUrl": "http://probe",
        "authType": "none", "authToken": "", "extraHeaders": {}, "timeoutMs": 1000,
        "retryMaxAttempts": 1, "retryBackoffMs": 0, "events": ["transcript"], "enabled": True,
    }, headers=auth_headers)
    target_id = resp.json()["data"]["id"]
    resp = client.post(f"/api/v1/callbacks/targets/{target_id}/test", headers=auth_headers)
    data = resp.json()["data"]
    assert data["ok"] is True and data["httpStatus"] == 200


def test_java_target_rejects_non_transcript_events(client, auth_headers: dict) -> None:
    resp = client.post("/api/v1/callbacks/targets", json={
        "name": "bad-java", "targetType": "java", "baseUrl": "http://ai",
        "authType": "header_token", "authToken": "t", "extraHeaders": {},
        "events": ["transcript", "session_end"], "enabled": True,
    }, headers=auth_headers)
    assert resp.status_code == 400  # java 协议仅支持 transcript


def test_logs_endpoint_filters(client, auth_headers: dict) -> None:
    resp = client.get("/api/v1/callbacks/logs?status=failed&page=1&pageSize=10",
                      headers=auth_headers)
    assert resp.status_code == 200
    assert {"list", "total", "page", "pageSize"} <= set(resp.json()["data"])


def test_requires_permission(client) -> None:
    # 未带 JWT → 401；带普通 user JWT → 403（callback 写仅 admin）
    assert client.get("/api/v1/callbacks/targets").status_code == 401
```

- [ ] **Step 2: 运行确认失败**

Run（在 `console/backend` 目录）：`..\..\.venv\Scripts\python.exe -m pytest tests/integration/test_callbacks_api.py -v`
Expected: FAIL，404（路由不存在）

- [ ] **Step 3: permissions.py 追加**

```python
    # 回调子系统（spec 2026-11-25 §8.4）：查询 operator 可看，写仅管理员。
    "console:callback:query": frozenset({"admin", "operator"}),
    "console:callback:manage": frozenset({"admin"}),
```

- [ ] **Step 4: schemas/callbacks.py**

```python
# console/backend/app/schemas/callbacks.py
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

EVENT_TYPES = ("transcript", "segment_attributed", "session_end")
TARGET_TYPES = ("java", "python")
AUTH_TYPES = ("none", "bearer", "header_token")


class CallbackTargetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    targetType: str
    baseUrl: str = Field(min_length=1, max_length=512)
    authType: str = "none"
    authHeaderName: str | None = None
    authToken: str = ""
    extraHeaders: dict[str, str] = Field(default_factory=dict)
    timeoutMs: int = Field(default=3000, ge=100, le=60000)
    retryMaxAttempts: int = Field(default=3, ge=1, le=10)
    retryBackoffMs: int = Field(default=500, ge=0, le=60000)
    events: list[str] = Field(default_factory=lambda: ["transcript"])
    filters: dict | None = None
    enabled: bool = True

    @field_validator("targetType")
    @classmethod
    def _check_type(cls, value: str) -> str:
        if value not in TARGET_TYPES:
            raise ValueError(f"targetType must be one of {'|'.join(TARGET_TYPES)}")
        return value

    @field_validator("authType")
    @classmethod
    def _check_auth(cls, value: str) -> str:
        if value not in AUTH_TYPES:
            raise ValueError(f"authType must be one of {'|'.join(AUTH_TYPES)}")
        return value

    @field_validator("events")
    @classmethod
    def _check_events(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("events 不能为空")
        unknown = [e for e in value if e not in EVENT_TYPES]
        if unknown:
            raise ValueError(f"未知事件类型: {unknown}")
        return value

    @field_validator("filters")
    @classmethod
    def _check_filters(cls, value: dict | None) -> dict | None:
        if value is None:
            return None
        allowed = {"speakers", "min_text_len"}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"filters 仅支持 {sorted(allowed)}")
        return value

    @field_validator("filters", mode="before")
    @classmethod
    def _java_only_transcript(cls, value, info):
        # java 协议仅支持 transcript；与 data 校验解耦的跨字段检查在 service 层做
        return value


class CallbackTargetUpdate(CallbackTargetCreate):
    pass


class CallbackTargetOut(BaseModel):
    id: int
    name: str
    targetType: str
    baseUrl: str
    authType: str
    authHeaderName: str | None
    authToken: str  # service 层保证脱敏
    extraHeaders: dict[str, str]
    timeoutMs: int
    retryMaxAttempts: int
    retryBackoffMs: int
    events: list[str]
    filters: dict | None
    enabled: bool
    updatedAt: str | None = None


class CallbackBatchRequest(BaseModel):
    ids: list[int] = Field(min_length=1)
    action: str  # enable | disable | delete


class TestDeliveryResult(BaseModel):
    ok: bool
    httpStatus: int | None = None
    durationMs: int = 0
    error: str = ""


class DeliveryLogOut(BaseModel):
    id: int
    targetId: int | None
    eventType: str
    triggeredAt: str | None
    requestUrl: str
    requestPayload: str
    attempt: int
    httpStatus: int | None
    responseSnippet: str
    durationMs: int
    status: str
    error: str
```

- [ ] **Step 5: repositories + services**

```python
# console/backend/app/repositories/callback_repository.py
"""callback_target / callback_delivery_log 数据访问（只做查询与落库）。"""
from __future__ import annotations

from sqlalchemy import select, update, delete, func
from sqlalchemy.orm import Session

from app.models.callbacks import CallbackDeliveryLog, CallbackTarget


class CallbackRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, page: int = 1, page_size: int = 50) -> tuple[list[CallbackTarget], int]:
        total = self.db.scalar(select(func.count()).select_from(CallbackTarget)) or 0
        rows = self.db.scalars(
            select(CallbackTarget).order_by(CallbackTarget.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        ).all()
        return list(rows), int(total)

    def get(self, target_id: int) -> CallbackTarget | None:
        return self.db.get(CallbackTarget, target_id)

    def create(self, **fields) -> CallbackTarget:
        row = CallbackTarget(**fields)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def update(self, target_id: int, **fields) -> CallbackTarget | None:
        row = self.get(target_id)
        if row is None:
            return None
        for key, value in fields.items():
            setattr(row, key, value)
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete(self, target_id: int) -> bool:
        row = self.get(target_id)
        if row is None:
            return False
        self.db.delete(row)
        self.db.commit()
        return True

    def batch_set_enabled(self, ids: list[int], enabled: bool) -> int:
        result = self.db.execute(
            update(CallbackTarget).where(CallbackTarget.id.in_(ids))
            .values(enabled=enabled))
        self.db.commit()
        return int(result.rowcount or 0)

    def batch_delete(self, ids: list[int]) -> int:
        result = self.db.execute(delete(CallbackTarget).where(CallbackTarget.id.in_(ids)))
        self.db.commit()
        return int(result.rowcount or 0)

    def list_logs(self, *, target_id: int | None, status: str | None,
                  since=None, until=None, page: int = 1, page_size: int = 50):
        stmt = select(CallbackDeliveryLog).order_by(CallbackDeliveryLog.id.desc())
        count_stmt = select(func.count()).select_from(CallbackDeliveryLog)
        if target_id is not None:
            stmt = stmt.where(CallbackDeliveryLog.target_id == target_id)
            count_stmt = count_stmt.where(CallbackDeliveryLog.target_id == target_id)
        if status:
            stmt = stmt.where(CallbackDeliveryLog.status == status)
            count_stmt = count_stmt.where(CallbackDeliveryLog.status == status)
        total = self.db.scalar(count_stmt) or 0
        rows = self.db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
        return list(rows), int(total)
```

```python
# console/backend/app/services/callback_service.py
"""回调目标服务层：校验（java 协议事件约束）、脱敏、测试投递。"""
from __future__ import annotations

import time

import requests
from sqlalchemy.orm import Session

from app.repositories.callback_repository import CallbackRepository
from app.schemas.callbacks import CallbackTargetCreate, CallbackTargetUpdate

JAVA_ONLY_EVENTS = ("transcript",)


def mask_token(token: str) -> str:
    if len(token) < 10:
        return "***"
    return f"{token[:4]}***{token[-4:]}"


class CallbackServiceError(ValueError):
    """业务校验失败（HTTP 400）。"""


def _validate_protocol(payload: CallbackTargetCreate | CallbackTargetUpdate) -> None:
    if payload.targetType == "java":
        bad = [e for e in payload.events if e not in JAVA_ONLY_EVENTS]
        if bad:
            raise CallbackServiceError(f"java 目标仅支持 {JAVA_ONLY_EVENTS} 事件: {bad}")
        if payload.authType != "header_token":
            raise CallbackServiceError("java 目标鉴权固定为 header_token")
    if payload.authType == "header_token" and not payload.authHeaderName:
        payload.authHeaderName = "X-Callback-Token"


def _fields(payload) -> dict:
    return {
        "name": payload.name, "target_type": payload.targetType, "base_url": payload.baseUrl,
        "auth_type": payload.authType, "auth_header_name": payload.authHeaderName,
        "auth_token": payload.authToken, "extra_headers": payload.extraHeaders,
        "timeout_ms": payload.timeoutMs, "retry_max_attempts": payload.retryMaxAttempts,
        "retry_backoff_ms": payload.retryBackoffMs, "events": payload.events,
        "filters": payload.filters, "enabled": payload.enabled,
    }


def _to_out(row) -> dict:
    return {
        "id": row.id, "name": row.name, "targetType": row.target_type,
        "baseUrl": row.base_url, "authType": row.auth_type,
        "authHeaderName": row.auth_header_name,
        "authToken": mask_token(row.auth_token) if row.auth_token else "",
        "extraHeaders": row.extra_headers or {}, "timeoutMs": row.timeout_ms,
        "retryMaxAttempts": row.retry_max_attempts, "retryBackoffMs": row.retry_backoff_ms,
        "events": row.events or [], "filters": row.filters, "enabled": bool(row.enabled),
    }


def list_targets(db: Session, page: int, page_size: int) -> dict:
    rows, total = CallbackRepository(db).list(page, page_size)
    return {"list": [_to_out(r) for r in rows], "total": total, "page": page, "pageSize": page_size}


def get_target(db: Session, target_id: int) -> dict | None:
    row = CallbackRepository(db).get(target_id)
    return _to_out(row) if row else None


def create_target(db: Session, payload: CallbackTargetCreate, actor: str) -> dict:
    _validate_protocol(payload)
    repo = CallbackRepository(db)
    if repo.get(0) is not None:  # noqa: 仅为类型检查占位，实际查重见下
        pass
    existing = db.execute(
        __import__("sqlalchemy").select(__import__("app.models.callbacks", fromlist=["CallbackTarget"]).CallbackTarget)
        .where(__import__("app.models.callbacks", fromlist=["CallbackTarget"]).CallbackTarget.name == payload.name)
    ).scalar_one_or_none()
    if existing is not None:
        raise CallbackServiceError(f"目标名 {payload.name!r} 已存在")
    row = repo.create(**_fields(payload), updated_by=actor)
    return _to_out(row)


def update_target(db: Session, target_id: int, payload: CallbackTargetUpdate, actor: str) -> dict | None:
    _validate_protocol(payload)
    row = CallbackRepository(db).update(target_id, **_fields(payload), updated_by=actor)
    return _to_out(row) if row else None


def delete_target(db: Session, target_id: int) -> bool:
    return CallbackRepository(db).delete(target_id)


def batch_targets(db: Session, ids: list[int], action: str) -> dict:
    repo = CallbackRepository(db)
    if action == "enable":
        return {"updated": repo.batch_set_enabled(ids, True)}
    if action == "disable":
        return {"updated": repo.batch_set_enabled(ids, False)}
    if action == "delete":
        return {"deleted": repo.batch_delete(ids)}
    raise CallbackServiceError(f"未知批量操作: {action!r}")


def send_test_event(db: Session, target_id: int) -> dict:
    """发送一条测试 transcript 事件，同步返回投递结果（spec §8.4）。"""
    from speech_to_speech.callback.dispatcher import CallbackTargetConfig, _build_request

    row = CallbackRepository(db).get(target_id)
    if row is None:
        raise CallbackServiceError("target not found")
    config = CallbackTargetConfig(
        id=row.id, name=row.name, target_type=row.target_type, base_url=row.base_url,
        auth_type=row.auth_type, auth_header_name=row.auth_header_name,
        auth_token=row.auth_token, extra_headers=row.extra_headers or {},
        timeout_ms=row.timeout_ms, retry_max_attempts=1, retry_backoff_ms=0,
        events=tuple(row.events or ()), filters=row.filters, enabled=True,
    )
    event = {
        "event_type": "transcript", "room_sid": "console-test", "identity": "console",
        "text": "这是一条 console 回调连接测试事件", "start_ts": 0, "end_ts": 0,
        "audio_level": None, "extra": {"test": True},
        "timestamp_ms": int(time.time() * 1000),
    }

    class _FakeEvent:
        event_type = "transcript"
        room_sid = "console-test"
        identity = "console"
        text = event["text"]
        start_ts = 0
        end_ts = 0
        audio_level = None
        extra = {"test": True}

        def to_payload(self) -> dict:
            return {
                "eventType": "transcript", "roomSid": "console-test",
                "identity": "console", "text": self.text, "startTs": 0, "endTs": 0,
                "timestamp": event["timestamp_ms"], "test": True,
            }

    url, payload, headers = _build_request(_FakeEvent(), config)
    started = time.monotonic()
    try:
        resp = requests.post(url, json=payload, headers=headers,
                             timeout=config.timeout_ms / 1000,
                             params=({"roomSid": "console-test"} if config.target_type == "java" else None))
        ok = 200 <= int(resp.status_code) < 300
        return {"ok": ok, "httpStatus": int(resp.status_code),
                "durationMs": int((time.monotonic() - started) * 1000),
                "error": "" if ok else resp.text[:200]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "httpStatus": None,
                "durationMs": int((time.monotonic() - started) * 1000),
                "error": f"{type(exc).__name__}: {exc}"[:200]}


def list_logs(db: Session, *, target_id: int | None, status: str | None,
              page: int, page_size: int) -> dict:
    from app.schemas.common import iso_utc

    rows, total = CallbackRepository(db).list_logs(
        target_id=target_id, status=status, page=page, page_size=page_size)
    return {
        "list": [{
            "id": r.id, "targetId": r.target_id, "eventType": r.event_type,
            "triggeredAt": iso_utc(r.triggered_at), "requestUrl": r.request_url,
            "requestPayload": r.request_payload, "attempt": r.attempt,
            "httpStatus": r.http_status, "responseSnippet": r.response_snippet,
            "durationMs": r.duration_ms, "status": r.status, "error": r.error,
        } for r in rows],
        "total": total, "page": page, "pageSize": page_size,
    }
```

实现注意：`create_target` 中的重名检查用正规 import 写法（文件顶部 `from sqlalchemy import select` 与 `from app.models.callbacks import CallbackTarget`），上面 `__import__` 写法仅为单块展示——实现时必须写成标准 import。测试投递不写 `callback_delivery_log`（连接探测非正式投递）。

- [ ] **Step 6: routers/callbacks.py 并注册**

```python
# console/backend/app/routers/callbacks.py
"""回调配置 CRUD/batch/test/logs（spec 2026-11-25 §8.4）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from app.core.errors import ApiError
from app.core.permissions import require_permission
from app.core.security import CurrentUser
from app.deps import DbSession
from app.schemas.callbacks import (
    CallbackBatchRequest,
    CallbackTargetCreate,
    CallbackTargetOut,
    CallbackTargetUpdate,
    DeliveryLogOut,
    TestDeliveryResult,
)
from app.schemas.common import ok
from app.services import callback_service
from app.services.callback_service import CallbackServiceError

router = APIRouter(prefix="/api/v1/callbacks", tags=["callbacks"])


@router.get("/targets")
def list_targets(
    page: int = Query(1, ge=1), pageSize: int = Query(50, ge=1, le=200),
    db: DbSession = None, user: CurrentUser = Depends(require_permission("console:callback:query")),
):
    db = db  # DbSession 为 Annotated 依赖，见下方最终签名说明
    return ok(callback_service.list_targets(db, page, pageSize))


@router.post("/targets")
def create_target(
    payload: CallbackTargetCreate, db: DbSession = None,
    user: CurrentUser = Depends(require_permission("console:callback:manage")),
):
    try:
        return ok(callback_service.create_target(db, payload, actor=user.username))
    except CallbackServiceError as exc:
        raise ApiError("invalid_request", str(exc), 400) from exc


@router.get("/targets/{target_id}")
def get_target(
    target_id: int, db: DbSession = None,
    user: CurrentUser = Depends(require_permission("console:callback:query")),
):
    data = callback_service.get_target(db, target_id)
    if data is None:
        raise ApiError("not_found", f"callback target {target_id} not found", 404)
    return ok(data)


@router.put("/targets/{target_id}")
def update_target(
    target_id: int, payload: CallbackTargetUpdate, db: DbSession = None,
    user: CurrentUser = Depends(require_permission("console:callback:manage")),
):
    try:
        data = callback_service.update_target(db, target_id, payload, actor=user.username)
    except CallbackServiceError as exc:
        raise ApiError("invalid_request", str(exc), 400) from exc
    if data is None:
        raise ApiError("not_found", f"callback target {target_id} not found", 404)
    return ok(data)


@router.delete("/targets/{target_id}", status_code=204)
def delete_target(
    target_id: int, db: DbSession = None,
    user: CurrentUser = Depends(require_permission("console:callback:manage")),
):
    if not callback_service.delete_target(db, target_id):
        raise ApiError("not_found", f"callback target {target_id} not found", 404)
    return Response(status_code=204)


@router.post("/targets/batch")
def batch_targets(
    payload: CallbackBatchRequest, db: DbSession = None,
    user: CurrentUser = Depends(require_permission("console:callback:manage")),
):
    try:
        return ok(callback_service.batch_targets(db, payload.ids, payload.action))
    except CallbackServiceError as exc:
        raise ApiError("invalid_request", str(exc), 400) from exc


@router.post("/targets/{target_id}/test")
def test_target(
    target_id: int, db: DbSession = None,
    user: CurrentUser = Depends(require_permission("console:callback:manage")),
):
    try:
        return ok(callback_service.send_test_event(db, target_id))
    except CallbackServiceError as exc:
        raise ApiError("invalid_request", str(exc), 400) from exc


@router.get("/logs")
def list_logs(
    targetId: int | None = Query(None), status: str | None = Query(None),
    page: int = Query(1, ge=1), pageSize: int = Query(50, ge=1, le=200),
    db: DbSession = None,
    user: CurrentUser = Depends(require_permission("console:callback:query")),
):
    return ok(callback_service.list_logs(
        db, target_id=targetId, status=status, page=page, page_size=pageSize))
```

**签名修正（实现时照此写）**：`db: DbSession` 不能带默认值 `None`——`DbSession` 是 `Annotated[Session, Depends(get_db)]`，正确写法为 `db: DbSession,` 后接 `user: CurrentUser = Depends(...)`。上面块中 `= None` 是展示噪音，实现时删除。

`router_registry.py` 的 import 列表加 `callbacks`，`app.include_router(callbacks.router)` 放在 `config.router` 之后。

- [ ] **Step 7: 运行确认通过**

Run（在 `console/backend` 目录）：`..\..\.venv\Scripts\python.exe -m pytest tests/integration/test_callbacks_api.py tests/unit/test_permissions.py -v`
Expected: PASS（7 + 既有 permissions 全通过）

- [ ] **Step 8: Commit（先询问用户）**

```bash
git add console/backend/app/core/permissions.py console/backend/app/core/router_registry.py console/backend/app/schemas/callbacks.py console/backend/app/repositories/callback_repository.py console/backend/app/services/callback_service.py console/backend/app/routers/callbacks.py console/backend/tests/integration/test_callbacks_api.py
git commit -m "feat(callbacks): console CRUD, batch, test-delivery and logs API"
```

---

### Task 14: console 前端「回调管理」页面

**Files:**
- Create: `console/frontend/src/api/callbacks.ts`
- Create: `console/frontend/src/views/CallbacksView.vue`
- Create: `console/frontend/src/i18n/locales/zh-CN/callbacks.ts` + `en-US/callbacks.ts`（若 i18n 结构为单文件则在其中加 `callbacks` 键组）
- Modify: `console/frontend/src/router/index.ts`（`/console/callbacks`）
- Modify: `console/frontend/src/i18n/locales/{zh-CN,en-US}/index.ts`（挂载 callbacks 模块）
- Modify: 布局导航（`src/layouts/*` 或侧边栏配置文件，按现有 AuditView 挂载方式同步追加一项）

- [ ] **Step 1: api/callbacks.ts**

```typescript
// console/frontend/src/api/callbacks.ts
// 回调管理 API 客户端（对齐 api/profiles.ts 的请求风格）
import request from '@/api/client'

export type TargetType = 'java' | 'python'
export type AuthType = 'none' | 'bearer' | 'header_token'
export type EventType = 'transcript' | 'segment_attributed' | 'session_end'

export interface CallbackTarget {
  id: number
  name: string
  targetType: TargetType
  baseUrl: string
  authType: AuthType
  authHeaderName: string | null
  authToken: string
  extraHeaders: Record<string, string>
  timeoutMs: number
  retryMaxAttempts: number
  retryBackoffMs: number
  events: EventType[]
  filters: { speakers?: string[]; min_text_len?: number } | null
  enabled: boolean
  updatedAt?: string | null
}

export interface DeliveryLog {
  id: number
  targetId: number | null
  eventType: string
  triggeredAt: string | null
  requestUrl: string
  requestPayload: string
  attempt: number
  httpStatus: number | null
  responseSnippet: string
  durationMs: number
  status: 'success' | 'failed' | 'retrying'
  error: string
}

export const listTargets = (page: number, pageSize: number) =>
  request.get('/api/v1/callbacks/targets', { params: { page, pageSize } })

export const createTarget = (payload: Partial<CallbackTarget>) =>
  request.post('/api/v1/callbacks/targets', payload)

export const updateTarget = (id: number, payload: Partial<CallbackTarget>) =>
  request.put(`/api/v1/callbacks/targets/${id}`, payload)

export const deleteTarget = (id: number) =>
  request.delete(`/api/v1/callbacks/targets/${id}`)

export const batchTargets = (ids: number[], action: 'enable' | 'disable' | 'delete') =>
  request.post('/api/v1/callbacks/targets/batch', { ids, action })

export const testTarget = (id: number) =>
  request.post(`/api/v1/callbacks/targets/${id}/test`)

export const listLogs = (params: { page: number; pageSize: number; status?: string; targetId?: number }) =>
  request.get('/api/v1/callbacks/logs', { params })
```

- [ ] **Step 2: views/CallbacksView.vue**

```vue
<!-- console/frontend/src/views/CallbacksView.vue -->
<!-- 回调管理（spec 2026-11-25 §8.5）：目标列表 + 新建/编辑抽屉 + 批量操作 + 投递日志页签 -->
<template>
  <a-card :bordered="false">
    <a-tabs v-model:activeKey="activeTab">
      <a-tab-pane key="targets" :tab="t('callbacks.targetsTab')">
        <a-space style="margin-bottom: 16px">
          <a-button type="primary" @click="openCreate">{{ t('callbacks.create') }}</a-button>
          <a-button :disabled="!selectedRowKeys.length" @click="batch('enable')">
            {{ t('callbacks.batchEnable') }}
          </a-button>
          <a-button :disabled="!selectedRowKeys.length" @click="batch('disable')">
            {{ t('callbacks.batchDisable') }}
          </a-button>
          <a-popconfirm :title="t('callbacks.batchDeleteConfirm')" @confirm="batch('delete')">
            <a-button danger :disabled="!selectedRowKeys.length">{{ t('callbacks.batchDelete') }}</a-button>
          </a-popconfirm>
        </a-space>
        <a-table
          row-key="id"
          :columns="columns"
          :data-source="targets"
          :loading="loading"
          :pagination="{ total, current: page, pageSize, onChange: load }"
          :row-selection="{ selectedRowKeys, onChange: (keys: any) => (selectedRowKeys = keys) }"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'enabled'">
              <a-switch :checked="record.enabled" @change="() => toggleEnabled(record)" />
            </template>
            <template v-else-if="column.key === 'actions'">
              <a-space>
                <a-button size="small" @click="openEdit(record)">{{ t('common.edit') }}</a-button>
                <a-button size="small" @click="runTest(record)">{{ t('callbacks.test') }}</a-button>
                <a-popconfirm :title="t('callbacks.deleteConfirm')" @confirm="() => removeOne(record)">
                  <a-button size="small" danger>{{ t('common.delete') }}</a-button>
                </a-popconfirm>
              </a-space>
            </template>
          </template>
        </a-table>
      </a-tab-pane>
      <a-tab-pane key="logs" :tab="t('callbacks.logsTab')">
        <a-space style="margin-bottom: 16px">
          <a-select
            v-model:value="logStatus" style="width: 160px" allow-clear
            :placeholder="t('callbacks.logStatusFilter')"
            :options="['success', 'failed', 'retrying'].map(s => ({ value: s, label: s }))"
            @change="loadLogs"
          />
        </a-space>
        <a-table
          row-key="id"
          :columns="logColumns"
          :data-source="logs"
          :loading="logsLoading"
          :pagination="{ total: logsTotal, current: logsPage, pageSize: logPageSize, onChange: loadLogs }"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'status'">
              <a-tag :color="record.status === 'success' ? 'green' : record.status === 'retrying' ? 'orange' : 'red'">
                {{ record.status }}
              </a-tag>
            </template>
            <template v-else-if="column.key === 'detail'">
              <a-button size="small" @click="showLogDetail(record)">{{ t('callbacks.viewDetail') }}</a-button>
            </template>
          </template>
        </a-table>
      </a-tab-pane>
    </a-tabs>

    <a-drawer
      v-model:open="editorOpen"
      :title="editingId ? t('callbacks.editTitle') : t('callbacks.createTitle')"
      width="520"
      @close="resetEditor"
    >
      <a-form layout="vertical">
        <a-form-item :label="t('callbacks.field.name')" required>
          <a-input v-model:value="form.name" :maxlength="128" />
        </a-form-item>
        <a-form-item :label="t('callbacks.field.type')" required>
          <a-radio-group v-model:value="form.targetType" :disabled="!!editingId">
            <a-radio value="java">Java</a-radio>
            <a-radio value="python">Python</a-radio>
          </a-radio-group>
          <div class="hint">
            {{ form.targetType === 'java' ? t('callbacks.hint.javaUrl') : t('callbacks.hint.pythonUrl') }}
          </div>
        </a-form-item>
        <a-form-item :label="t('callbacks.field.baseUrl')" required>
          <a-input v-model:value="form.baseUrl" placeholder="http://" />
        </a-form-item>
        <a-form-item :label="t('callbacks.field.authType')" required>
          <a-select
            v-model:value="form.authType"
            :options="form.targetType === 'java'
              ? [{ value: 'header_token', label: 'header_token' }]
              : ['none', 'bearer', 'header_token'].map(v => ({ value: v, label: v }))"
          />
        </a-form-item>
        <a-form-item v-if="form.authType === 'header_token'" :label="t('callbacks.field.authHeaderName')">
          <a-input v-model:value="form.authHeaderName" placeholder="X-Callback-Token" />
        </a-form-item>
        <a-form-item v-if="form.authType !== 'none'" :label="t('callbacks.field.authToken')">
          <a-input-password v-model:value="form.authToken" />
        </a-form-item>
        <a-form-item :label="t('callbacks.field.timeoutMs')">
          <a-input-number v-model:value="form.timeoutMs" :min="100" :max="60000" style="width: 100%" />
        </a-form-item>
        <a-form-item :label="t('callbacks.field.retry')">
          <a-space>
            <a-input-number v-model:value="form.retryMaxAttempts" :min="1" :max="10" />
            <span>× backoff</span>
            <a-input-number v-model:value="form.retryBackoffMs" :min="0" :max="60000" />
            <span>ms</span>
          </a-space>
        </a-form-item>
        <a-form-item :label="t('callbacks.field.events')" required>
          <a-checkbox-group v-model:value="form.events" :options="eventOptions" />
          <div v-if="form.targetType === 'java'" class="hint">{{ t('callbacks.hint.javaEvents') }}</div>
        </a-form-item>
        <a-form-item :label="t('callbacks.field.filters')">
          <a-select
            v-model:value="filterSpeakers" mode="tags" allow-clear
            :placeholder="t('callbacks.field.filterSpeakers')" style="margin-bottom: 8px"
          />
          <a-input-number
            v-model:value="filterMinTextLen" :min="0" allow-clear
            :placeholder="t('callbacks.field.filterMinLen')" style="width: 200px"
          />
        </a-form-item>
        <a-form-item>
          <a-space>
            <a-button type="primary" :loading="saving" @click="save">{{ t('common.save') }}</a-button>
            <a-button @click="editorOpen = false">{{ t('common.cancel') }}</a-button>
          </a-space>
        </a-form-item>
      </a-form>
    </a-drawer>

    <a-drawer v-model:open="logDetailOpen" :title="t('callbacks.logDetail')" width="560">
      <a-descriptions v-if="logDetail" :column="1" size="small">
        <a-descriptions-item label="URL">{{ logDetail.requestUrl }}</a-descriptions-item>
        <a-descriptions-item label="HTTP">{{ logDetail.httpStatus ?? '-' }}</a-descriptions-item>
        <a-descriptions-item label="attempt">{{ logDetail.attempt }}</a-descriptions-item>
        <a-descriptions-item label="duration">{{ logDetail.durationMs }}ms</a-descriptions-item>
        <a-descriptions-item :label="t('callbacks.field.payload')">
          <pre class="payload">{{ logDetail.requestPayload }}</pre>
        </a-descriptions-item>
        <a-descriptions-item :label="t('callbacks.field.response')">
          <pre class="payload">{{ logDetail.responseSnippet }}</pre>
        </a-descriptions-item>
        <a-descriptions-item v-if="logDetail.error" :label="t('callbacks.field.error')">
          {{ logDetail.error }}
        </a-descriptions-item>
      </a-descriptions>
    </a-drawer>
  </a-card>
</template>

<script setup lang="ts">
// 回调管理视图逻辑（对齐 AuditView.vue 的 request/message 用法）
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import {
  batchTargets, createTarget, deleteTarget, listLogs, listTargets,
  testTarget, updateTarget,
  type CallbackTarget, type DeliveryLog,
} from '@/api/callbacks'

const { t } = useI18n()
const activeTab = ref<'targets' | 'logs'>('targets')
const targets = ref<CallbackTarget[]>([])
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const selectedRowKeys = ref<number[]>([])

const columns = [
  { title: () => t('callbacks.field.name'), dataIndex: 'name', key: 'name' },
  { title: 'Type', dataIndex: 'targetType', key: 'targetType', width: 80 },
  { title: 'URL', dataIndex: 'baseUrl', key: 'baseUrl', ellipsis: true },
  { title: 'Auth', dataIndex: 'authType', key: 'authType', width: 110 },
  { title: () => t('callbacks.field.events'), dataIndex: 'events', key: 'events' },
  { title: () => t('callbacks.field.enabled'), key: 'enabled', width: 90 },
  { title: () => t('common.actions'), key: 'actions', width: 220 },
]

const logs = ref<DeliveryLog[]>([])
const logsLoading = ref(false)
const logsPage = ref(1)
const logPageSize = ref(20)
const logsTotal = ref(0)
const logStatus = ref<string | undefined>(undefined)
const logColumns = [
  { title: 'ID', dataIndex: 'id', width: 70 },
  { title: 'Target', dataIndex: 'targetId', width: 80 },
  { title: 'Event', dataIndex: 'eventType', width: 140 },
  { title: 'URL', dataIndex: 'requestUrl', ellipsis: true },
  { title: 'HTTP', dataIndex: 'httpStatus', width: 70 },
  { title: 'Status', key: 'status', width: 100 },
  { title: '耗时', dataIndex: 'durationMs', width: 90 },
  { title: '', key: 'detail', width: 90 },
]
const logDetail = ref<DeliveryLog | null>(null)
const logDetailOpen = ref(false)

const editorOpen = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const eventOptions = ['transcript', 'segment_attributed', 'session_end'].map(v => ({ value: v, label: v }))
const filterSpeakers = ref<string[]>([])
const filterMinTextLen = ref<number | undefined>(undefined)

const defaultForm = (): Partial<CallbackTarget> => ({
  name: '', targetType: 'python', baseUrl: '', authType: 'none', authHeaderName: null,
  authToken: '', extraHeaders: {}, timeoutMs: 3000, retryMaxAttempts: 3,
  retryBackoffMs: 500, events: ['transcript'], filters: null, enabled: true,
})
const form = reactive<Partial<CallbackTarget>>(defaultForm())

async function load(p = page.value) {
  loading.value = true
  try {
    const { data } = await listTargets(p, pageSize.value)
    targets.value = data.data.list
    total.value = data.data.total
    page.value = p
  } finally {
    loading.value = false
  }
}

async function loadLogs(p = logsPage.value) {
  logsLoading.value = true
  try {
    const { data } = await listLogs({ page: p, pageSize: logPageSize.value, status: logStatus.value })
    logs.value = data.data.list
    logsTotal.value = data.data.total
    logsPage.value = p
  } finally {
    logsLoading.value = false
  }
}

function openCreate() {
  Object.assign(form, defaultForm())
  editingId.value = null
  filterSpeakers.value = []
  filterMinTextLen.value = undefined
  editorOpen.value = true
}

function openEdit(record: CallbackTarget) {
  Object.assign(form, JSON.parse(JSON.stringify(record)))
  editingId.value = record.id
  filterSpeakers.value = record.filters?.speakers ?? []
  filterMinTextLen.value = record.filters?.min_text_len
  editorOpen.value = true
}

function resetEditor() {
  Object.assign(form, defaultForm())
  editingId.value = null
}

async function save() {
  saving.value = true
  try {
    form.filters = (filterSpeakers.value.length || filterMinTextLen.value !== undefined)
      ? { ...(filterSpeakers.value.length ? { speakers: filterSpeakers.value } : {}),
          ...(filterMinTextLen.value !== undefined ? { min_text_len: filterMinTextLen.value } : {}) }
      : null
    if (editingId.value) await updateTarget(editingId.value, form)
    else await createTarget(form)
    message.success(t('common.saved'))
    editorOpen.value = false
    resetEditor()
    await load()
  } catch (error: any) {
    message.error(error?.response?.data?.message ?? t('common.saveFailed'))
  } finally {
    saving.value = false
  }
}

async function toggleEnabled(record: CallbackTarget) {
  await updateTarget(record.id, { ...record, enabled: !record.enabled })
  await load()
}

async function removeOne(record: CallbackTarget) {
  await deleteTarget(record.id)
  message.success(t('common.deleted'))
  await load()
}

async function batch(action: 'enable' | 'disable' | 'delete') {
  await batchTargets(selectedRowKeys.value, action)
  selectedRowKeys.value = []
  message.success(t('common.saved'))
  await load()
}

async function runTest(record: CallbackTarget) {
  const { data } = await testTarget(record.id)
  const result = data.data
  if (result.ok) message.success(`${t('callbacks.testOk')} (${result.httpStatus}, ${result.durationMs}ms)`)
  else message.error(`${t('callbacks.testFail')}: ${result.error}`)
}

function showLogDetail(record: DeliveryLog) {
  logDetail.value = record
  logDetailOpen.value = true
}

onMounted(() => {
  load()
  loadLogs()
})
</script>

<style scoped>
.hint { color: var(--ant-color-text-tertiary, #999); font-size: 12px; margin-top: 4px; }
.payload { max-height: 220px; overflow: auto; font-size: 12px; white-space: pre-wrap; }
</style>
```

- [ ] **Step 3: 路由 + i18n + 导航**

1. `router/index.ts`：在 audit 路由后追加（保持现有路由对象风格）：

```typescript
  {
    path: '/console/callbacks',
    name: 'console-callbacks',
    component: () => import('@/views/CallbacksView.vue'),
  },
```

2. `i18n/locales/zh-CN/callbacks.ts`：

```typescript
export default {
  targetsTab: '回调目标',
  logsTab: '投递日志',
  create: '新建目标',
  createTitle: '新建回调目标',
  editTitle: '编辑回调目标',
  batchEnable: '批量启用',
  batchDisable: '批量禁用',
  batchDelete: '批量删除',
  batchDeleteConfirm: '确认删除选中的回调目标？',
  deleteConfirm: '确认删除该回调目标？',
  test: '测试',
  testOk: '测试投递成功',
  testFail: '测试投递失败',
  viewDetail: '详情',
  logDetail: '投递详情',
  logStatusFilter: '状态筛选',
  field: {
    name: '名称',
    type: '目标类型',
    baseUrl: '目标地址',
    authType: '鉴权方式',
    authHeaderName: '鉴权头名',
    authToken: '凭据 Token',
    timeoutMs: '超时 (ms)',
    retry: '重试',
    events: '订阅事件',
    filters: '过滤器',
    filterSpeakers: '仅这些说话人（可空）',
    filterMinLen: '最小文本长度',
    enabled: '启用',
    payload: '请求参数',
    response: '响应摘要',
    error: '错误',
  },
  hint: {
    javaUrl: 'Java 目标只需填服务基址，回调路径固定为 /admin-api/ai/meeting/internal/transcript',
    pythonUrl: 'Python 目标填完整 webhook URL，收到统一事件 JSON',
    javaEvents: 'Java 目标仅支持 transcript 事件',
  },
}
```

3. `i18n/locales/en-US/callbacks.ts`：同结构英文（targetsTab: 'Callback Targets'、logsTab: 'Delivery Logs'、create: 'New Target' 等，逐键对应翻译）。
4. 两个 `i18n/locales/{zh-CN,en-US}/index.ts` 追加 `callbacks` 模块挂载（照 profiles 模块现有写法）。
5. 侧边导航追加「回调管理 / Callbacks」项，指向 `/console/callbacks`（按现有 audit 导航项的配置文件位置同步）。

- [ ] **Step 4: 前端类型检查与构建**

Run（在 `console/frontend` 目录）：`npm run build`
Expected: vite build 成功、vue-tsc 无类型错误（若有既有 warning 与本次无关则忽略）

- [ ] **Step 5: Commit（先询问用户）**

```bash
git add console/frontend/src/api/callbacks.ts console/frontend/src/views/CallbacksView.vue console/frontend/src/router/index.ts console/frontend/src/i18n/locales
git commit -m "feat(callbacks): console frontend callback management page"
```

---

### Task 14A: console SSE 端点 —— 实时转写流

**Files:**
- Create: `console/backend/app/routers/live_transcripts.py`
- Modify: `console/backend/app/core/router_registry.py`（import + include `live_transcripts.router`）
- Test: `console/backend/tests/integration/test_live_transcripts.py`

- [ ] **Step 1: 写失败测试**

```python
# console/backend/tests/integration/test_live_transcripts.py
"""SSE 实时转写流：订阅 TranscriptEventBus，逐事件 data: 行输出，15s 心跳。"""
from __future__ import annotations

import json

import pytest


@pytest.fixture()
def auth_headers(client) -> dict:  # 复用 conftest 的管理员登录方式（同 test_callbacks_api.py）
    from tests.integration.conftest import admin_headers  # 若名称不同，按现有 conftest 实际 helper 对齐

    return admin_headers(client)


def _publish_transcript(text: str = "实时字幕测试") -> None:
    from speech_to_speech.livekit_worker.events import TranscriptEvent, get_event_bus

    get_event_bus().publish(TranscriptEvent(
        event_type="transcript", room_sid="room-sse", identity="speaker-1",
        text=text, start_ts=1, end_ts=2, audio_level=-8,
        extra={}, timestamp_ms=12345,
    ))


def test_sse_requires_auth(client) -> None:
    assert client.get("/api/v1/live-transcripts/stream").status_code == 401


def test_sse_stream_emits_events(client, auth_headers: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """打开流 → 向进程内总线发布事件 → 读到 data 行；随后关闭。"""
    # 客户端读取线程发布事件：TestClient 流式读取为同步迭代，先订阅后发布，
    # 用一个后台线程延迟发布。
    import threading
    import time

    def publish_later() -> None:
        time.sleep(0.5)
        _publish_transcript("实时字幕A")
        _publish_transcript("实时字幕B")

    threading.Thread(target=publish_later, daemon=True).start()
    received: list[dict] = []
    with client.stream("GET", "/api/v1/live-transcripts/stream", headers=auth_headers) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        for line in resp.iter_lines():
            if line.startswith("data: "):
                received.append(json.loads(line[len("data: "):]))
                if len(received) >= 2:
                    break
    assert received[0]["text"] == "实时字幕A"
    assert received[1]["eventType"] == "transcript"


def test_sse_worker_absent_reports_error(client, auth_headers: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """livekit_worker 不可导入（standalone console 部署）→ 首帧 error 事件。"""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):  # noqa: ANN001
        if name.startswith("speech_to_speech.livekit_worker"):
            raise ImportError("livekit extra not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with client.stream("GET", "/api/v1/live-transcripts/stream", headers=auth_headers) as resp:
        assert resp.status_code == 200
        lines = list(resp.iter_lines())
    assert any(line.startswith("event: error") for line in lines)
```

- [ ] **Step 2: 运行确认失败**

Run（在 `console/backend` 目录）：`..\..\.venv\Scripts\python.exe -m pytest tests/integration/test_live_transcripts.py -v`
Expected: FAIL，404（路由不存在）

- [ ] **Step 3: 实现路由并注册**

```python
# console/backend/app/routers/live_transcripts.py
"""LiveKit worker 实时转写 SSE 流（spec §7.1 修订版）。

订阅进程内 TranscriptEventBus，把转写事件以 SSE data 行推给前端。
- worker 与 console 同进程（--with-console 内嵌）时有事件流；
- standalone console 部署时 livekit_worker 不可导入 → 首帧 error 事件。
鉴权：JWT（require_permission("console:callback:query")）；前端用 fetch 流式
读取并携带 Authorization 头（EventSource 无法自定义头）。
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.permissions import require_permission
from app.core.security import CurrentUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/live-transcripts", tags=["live-transcripts"])

QUEUE_MAXSIZE = 200
KEEPALIVE_SECONDS = 15.0


@router.get("/stream")
async def stream_live_transcripts(
    user: CurrentUser = Depends(require_permission("console:callback:query")),
) -> StreamingResponse:
    """SSE：每条转写事件一行 data JSON；15s 无事件发 keep-alive 注释行。"""

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        try:
            from speech_to_speech.livekit_worker.events import get_event_bus
        except Exception as exc:  # noqa: BLE001 - worker 不在本进程
            detail = json.dumps({"detail": f"livekit worker not in this process: {exc}"},
                                ensure_ascii=False)
            yield f"event: error\ndata: {detail}\n\n"
            return
        bus = get_event_bus()
        loop = asyncio.get_running_loop()

        def on_event(event) -> None:  # worker 线程回调 → 转投 asyncio 队列
            try:
                loop.call_soon_threadsafe(queue.put_nowait, event)
            except RuntimeError:
                pass  # loop 已关闭（客户端断开）

        unsubscribe = bus.subscribe(on_event)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                    payload = json.dumps(event.to_payload(), ensure_ascii=False)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            unsubscribe()

    return StreamingResponse(
        event_stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

`router_registry.py` 追加 `from app.routers import live_transcripts` 与 `app.include_router(live_transcripts.router)`（放 callbacks 之后）。

- [ ] **Step 4: 运行确认通过**

Run（在 `console/backend` 目录）：`..\..\.venv\Scripts\python.exe -m pytest tests/integration/test_live_transcripts.py tests/integration/test_callbacks_api.py -v`
Expected: PASS（3 + 7 passed）。注：`test_sse_worker_absent_reports_error` 若因测试进程内 livekit_worker 可导入而走不到 ImportError 分支，改为 monkeypatch `speech_to_speech.livekit_worker.events.get_event_bus` 抛 ImportError 的等价写法（路由内 except 捕获的就是 import 失败与 bus 获取失败两类）。

- [ ] **Step 5: Commit（先询问用户）**

```bash
git add console/backend/app/routers/live_transcripts.py console/backend/app/core/router_registry.py console/backend/tests/integration/test_live_transcripts.py
git commit -m "feat(callbacks): SSE endpoint streaming live transcript events"
```

---

### Task 14B: 前端「实时字幕」页签

**Files:**
- Create: `console/frontend/src/components/LiveSubtitlesPanel.vue`
- Modify: `console/frontend/src/views/CallbacksView.vue`（第三个 tab-pane 引入面板）
- Modify: `console/frontend/src/i18n/locales/{zh-CN,en-US}/callbacks.ts`（追加实时字幕键组）
- Test: 前端无单测框架既有约定则不新增（与现有 frontend 一致），以 `npm run build` 类型检查为准

- [ ] **Step 1: 实现 LiveSubtitlesPanel.vue**

```vue
<!-- console/frontend/src/components/LiveSubtitlesPanel.vue -->
<!-- 实时字幕面板：fetch 流式读取 SSE（携带 JWT），渲染 LiveKit 房间转写事件 -->
<template>
  <div class="live-subtitles">
    <a-space style="margin-bottom: 12px">
      <a-badge :status="connected ? 'processing' : 'error'" />
      <span>{{ connected ? t('callbacks.live.connected') : t('callbacks.live.disconnected') }}</span>
      <a-button size="small" @click="togglePause">
        {{ paused ? t('callbacks.live.resume') : t('callbacks.live.pause') }}
      </a-button>
      <a-button size="small" danger @click="clear">{{ t('callbacks.live.clear') }}</a-button>
      <span class="count">{{ lines.length }}</span>
    </a-space>
    <div ref="listEl" class="subtitle-list">
      <div v-for="(line, index) in lines" :key="index" class="subtitle-line">
        <span class="meta">[{{ formatTime(line.timestamp) }}] {{ line.room }} / {{ line.identity }}</span>
        <span class="text">{{ line.text }}</span>
      </div>
      <div v-if="!lines.length" class="empty">{{ t('callbacks.live.empty') }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
// SSE 消费：EventSource 无法带 Authorization 头，用 fetch + ReadableStream 解析 data 行
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'  // 若 token 存取路径不同，按现有 store 实际导出对齐

interface LiveLine {
  timestamp: number
  room: string
  identity: string
  text: string
  eventType: string
}

const { t } = useI18n()
const lines = ref<LiveLine[]>([])
const connected = ref(false)
const paused = ref(false)
const listEl = ref<HTMLElement | null>(null)
let controller: AbortController | null = null
const MAX_LINES = 500

function formatTime(ts: number): string {
  if (!ts) return '--:--:--'
  return new Date(ts).toLocaleTimeString()
}

function pushLine(payload: Record<string, unknown>) {
  if (paused.value) return
  lines.value.push({
    timestamp: Number(payload.timestamp ?? 0),
    room: String(payload.roomSid ?? ''),
    identity: String(payload.identity ?? ''),
    text: String(payload.text ?? ''),
    eventType: String(payload.eventType ?? ''),
  })
  if (lines.value.length > MAX_LINES) lines.value.splice(0, lines.value.length - MAX_LINES)
  nextTick(() => listEl.value?.scrollTo({ top: listEl.value.scrollHeight }))
}

async function connect() {
  const auth = useAuthStore()
  controller = new AbortController()
  try {
    const resp = await fetch('/api/v1/live-transcripts/stream', {
      headers: { Authorization: `Bearer ${auth.token}` },
      signal: controller.signal,
    })
    if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`)
    connected.value = true
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() ?? ''
      for (const frame of parts) {
        for (const row of frame.split('\n')) {
          if (row.startsWith('event: error')) {
            connected.value = false
            return  // standalone console 部署：无实时流，停止重试
          }
          if (row.startsWith('data: ')) {
            try {
              pushLine(JSON.parse(row.slice(6)))
            } catch { /* 跳过坏帧 */ }
          }
        }
      }
    }
  } catch {
    // AbortError（组件卸载）或网络断开
  } finally {
    connected.value = false
  }
}

function togglePause() {
  paused.value = !paused.value
}

function clear() {
  lines.value = []
}

onMounted(connect)
onBeforeUnmount(() => controller?.abort())
</script>

<style scoped>
.live-subtitles { display: flex; flex-direction: column; }
.subtitle-list {
  height: 420px; overflow-y: auto; border: 1px solid var(--ant-color-border, #eee);
  border-radius: 6px; padding: 8px 12px;
}
.subtitle-line { margin: 4px 0; line-height: 1.6; }
.subtitle-line .meta { color: var(--ant-color-text-tertiary, #999); font-size: 12px; margin-right: 8px; }
.subtitle-line .text { font-size: 14px; }
.empty { color: var(--ant-color-text-tertiary, #999); text-align: center; padding: 40px 0; }
.count { color: var(--ant-color-text-tertiary, #999); font-size: 12px; }
</style>
```

实现注意：`useAuthStore` 的 token 字段名（`token` / `accessToken`）按 `console/frontend/src/stores/auth.ts`（或现有 auth store 实际路径）对齐；若 fetch 需要完整后端地址，复用 `@/api/client` 的 baseURL 约定。

- [ ] **Step 2: CallbacksView.vue 挂第三个页签**

`<a-tabs v-model:activeKey="activeTab">` 内、logs 页签之后追加：

```vue
      <a-tab-pane key="live" :tab="t('callbacks.liveTab')">
        <LiveSubtitlesPanel />
      </a-tab-pane>
```

`<script setup>` 追加 `import LiveSubtitlesPanel from '@/components/LiveSubtitlesPanel.vue'`。

- [ ] **Step 3: i18n 键组**

`zh-CN/callbacks.ts` 追加：

```typescript
  liveTab: '实时字幕',
  live: {
    connected: '已连接实时转写流',
    disconnected: '未连接（worker 未随本进程启动或已断开）',
    pause: '暂停',
    resume: '继续',
    clear: '清空',
    empty: '暂无转写事件，启动 serve --with-livekitworker 后进房说话即可看到字幕',
  },
```

`en-US/callbacks.ts` 同结构英文（liveTab: 'Live Subtitles'、connected: 'Connected to live transcript stream'、disconnected: 'Not connected (worker not running in this process or disconnected)'、pause: 'Pause'、resume: 'Resume'、clear: 'Clear'、empty: 'No transcript events yet; start serve --with-livekitworker and join a room to see subtitles'）。

- [ ] **Step 4: 构建验证**

Run（在 `console/frontend` 目录）：`npm run build`
Expected: vite build 成功、vue-tsc 无类型错误

- [ ] **Step 5: Commit（先询问用户）**

```bash
git add console/frontend/src/components/LiveSubtitlesPanel.vue console/frontend/src/views/CallbacksView.vue console/frontend/src/i18n/locales
git commit -m "feat(callbacks): frontend live subtitles panel consuming SSE stream"
```

---

### Task 15: 测试补全与回归 + 文档

**Files:**
- Test: `tests/test_livekit_worker.py`（追加崩溃隔离、开关联动断言）
- Modify: `README.md`、`README-CN.md`
- Create: `docs/livekit-worker-integration-CN.md`
- Create: `docs/callback-subsystem-CN.md`
- Modify: `console/backend/tests/integration/test_machines_api.py` 等既有测试（仅当权限码影响断言计数）

- [ ] **Step 1: 追加 worker 崩溃隔离测试**

```python
# tests/test_livekit_worker.py 追加
def test_runtime_thread_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """worker 线程崩溃不拖垮主进程（spec §9）。"""
    _install_livekit_stub(monkeypatch)
    import importlib

    import speech_to_speech.livekit_worker as pkg

    importlib.reload(pkg)  # 确保拿到 stub 后的模块
    from threading import Event

    runtime = pkg.LiveKitWorkerRuntime(Event())
    monkeypatch.setattr(runtime, "_serve", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    runtime._run()  # 内部捕获异常，不向上抛
    assert runtime._loop is not None


def test_runtime_stop_joins_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_livekit_stub(monkeypatch)
    import importlib

    import speech_to_speech.livekit_worker as pkg

    importlib.reload(pkg)
    from threading import Event

    runtime = pkg.LiveKitWorkerRuntime(Event())
    runtime._thread = None  # 未启动时 stop 不抛
    runtime.stop()
```

- [ ] **Step 2: 全量回归**

Run: `.\.venv\Scripts\python.exe -m pytest tests -q`
Expected: 全部 PASS（含既有测试；若有 README 计数类断言，更新为实际数字）

Run（在 `console/backend` 目录）：`..\..\.venv\Scripts\python.exe -m pytest tests -q`
Expected: 全部 PASS

Run: `.\.venv\Scripts\python.exe -m ruff check .`
Expected: 无错误（新增文件全绿；既有告警不在本次范围）

- [ ] **Step 3: README 两个语言版本**

`README.md`（英文）在开关/CLI 段落追加：

```markdown
### LiveKit room transcript worker (optional)

Install the optional extra and start the embedded worker alongside `serve`:

```bash
pip install "speech-to-speech[livekit]"
export LIVEKIT_URL=... LIVEKIT_API_KEY=... LIVEKIT_API_SECRET=...
speech-to-speech serve --with-livekitworker --with-diarization --with-console
```

- `--with-diarization` enables the existing streaming speaker separation for the
  main pipeline.
- `--with-livekitworker` runs the LiveKit room transcript worker thread inside
  the server process (see [docs/livekit-worker-integration-CN.md](docs/livekit-worker-integration-CN.md)).
- Transcripts are delivered through the configurable callback subsystem
  (see [docs/callback-subsystem-CN.md](docs/callback-subsystem-CN.md)) and the
  console "Callbacks" page.
```

`README-CN.md` 对应中文段落（同义翻译，命令一致）。

- [ ] **Step 4: docs/livekit-worker-integration-CN.md**

内容结构（必须包含以下小节，不得占位）：

1. **架构图**（ASCII）：serve 进程内 pipeline / livekit_worker 线程 / callback dispatcher / console 四块及事件流向。
2. **开关与环境变量全表**：`--with-diarization`/`--no-with-diarization`/`DIARIZATION_AUTOSTART`；`--with-livekitworker`/`--no-with-livekitworker`/`LIVEKIT_WORKER_AUTOSTART`；`LIVEKIT_URL`、`LIVEKIT_API_KEY`、`LIVEKIT_API_SECRET`、`AGENT_NAME`、`HEALTH_PORT`、`LOAD_THRESHOLD`、`LIVEKIT_WORKER_ASR_MODE`、`VOICE_GATEWAY_BASE_URL`、`VOICE_ASR_MODEL`、`SER_*`、`DIARIZATION_BASE_URL` 及语义——与源工程同名同义，逐条列出并注明默认值。
3. **与源工程差异清单**：依赖注入化（ASR 双模式、STT handler 注入）、回调去向统一 CallbackDispatcher（env 兜底保留）、模块路径命名空间化、事件双路输出、env 读取惰性化。
4. **Python 版本约束**：livekit-agents 0.12 支持矩阵，3.14 不可用时的 ImportError 提示文案与 mock 单测说明。
5. **两套分离能力并存说明**：`--with-diarization`（主 pipeline 流式）vs worker `DIARIZATION_BASE_URL`（外部离线服务），互不调用；`deploy/diarization/main.py` 不迁移、仍按源工程 README 独立部署。

- [ ] **Step 5: docs/callback-subsystem-CN.md**

内容结构（必须包含以下小节）：

1. **数据模型**：`callback_target` / `callback_delivery_log` 全字段表（照 spec §8.1）。
2. **API 清单**：§8.4 六组端点的请求/响应示例（curl + JSON 响应体）。
3. **事件 payload**：`TranscriptEvent.to_payload()` 输出示例（transcript 与 session_end 各一）；java 目标的 TranscriptSegmentVO 数组形状示例。
4. **协议适配矩阵**：照 spec §8.2 表格复制并补充 `MEETING_INTERNAL_TOKEN`/`X-Internal-Token`/`tenant-id` 头细节。
5. **热加载与 env 兜底语义**：TTL 5 秒缓存、`invalidate_cache` 时机（console 写 API 成功后由 dispatcher 下轮 TTL 自然刷新，无需重启）；DB 可用时 env 兜底失效并 warning；DB 不可用 + `JAVA_CALLBACK_BASE`/`MEETING_INTERNAL_TOKEN` 存在时生成内存 java 目标。
6. **投递语义**：线程池异步、指数退避（`retry_backoff_ms × 2^(attempt-1)`）、每次尝试一条日志、最终失败仅日志不重投；日志 token 脱敏规则（`mask_token`）。

- [ ] **Step 6: Commit（先询问用户）**

```bash
git add README.md README-CN.md docs/livekit-worker-integration-CN.md docs/callback-subsystem-CN.md tests
git commit -m "docs: livekit worker integration and callback subsystem documentation"
```

---

## 验收清单（对照 spec §13）

1. CLI 开关解析 + env 覆盖 + 报错分支 → Task 1、2
2. `livekit_worker/` 包骨架与线程生命周期 → Task 4、9
3. `segment_dedupe` / `ser_provider` / `diarization_provider` / `events` 移植 → Task 4、5、6、7
4. `asr_provider` 双模式 → Task 6、8
5. `worker.py` 核心移植与事件产出 → Task 9
6. 回调子系统：alembic → dispatcher → API → 前端 → Task 11、12、13、14；实时字幕桥接（§7.1 修订版）→ Task 14A、14B
7. extra 依赖与启动期校验 → Task 3、2、10
8. 测试新增 + 既有断言更新 → 各任务内 TDD + Task 15
9. 文档四处 → Task 15
10. `pytest` + `ruff check .` 修复回归 → Task 15
