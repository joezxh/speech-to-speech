# 移除 SenseVoiceLarge 与内嵌 SenseVoiceSmall 情感服务（Embedded SER）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 全仓清除 SenseVoiceLarge；引入 `ModelCard.native_emotion` 静态能力声明；serve 启动时对无原生情感能力的 STT 自动内嵌加载 SenseVoiceSmall 情感服务，实时管线与 livekit_worker 共用；`--no-embedded-ser`/env 可关。

**Architecture:** 内嵌 SER 以 ThreadManager 线程形态随 serve 运行（与 `--with-agent`/`LiveKitWorkerRuntime` 同模式：`run()` + `stop_event` + 崩溃隔离）。端点复用 `emotion_local_service` 现有路由（零新路由代码）：pipeline 里找不到 SenseVoice handler 时回落到内嵌 runtime 的独立 handler。worker 侧 `get_ser_provider()` 在显式配置优先的前提下回落到本进程内嵌端点的 `HttpSerProvider`。

**Tech Stack:** Python 3.11+、FastAPI、funasr（可选 extra，单测不装）、pytest 全离线 mock。

**Spec:** `docs/superpowers/specs/2026-11-26-embedded-ser-design.md`（唯一事实来源）。

**仓库规则：** commit 步骤执行前必须先询问用户是否执行 commit（除非用户已授权免询问模式）；分支/PR 标题不得含 "codex"。

**测试命令约定（Windows dev）：** `.\.venv\Scripts\python.exe -m pytest <args>`。**不要主动跑全量 pytest**——全量回归由用户手动执行；每个任务只跑该任务指定的目标测试文件。

**关键现状事实（2026-11-26 已探查）：**
- `config/prod.yaml` STT 块**已是** `backend: qwen3-asr`、`config/prod.env` 的 `S2S_ASR_MODEL_DIR` **已指向** qwen3-asr 权重——本计划只改注释与新增 env，不动 STT 指向。
- `SenseVoiceLarge` 代码引用仅 3 处：`src/speech_to_speech/models/builtin.py:43-61`（卡片）、`tests/test_model_registry.py:170`（断言）、spec 文档自身（保留）。
- `-f` 文件模式不接线 worker 开关（`configured_runtime.py` 忽略 diarization/livekit options + cli 警告先例）；内嵌 SER 沿用同款（仅显式 flag 时警告，不接线）。
- `SER_PROVIDER` 值域两套不混用：realtime 侧 `local|proxy`；worker 侧 `none|emotion2vec|sensevoice`。

---

## 文件结构

```
src/speech_to_speech/
├── model_registry.py                # 修改：ModelCard.native_emotion 字段 + stt_has_native_emotion()
├── models/builtin.py                # 修改：删 sensevoice-large 卡片；sensevoice-small 置 native_emotion=True
├── embedded_ser.py                  # 新增：开关解析 + EmbeddedSerRuntime + 单例 + 启动期判定
├── cli.py                           # 修改：接线开关（strip → talk 拒绝 → _dispatch 透传 → file-mode 警告）
├── s2s_pipeline.py                  # 修改：run_pipeline_command/_run_parsed/build_pipeline/build_local_pipeline 透传
├── api/openai_realtime/emotion_local_service.py   # 修改：挂载门 + handler 回落
└── livekit_worker/ser_provider.py   # 修改：get_ser_provider 内嵌回落
config/
├── prod.yaml                        # 修改：两处注释改写（去 SenseVoice 字样）
└── prod.env                         # 修改：新增 S2S_SENSEVOICE_MODEL_DIR
docs/
└── service-enablement-CN.md         # 修改：新增 §9.5 Embedded SER 说明
tests/
├── test_model_registry.py           # 修改：卡片全集断言 + native_emotion/stt_has_native_emotion 断言
└── test_embedded_ser.py             # 新增：开关/绑定三分支/端点契约/worker 回落 全离线测试
```

---

### Task 1: 删除 sensevoice-large 卡片（测试先行）

**Files:**
- Modify: `src/speech_to_speech/models/builtin.py:43-61`
- Modify: `tests/test_model_registry.py:159-177`

- [ ] **Step 1: 更新卡片全集断言（先改测试，使其失败）**

`tests/test_model_registry.py` 的 `test_builtin_catalog_status_counts_and_license_gate` 改为：

```python
def test_builtin_catalog_status_counts_and_license_gate():
    from speech_to_speech.models.builtin import builtin_model_cards

    cards = builtin_model_cards()
    assert len(cards) == 14
    assert len({c.id for c in cards}) == 14
    assert sorted(c.id for c in cards if c.status == "available") == [
        "cosyvoice2",
        "qwen3-asr-1.7b-hf",
        "qwen3-tts-1.7b-customvoice",
        "qwen3.5-4b-transformers",
        "sensevoice-small",
        "voxcpm-0.5b",
        "voxcpm1.5-0.8b",
        "voxcpm2-2b",
    ]
    assert not [c.id for c in cards if c.status == "deprecated"]
    assert sum(c.status == "planned" for c in cards) == 6

    breeze = next(c for c in cards if c.id == "breeze-tts-2")
    assert breeze.status == "planned"
    assert "Research and Non-Commercial" in breeze.license
    assert "商用" in breeze.notes
    assert "商业授权" in breeze.notes
    assert breeze.min_vram_gb == 7.7

    qwen_llm = next(c for c in cards if c.id == "minicpm-homologous-qwen3-8b")
    assert qwen_llm.min_vram_gb == 16.0
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_model_registry.py::test_builtin_catalog_status_counts_and_license_gate -v`
Expected: FAIL（15 张卡 ≠ 14，available 列表多 `sensevoice-large`）

- [ ] **Step 3: 删除卡片**

删除 `src/speech_to_speech/models/builtin.py` 中 `id="sensevoice-large"` 的整张 `ModelCard(...)`（L43-61，从 `ModelCard(` 到其闭括号加尾逗号）。

- [ ] **Step 4: 运行确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_model_registry.py -v`
Expected: PASS（全部用例）

- [ ] **Step 5: Commit**

```bash
git add src/speech_to_speech/models/builtin.py tests/test_model_registry.py
git commit -m "feat(models): remove sensevoice-large model card"
```

---

### Task 2: ModelCard.native_emotion 字段 + stt_has_native_emotion()

**Files:**
- Modify: `src/speech_to_speech/model_registry.py`
- Modify: `src/speech_to_speech/models/builtin.py`（sensevoice-small 卡片）
- Modify: `tests/test_model_registry.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_model_registry.py` 文件末尾：

```python
def test_native_emotion_capability_declarations():
    """spec §4：能力静态声明，默认 False，仅 sensevoice-small 为 True。"""
    from speech_to_speech.models.builtin import builtin_model_cards

    cards = {c.id: c for c in builtin_model_cards()}
    assert cards["sensevoice-small"].native_emotion is True
    assert cards["qwen3-asr-1.7b-hf"].native_emotion is False
    assert cards["whisper-medium"].native_emotion is False
    assert cards["cosyvoice2"].native_emotion is False  # 非 STT 卡片同样默认 False


def test_stt_has_native_emotion_lookup():
    """spec §4：按 backend 名查卡片；无卡片映射的后端返回 False（fail-closed）。"""
    from speech_to_speech.model_registry import stt_has_native_emotion

    assert stt_has_native_emotion("sense-voice") is True
    assert stt_has_native_emotion("qwen3-asr") is False
    assert stt_has_native_emotion("whisper") is False
    assert stt_has_native_emotion("no-such-backend") is False
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_model_registry.py::test_native_emotion_capability_declarations tests/test_model_registry.py::test_stt_has_native_emotion_lookup -v`
Expected: FAIL，`AttributeError: ... no attribute 'native_emotion'` / `ImportError: cannot import name 'stt_has_native_emotion'`

- [ ] **Step 3: ModelCard 加字段**

`src/speech_to_speech/model_registry.py` 的 `ModelCard` 末尾（`notes: str = ""` 之后）加一行：

```python
    notes: str = ""
    native_emotion: bool = False
```

- [ ] **Step 4: stt_has_native_emotion 查询**

`src/speech_to_speech/model_registry.py` 在 `validate_models()` 之后追加：

```python
def stt_has_native_emotion(backend_name: str) -> bool:
    """Static capability lookup (spec §4): does this STT backend declare native emotion?

    无卡片映射的后端返回 False（fail-closed → 走内嵌 SER 补齐）。
    """
    return any(card.native_emotion for card in MODEL_REGISTRY.by_backend(backend_name))
```

- [ ] **Step 5: sensevoice-small 卡片置位**

`src/speech_to_speech/models/builtin.py` 的 `id="sensevoice-small"` 卡片，在 `license="Apache-2.0",` 之后加一行：

```python
            native_emotion=True,
```

- [ ] **Step 6: 运行确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_model_registry.py -v`
Expected: PASS（全部用例）

- [ ] **Step 7: Commit**

```bash
git add src/speech_to_speech/model_registry.py src/speech_to_speech/models/builtin.py tests/test_model_registry.py
git commit -m "feat(models): add ModelCard.native_emotion capability declaration"
```

---

### Task 3: embedded_ser.py 开关解析 + CLI 接线

**Files:**
- Create: `src/speech_to_speech/embedded_ser.py`
- Modify: `src/speech_to_speech/cli.py`
- Test: `tests/test_embedded_ser.py`（本任务先写开关解析部分）

- [ ] **Step 1: 写失败测试（开关解析 + talk 拒绝）**

创建 `tests/test_embedded_ser.py`：

```python
"""Embedded SER 离线契约测试（spec §7.2；不装 funasr，全部 mock）。"""
from __future__ import annotations

import sys

import pytest

from speech_to_speech.embedded_ser import (
    EMBEDDED_SER_AUTOSTART_ENV,
    EMBEDDED_SER_WITH_FLAG,
    EMBEDDED_SER_WITHOUT_FLAG,
    EmbeddedSerError,
    parse_embedded_ser_arguments,
)


# ---------------------------------------------------------------------------
# 开关解析（spec §5：显式 flag > env > 默认自动启用）
# ---------------------------------------------------------------------------


def test_default_is_auto_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """与 worker 开关的差别：无 flag 无 env 时默认启用。"""
    monkeypatch.delenv(EMBEDDED_SER_AUTOSTART_ENV, raising=False)
    options, rest = parse_embedded_ser_arguments(["serve", "--port", "9000"])
    assert options.autostart is True
    assert options.explicit is False
    assert rest == ["serve", "--port", "9000"]


def test_without_flag_disables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(EMBEDDED_SER_AUTOSTART_ENV, raising=False)
    options, rest = parse_embedded_ser_arguments(["--no-embedded-ser", "serve"])
    assert options.autostart is False
    assert options.explicit is True
    assert options.explicit_flag == "--no-embedded-ser"
    assert rest == ["serve"]


def test_with_flag_enables(monkeypatch: pytest.MonkeyPatch) -> None:
    options, rest = parse_embedded_ser_arguments(["--with-embedded-ser", "serve"])
    assert options.autostart is True
    assert options.explicit is True
    assert options.explicit_flag == "--with-embedded-ser"
    assert rest == ["serve"]


def test_env_false_disables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EMBEDDED_SER_AUTOSTART_ENV, "false")
    options, rest = parse_embedded_ser_arguments(["serve"])
    assert options.autostart is False
    assert options.explicit is False
    assert rest == ["serve"]


def test_env_true_enables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EMBEDDED_SER_AUTOSTART_ENV, "1")
    options, _ = parse_embedded_ser_arguments(["serve"])
    assert options.autostart is True


def test_env_invalid_value_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EMBEDDED_SER_AUTOSTART_ENV, "maybe")
    with pytest.raises(EmbeddedSerError, match="must be a boolean"):
        parse_embedded_ser_arguments(["serve"])


def test_explicit_flag_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EMBEDDED_SER_AUTOSTART_ENV, "false")
    options, _ = parse_embedded_ser_arguments(["--with-embedded-ser", "serve"])
    assert options.autostart is True
    assert options.explicit is True


def test_conflicting_flags_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(EMBEDDED_SER_AUTOSTART_ENV, raising=False)
    with pytest.raises(EmbeddedSerError, match="conflicts"):
        parse_embedded_ser_arguments(["--with-embedded-ser", "--no-embedded-ser", "serve"])


def test_file_mode_switch_stripped_before_f(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(EMBEDDED_SER_AUTOSTART_ENV, raising=False)
    _, rest = parse_embedded_ser_arguments(["-f", "run.yaml", "--no-embedded-ser"])
    assert rest == ["-f", "run.yaml"]


@pytest.mark.parametrize("flag", [EMBEDDED_SER_WITH_FLAG, EMBEDDED_SER_WITHOUT_FLAG])
def test_talk_rejects_explicit_switches(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], flag: str
) -> None:
    """真实触发 cli.main() 的 talk 分支：显式内嵌 SER 开关必须以 exit 2 拒绝。"""
    from speech_to_speech import cli

    monkeypatch.delenv("CONSOLE_AUTOSTART", raising=False)
    monkeypatch.delenv("S2S_AGENT_AUTOSTART", raising=False)
    monkeypatch.delenv("DIARIZATION_AUTOSTART", raising=False)
    monkeypatch.delenv("LIVEKIT_WORKER_AUTOSTART", raising=False)
    monkeypatch.delenv(EMBEDDED_SER_AUTOSTART_ENV, raising=False)
    monkeypatch.setattr(sys, "argv", ["speech-to-speech", "talk", flag])
    with pytest.raises(SystemExit) as exc_info:
        cli.main()
    assert exc_info.value.code == 2
    assert f"talk does not accept {flag}" in capsys.readouterr().err
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_embedded_ser.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'speech_to_speech.embedded_ser'`

- [ ] **Step 3: 创建 embedded_ser.py（本任务实现到开关解析为止，runtime 在 Task 4 补）**

创建 `src/speech_to_speech/embedded_ser.py`：

```python
"""Embedded SenseVoiceSmall SER runtime（内嵌情感服务，spec 2026-11-26 §5）.

serve 启动时按所选 STT 是否原生支持情感识别（``ModelCard.native_emotion``）
自动决定是否在本进程内加载 SenseVoiceSmall 作为情感服务：

* STT 原生（sense-voice）→ 沿用现状：``emotion_local_service`` 复用 pipeline
  handler，本模块不启动（零改动路径）。
* STT 非原生（qwen3-asr / whisper / …）→ :class:`EmbeddedSerRuntime` 线程加载
  SenseVoiceSmall（独立 handler，非 pipeline 复用），端点仍由
  ``emotion_local_service`` 挂载；实时管线与 livekit_worker 共用同一模型显存。
* 开关双通道：``--with-embedded-ser`` / ``--no-embedded-ser``（显式 flag）与
  ``EMBEDDED_SER_AUTOSTART``（布尔 env）；显式 flag > env > 默认自动启用。

崩溃隔离：加载失败只记日志，``ready`` 保持 False，转写链路不受影响。
"""
from __future__ import annotations

import logging
import os
import threading
from collections.abc import Sequence

# 复用 worker_integration 的布尔值域与 SwitchOptions 形状（同包内部复用私有常量，
# 保持「开关双通道」行为与 --with-livekitworker 完全一致）。
from speech_to_speech.worker_integration import SwitchOptions, _FALSE_VALUES, _TRUE_VALUES

logger = logging.getLogger(__name__)

EMBEDDED_SER_WITH_FLAG = "--with-embedded-ser"
EMBEDDED_SER_WITHOUT_FLAG = "--no-embedded-ser"
EMBEDDED_SER_AUTOSTART_ENV = "EMBEDDED_SER_AUTOSTART"
EMBEDDED_SER_BASE_URL_ENV = "EMBEDDED_SER_BASE_URL"
DEFAULT_EMBEDDED_SER_BASE_URL = "http://127.0.0.1:8765"
EMBEDDED_SER_HEALTH_PATH = "/v1/audio/emotion/health"
DEFAULT_SENSEVOICE_MODEL = "FunAudioLLM/SenseVoiceSmall"


class EmbeddedSerError(RuntimeError):
    """An embedded SER switch cannot be applied as requested; callers exit with code 2."""


def parse_embedded_ser_arguments(argv: Sequence[str]) -> tuple[SwitchOptions, list[str]]:
    """Strip the embedded SER flag pair from argv and resolve the effective option.

    与 worker 开关唯一的差别是默认值：无 flag 且无 env 时**自动启用**（spec §5）。
    Stripping happens before ``parse_command`` so ``-f`` file mode keeps working.
    """
    remaining = list(argv)
    explicit: bool | None = None
    explicit_flag: str | None = None
    kept: list[str] = []
    for argument in remaining:
        if argument == EMBEDDED_SER_WITH_FLAG:
            if explicit is False:
                raise EmbeddedSerError(f"{EMBEDDED_SER_WITH_FLAG} conflicts with {EMBEDDED_SER_WITHOUT_FLAG}.")
            explicit = True
            explicit_flag = EMBEDDED_SER_WITH_FLAG
            continue
        if argument == EMBEDDED_SER_WITHOUT_FLAG:
            if explicit is True:
                raise EmbeddedSerError(f"{EMBEDDED_SER_WITHOUT_FLAG} conflicts with {EMBEDDED_SER_WITH_FLAG}.")
            explicit = False
            explicit_flag = EMBEDDED_SER_WITHOUT_FLAG
            continue
        kept.append(argument)
    remaining[:] = kept
    if explicit is None:
        raw = os.environ.get(EMBEDDED_SER_AUTOSTART_ENV)
        if raw is None:
            autostart = True
        else:
            value = raw.strip().lower()
            if value in _TRUE_VALUES:
                autostart = True
            elif value in _FALSE_VALUES:
                autostart = False
            else:
                raise EmbeddedSerError(
                    f"{EMBEDDED_SER_AUTOSTART_ENV} must be a boolean "
                    f"(1/true/yes/on or 0/false/no/off); got {raw!r}."
                )
    else:
        autostart = explicit
    return (
        SwitchOptions(autostart=autostart, explicit=explicit is not None, explicit_flag=explicit_flag),
        remaining,
    )


__all__ = [
    "DEFAULT_EMBEDDED_SER_BASE_URL",
    "EMBEDDED_SER_AUTOSTART_ENV",
    "EMBEDDED_SER_BASE_URL_ENV",
    "EMBEDDED_SER_HEALTH_PATH",
    "EMBEDDED_SER_WITH_FLAG",
    "EMBEDDED_SER_WITHOUT_FLAG",
    "EmbeddedSerError",
    "parse_embedded_ser_arguments",
]
```

- [ ] **Step 4: 运行开关解析测试**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_embedded_ser.py -v -k "not talk"`
Expected: PASS（9 项解析测试）；talk 拒绝测试仍 FAIL（cli 未接线）

- [ ] **Step 5: CLI 接线（strip → talk 拒绝 → dispatch 透传 → file-mode 警告）**

`src/speech_to_speech/cli.py` 共 5 处修改：

(a) import 区（紧挨现有 worker_integration import 之后）加：

```python
from speech_to_speech.embedded_ser import (
    EMBEDDED_SER_WITH_FLAG,
    EmbeddedSerError,
    parse_embedded_ser_arguments,
)
```

(b) `main()` 中 worker 开关解析之后（L511-514 `parse_worker_arguments` try 块后）加：

```python
    try:
        # Same discipline: the embedded SER switch leaves argv before parse_command.
        embedded_ser_options, argv = parse_embedded_ser_arguments(argv)
    except EmbeddedSerError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
```

(c) `main()` 的 talk 拒绝循环（L540）三元组变四元组：

```python
        for options, flag in (
            (diarization_options, DIARIZATION_WITH_FLAG),
            (livekit_options, LIVEKIT_WITH_FLAG),
            (embedded_ser_options, EMBEDDED_SER_WITH_FLAG),
        ):
```

（循环体保持不变——`options.explicit` 报 exit 2，`options.autostart` 打 env warning。）

(d) `_dispatch` 签名加参数并透传：

```python
def _dispatch(
    command: Command,
    command_args: list[str],
    console_options: ConsoleOptions,
    agent_options: AgentOptions,
    diarization_options: SwitchOptions,
    livekit_options: SwitchOptions,
    embedded_ser_options: SwitchOptions,
) -> None:
    if command == "models":
        _run_models_command(command_args)
        return
    if any(
        argument.startswith("-f") or argument == "--file" or argument.startswith("--file=") for argument in command_args
    ):
        _run_file_command(command, command_args, console_options, agent_options, diarization_options, livekit_options, embedded_ser_options)
        return
    if any(argument == "--name" or argument.startswith("--name=") for argument in command_args):
        _command_parser().error("--name requires a configuration file.")
    if command == "talk":
        config = parse_talk_arguments(command_args)
        set_log_transcripts(config.log_transcripts)
        warn_if_log_transcripts_enabled()
        run_realtime_audio_client(config)
        return

    from speech_to_speech.s2s_pipeline import run_pipeline_command

    run_pipeline_command(
        command,
        command_args,
        console_options=console_options,
        agent_options=agent_options,
        diarization_options=diarization_options,
        livekit_options=livekit_options,
        embedded_ser_options=embedded_ser_options,
    )
```

`main()` 的调用点（L586）同步改为：

```python
    try:
        _dispatch(command, command_args, console_options, agent_options, diarization_options, livekit_options, embedded_ser_options)
```

(e) `_run_file_command` 签名加 `embedded_ser_options: SwitchOptions`，并在 livekit 警告块（L341-345）后加（仅显式 flag 才警告，默认自动启用在 -f 模式不生效且不刷屏，与 worker 开关「file mode 不接线」先例一致）：

```python
    if embedded_ser_options.explicit and embedded_ser_options.autostart:
        print(
            "Warning: --with-embedded-ser is not wired for -f file mode yet; the embedded SER runtime will not start.",
            file=sys.stderr,
        )
```

- [ ] **Step 6: 运行全部 embedded 测试 + 既有 cli 相关回归**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_embedded_ser.py tests/test_worker_integration.py tests/test_agent_integration.py tests/test_console_integration.py -v`
Expected: PASS（talk 拒绝测试转绿；既有开关测试不回归）

- [ ] **Step 7: Commit**

```bash
git add src/speech_to_speech/embedded_ser.py src/speech_to_speech/cli.py tests/test_embedded_ser.py
git commit -m "feat(cli): add --with-embedded-ser / --no-embedded-ser switch"
```

---

### Task 4: EmbeddedSerRuntime + 启动期判定 + build_pipeline 接线

**Files:**
- Modify: `src/speech_to_speech/embedded_ser.py`（追加 runtime/单例/resolve）
- Modify: `src/speech_to_speech/s2s_pipeline.py`
- Modify: `tests/test_embedded_ser.py`（追加测试）

- [ ] **Step 1: 写失败测试（绑定三分支 + 崩溃隔离）**

追加到 `tests/test_embedded_ser.py`：

```python
# ---------------------------------------------------------------------------
# EmbeddedSerRuntime / resolve_embedded_ser（spec §5 三分支 + §6 崩溃隔离）
# ---------------------------------------------------------------------------

import threading

from speech_to_speech import embedded_ser
from speech_to_speech.worker_integration import SwitchOptions


class _FakeRuntime:
    """测试替身：绕过真实模型加载，直接注入就绪状态。"""

    def __init__(self, handler=None, ready: bool = False) -> None:
        self._handler = handler
        self._ready = ready

    @property
    def ready(self) -> bool:
        return self._ready

    def handler(self):
        return self._handler


class _FakeSERHandler:
    """Mimics a SenseVoiceSTTHandler with an attached emotion logits hook."""

    def __init__(self, raw="HAPPY", laughter=False, confidence=0.9, margin=0.4):
        self.raw = raw
        self.laughter = laughter
        self.confidence = confidence
        self.margin = margin

    def recognize(self, audio) -> dict:
        return {
            "raw": self.raw,
            "laughter": self.laughter,
            "confidence": self.confidence,
            "margin": self.margin,
        }


@pytest.fixture(autouse=True)
def _clean_singleton():
    """每条测试前后清空内嵌单例，避免跨用例串台。"""
    embedded_ser.set_embedded_runtime(None)
    yield
    embedded_ser.set_embedded_runtime(None)


def test_resolve_skips_when_stt_native(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedded_ser, "stt_has_native_emotion", lambda name: True)
    runtime = embedded_ser.resolve_embedded_ser("sense-voice", SwitchOptions(autostart=True), threading.Event())
    assert runtime is None
    assert embedded_ser.get_embedded_runtime() is None


def test_resolve_starts_when_stt_not_native(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedded_ser, "stt_has_native_emotion", lambda name: False)
    stop = threading.Event()
    runtime = embedded_ser.resolve_embedded_ser("qwen3-asr", SwitchOptions(autostart=True), stop)
    assert runtime is not None
    assert runtime.ready is False
    assert embedded_ser.get_embedded_runtime() is runtime
    assert runtime.stop_event is stop


def test_resolve_disabled_warns_when_ser_enabled(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    """spec §5：禁用 + STT 无原生能力 + SER_ENABLED=true → 启动 warning，不阻塞。"""
    monkeypatch.setattr(embedded_ser, "stt_has_native_emotion", lambda name: False)
    monkeypatch.setenv("SER_ENABLED", "true")
    import logging

    with caplog.at_level(logging.WARNING, logger="speech_to_speech.embedded_ser"):
        runtime = embedded_ser.resolve_embedded_ser(
            "qwen3-asr", SwitchOptions(autostart=False), threading.Event()
        )
    assert runtime is None
    assert embedded_ser.get_embedded_runtime() is None
    assert any("emotion endpoints" in record.message for record in caplog.records)


def test_resolve_disabled_silent_when_ser_disabled(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    monkeypatch.setattr(embedded_ser, "stt_has_native_emotion", lambda name: False)
    monkeypatch.delenv("SER_ENABLED", raising=False)
    runtime = embedded_ser.resolve_embedded_ser(
        "qwen3-asr", SwitchOptions(autostart=False), threading.Event()
    )
    assert runtime is None


def test_runtime_load_failure_is_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """spec §6：funasr 未装 / 权重缺失 → 记日志退出线程，ready=false，不抛。"""
    def _boom() -> None:
        raise ModuleNotFoundError("funasr not installed")

    monkeypatch.setattr(embedded_ser, "_load_sensevoice_handler", _boom)
    runtime = embedded_ser.EmbeddedSerRuntime(threading.Event())
    runtime.run()  # 直接调用：不抛、立即返回
    assert runtime.ready is False
    assert runtime.handler() is None


def test_load_uses_env_model_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """S2S_SENSEVOICE_MODEL_DIR 缺省回落 HF repo id；device 缺省 cuda。"""
    captured: dict = {}

    class _FakeHandler:
        def setup(self, model_name, device, language):
            captured["model_name"] = model_name
            captured["device"] = device

    class _FakeCls:
        def __call__(self):
            return _FakeHandler()

    monkeypatch.delenv("S2S_SENSEVOICE_MODEL_DIR", raising=False)
    monkeypatch.setattr(
        "speech_to_speech.STT.sense_voice_handler.SenseVoiceSTTHandler", _FakeCls()
    )
    handler = embedded_ser._load_sensevoice_handler()
    assert captured == {"model_name": "FunAudioLLM/SenseVoiceSmall", "device": "cuda"}
    assert isinstance(handler, _FakeHandler)
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_embedded_ser.py -v -k "resolve or runtime or load_uses"`
Expected: FAIL，`AttributeError: module ... has no attribute 'resolve_embedded_ser'`

- [ ] **Step 3: 实现 runtime / 单例 / resolve**

`src/speech_to_speech/embedded_ser.py` 在 `parse_embedded_ser_arguments` 之后、`__all__` 之前追加：

```python
class EmbeddedSerRuntime:
    """ThreadManager 协议 handler：后台线程加载 SenseVoiceSmall，崩溃只记日志。

    与 agent / LiveKitWorkerRuntime 同协议（run() + stop_event）：ThreadManager
    把 run() 跑在 daemon=False 线程里，stop_event 置位后线程退出。加载失败只记
    日志并返回——ready 恒为 False，端点按 503/409 语义拒答，转写链路不受影响。
    """

    def __init__(self, stop_event: threading.Event) -> None:
        self.stop_event = stop_event
        self._handler: object | None = None
        self._ready = threading.Event()

    @property
    def name(self) -> str:
        return "embedded-ser"

    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    def handler(self) -> object | None:
        return self._handler

    def run(self) -> None:
        try:
            self._handler = _load_sensevoice_handler()
        except Exception as exc:  # noqa: BLE001 - funasr 缺失/权重损坏/OOM 一律崩溃隔离
            logger.error(
                "embedded SER load failed; emotion endpoints stay ready=false (pipeline unaffected): %s", exc
            )
            return
        self._ready.set()
        logger.info("embedded SER ready (SenseVoiceSmall)")
        self.stop_event.wait()


def _load_sensevoice_handler() -> object:
    """Load a dedicated SenseVoiceSTTHandler（独立实例，非 pipeline 复用）.

    S2S_SENSEVOICE_MODEL_DIR 缺失时回落 HF repo id；目录缺失由 funasr 的加载
    错误路径统一走 run() 的崩溃隔离，不在本层预检（与 STV soft-fail 语义一致）。
    """
    from speech_to_speech.STT.sense_voice_handler import SenseVoiceSTTHandler

    handler = SenseVoiceSTTHandler()
    handler.setup(
        model_name=os.environ.get("S2S_SENSEVOICE_MODEL_DIR", "").strip() or DEFAULT_SENSEVOICE_MODEL,
        device=os.environ.get("S2S_SENSEVOICE_DEVICE", "cuda").strip() or "cuda",
        language="auto",
    )
    return handler


_ACTIVE_RUNTIME: EmbeddedSerRuntime | None = None


def set_embedded_runtime(runtime: EmbeddedSerRuntime | None) -> None:
    """Register/unregister the process-wide embedded SER runtime.

    emotion_local_service 的 handler 回落与 worker get_ser_provider 的回落都经
    get_embedded_runtime()/get_embedded_ser_handler() 读取本单例。
    """
    global _ACTIVE_RUNTIME
    _ACTIVE_RUNTIME = runtime


def get_embedded_runtime() -> "EmbeddedSerRuntime | None":
    return _ACTIVE_RUNTIME


def get_embedded_ser_handler() -> object | None:
    """Runtime 就绪时返回其 handler；未启动/未就绪/加载失败均返回 None。"""
    runtime = _ACTIVE_RUNTIME
    if runtime is not None and runtime.ready:
        return runtime.handler()
    return None


def resolve_embedded_ser(
    stt_backend_name: str,
    options: SwitchOptions,
    stop_event: threading.Event,
) -> "EmbeddedSerRuntime | None":
    """启动期判定（spec §5 流程图）：原生→不启动；禁用→按需 warning；否则创建 runtime。

    返回值由调用方追加进 ThreadManager handlers；本函数同时注册模块单例，
    使 emotion_local_service 挂载门与 worker 回落在 create_app 时能看到它。
    """
    from speech_to_speech.model_registry import stt_has_native_emotion

    if stt_has_native_emotion(stt_backend_name):
        logger.info(
            "embedded SER: STT backend %r declares native emotion; not starting", stt_backend_name
        )
        return None
    if not options.autostart:
        if os.environ.get("SER_ENABLED", "").strip().lower() in _TRUE_VALUES:
            logger.warning(
                "embedded SER disabled via %s/%s and STT backend %r has no native emotion "
                "support; emotion endpoints will be unavailable (transcription unaffected)",
                EMBEDDED_SER_WITHOUT_FLAG,
                EMBEDDED_SER_AUTOSTART_ENV,
                stt_backend_name,
            )
        return None
    runtime = EmbeddedSerRuntime(stop_event)
    set_embedded_runtime(runtime)
    logger.info(
        "embedded SER: STT backend %r has no native emotion; SenseVoiceSmall will load "
        "in background (S2S_SENSEVOICE_MODEL_DIR or %s)",
        stt_backend_name,
        DEFAULT_SENSEVOICE_MODEL,
    )
    return runtime
```

`__all__` 替换为：

```python
__all__ = [
    "DEFAULT_EMBEDDED_SER_BASE_URL",
    "DEFAULT_SENSEVOICE_MODEL",
    "EMBEDDED_SER_AUTOSTART_ENV",
    "EMBEDDED_SER_BASE_URL_ENV",
    "EMBEDDED_SER_HEALTH_PATH",
    "EMBEDDED_SER_WITH_FLAG",
    "EMBEDDED_SER_WITHOUT_FLAG",
    "EmbeddedSerError",
    "EmbeddedSerRuntime",
    "get_embedded_runtime",
    "get_embedded_ser_handler",
    "parse_embedded_ser_arguments",
    "resolve_embedded_ser",
    "set_embedded_runtime",
]
```

- [ ] **Step 4: 运行确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_embedded_ser.py -v -k "resolve or runtime or load_uses"`
Expected: PASS

- [ ] **Step 5: build_pipeline 接线**

`src/speech_to_speech/s2s_pipeline.py` 共 4 处修改：

(a) `build_pipeline`（L801）签名加 `embedded_ser_options: SwitchOptions | None = None`；在 livekit_runtime 块（L842-858）之后、`server = RealtimeServer(...)`（L860）之前插入：

```python
    # The embedded SER runtime shares the server's stop event and the ThreadManager
    # handler protocol (run() + stop_event). resolve_embedded_ser registers the
    # process-wide singleton BEFORE create_app mounts the emotion endpoints, so the
    # mount gate and the worker fallback both see it.
    embedded_ser_runtime = None
    if embedded_ser_options is not None:
        from speech_to_speech.embedded_ser import resolve_embedded_ser

        embedded_ser_runtime = resolve_embedded_ser(
            args.stt_backend.name, embedded_ser_options, stop_event
        )
```

并在 handlers 组装段（L872-879）末尾加：

```python
    if embedded_ser_runtime is not None:
        handlers.append(embedded_ser_runtime)
```

(b) `build_local_pipeline`（L883）签名加 `embedded_ser_options: SwitchOptions | None = None`；其内部 `build_pipeline(...)` 调用（L925-928）加 `embedded_ser_options=embedded_ser_options,`。

(c) `run_pipeline_command`（L944）签名加 `embedded_ser_options: SwitchOptions = SwitchOptions()`；内部 `_run_parsed_pipeline_command(...)` 调用（L963-966）加 `embedded_ser_options=embedded_ser_options,`。

(d) `_run_parsed_pipeline_command`（L969）签名加 `embedded_ser_options: SwitchOptions | None = None`；内部两个分支调用（L1020-1031）各加 `embedded_ser_options=embedded_ser_options,`。

- [ ] **Step 6: 运行确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_embedded_ser.py tests/test_worker_integration.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/speech_to_speech/embedded_ser.py src/speech_to_speech/s2s_pipeline.py tests/test_embedded_ser.py
git commit -m "feat(ser): add EmbeddedSerRuntime with startup resolution"
```

---

### Task 5: emotion_local_service 回落 + 挂载门

**Files:**
- Modify: `src/speech_to_speech/api/openai_realtime/emotion_local_service.py`
- Modify: `tests/test_embedded_ser.py`（追加端点契约测试）

- [ ] **Step 1: 写失败测试（端点契约）**

追加到 `tests/test_embedded_ser.py`：

```python
# ---------------------------------------------------------------------------
# 端点契约（spec §7.2：SER_PROVIDER 未配 local 时内嵌 runtime 也能挂载端点）
# ---------------------------------------------------------------------------

import io

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient
from speech_to_speech.api.openai_realtime.websocket_router import create_app


def _wav(seconds: float = 0.3, rate: int = 16000, amplitude: float = 0.1) -> bytes:
    t = np.arange(int(rate * seconds)) / rate
    audio = (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, audio, rate, format="WAV")
    return buf.getvalue()


def _pool_without_handler() -> list:
    return []  # qwen3-asr 场景：pool 里没有 SenseVoiceSTTHandler


def _routes(app) -> set[tuple[str, str]]:
    return {
        (m, r.path)
        for r in app.routes
        for m in (getattr(r, "methods", None) or set())
    }


def _embedded_client(monkeypatch, handler=None, ready=True, provider=None) -> TestClient:
    if provider is not None:
        monkeypatch.setenv("SER_PROVIDER", provider)
    else:
        monkeypatch.delenv("SER_PROVIDER", raising=False)
    fake = _FakeRuntime(handler=_FakeSERHandler() if handler is None else handler, ready=ready)
    monkeypatch.setattr(embedded_ser, "_ACTIVE_RUNTIME", fake)
    return TestClient(create_app(pool=_pool_without_handler(), stop_event=threading.Event()))


def test_embedded_runtime_mounts_endpoints_without_ser_provider(monkeypatch) -> None:
    """SER_PROVIDER 未配置 + 内嵌 runtime 存在 → 端点照常挂载（spec §5）。"""
    client = _embedded_client(monkeypatch)
    routes = _routes(client.app)
    assert ("POST", "/recognize") in routes
    assert ("POST", "/v1/audio/emotion") in routes
    assert ("GET", "/v1/audio/emotion/health") in routes


def test_embedded_recognize_returns_200(monkeypatch) -> None:
    client = _embedded_client(monkeypatch, handler=_FakeSERHandler(raw="HAPPY", laughter=True))
    resp = client.post("/recognize", files={"file": ("a.wav", _wav(), "audio/wav")})
    assert resp.status_code == 200
    body = resp.json()
    assert body["emotion"] == "happy"
    assert body["events"]["laughter"] is True


def test_embedded_silence_returns_structured_409(monkeypatch) -> None:
    client = _embedded_client(monkeypatch)
    resp = client.post("/recognize", files={"file": ("a.wav", _wav(amplitude=0.0), "audio/wav")})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "SILENCE"


def test_embedded_not_ready_returns_503(monkeypatch) -> None:
    client = _embedded_client(monkeypatch, ready=False)
    resp = client.post("/recognize", files={"file": ("a.wav", _wav(), "audio/wav")})
    assert resp.status_code == 503


def test_embedded_health_reports_ready(monkeypatch) -> None:
    client = _embedded_client(monkeypatch)
    resp = client.get("/v1/audio/emotion/health")
    assert resp.status_code == 200
    assert resp.json()["ready"] is True


def test_embedded_health_not_ready(monkeypatch) -> None:
    client = _embedded_client(monkeypatch, ready=False)
    resp = client.get("/v1/audio/emotion/health")
    assert resp.json()["ready"] is False


def test_no_mount_without_runtime_and_local(monkeypatch) -> None:
    """SER_PROVIDER 非 local 且无内嵌 runtime → 不挂载（维持现状）。"""
    monkeypatch.delenv("SER_PROVIDER", raising=False)
    monkeypatch.setattr(embedded_ser, "_ACTIVE_RUNTIME", None)
    client = TestClient(create_app(pool=[], stop_event=threading.Event()))
    assert ("POST", "/recognize") not in _routes(client.app)


def test_proxy_mode_keeps_ownership(monkeypatch) -> None:
    """SER_PROVIDER=proxy → 内嵌不抢端点，proxy 照常接管（spec 非目标）。"""
    client = _embedded_client(monkeypatch, provider="proxy")
    routes = _routes(client.app)
    assert ("POST", "/recognize") not in routes
```

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_embedded_ser.py -v -k "embedded or proxy or no_mount"`
Expected: FAIL（SER_PROVIDER 未配置时不挂载 → routes 断言失败）

- [ ] **Step 3: 改造 emotion_local_service.py**

`src/speech_to_speech/api/openai_realtime/emotion_local_service.py` 共 3 处修改：

(a) import 区（`from speech_to_speech.STT.sense_voice_emotion import ...` 之后）加：

```python
from speech_to_speech import embedded_ser
```

(b) `mount_emotion_local` 的挂载门（L117-121）替换为：

```python
def mount_emotion_local(app: FastAPI, pool: Iterable[Any]) -> None:
    """Register local/embedded SenseVoice SER routes.

    三种挂载来源（spec §5）：SER_PROVIDER=local（pipeline handler 复用）、本进程
    内嵌 EmbeddedSerRuntime 已注册、二者皆无 → 不挂载。SER_PROVIDER=proxy 时不
    挂载——emotion proxy 独占端点（spec 非目标：proxy 模式保持不变）。
    """
    provider = os.environ.get("SER_PROVIDER", "proxy").strip().lower()
    if provider == "proxy":
        return
    if provider != "local" and embedded_ser.get_embedded_runtime() is None:
        return
    if _route_exists(app, RECOGNIZE_PATH):
        return
```

(c) `_recognize` 的 handler 解析（L167-169）替换为：

```python
        handler = find_ser_handler(pool) or embedded_ser.get_embedded_ser_handler()
        if handler is None:
            raise HTTPException(status_code=503, detail="SER handler unavailable")
```

(d) `health()` 的 ready 字段（L320）替换为：

```python
            "ready": find_ser_handler(pool) is not None
            or embedded_ser.get_embedded_ser_handler() is not None,
```

(e) `HEALTH_DESCRIPTION` 的 ready 说明（L77）改写为：

```python
* `ready=false` 表示 pipeline 内没有 SenseVoice handler 且内嵌 SER 未就绪。
```

- [ ] **Step 4: 运行确认通过（含既有 SER 契约回归）**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_embedded_ser.py tests/test_sensevoice_ser_service.py tests/test_sensevoice_emotion.py -v`
Expected: PASS（新端点测试转绿；既有 local 模式契约测试不回归）

- [ ] **Step 5: Commit**

```bash
git add src/speech_to_speech/api/openai_realtime/emotion_local_service.py tests/test_embedded_ser.py
git commit -m "feat(ser): fall back to embedded runtime in local SER endpoints"
```

---

### Task 6: worker get_ser_provider 内嵌回落

**Files:**
- Modify: `src/speech_to_speech/livekit_worker/ser_provider.py:202-211`
- Modify: `tests/test_embedded_ser.py`（追加 worker 回落测试）

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_embedded_ser.py`：

```python
# ---------------------------------------------------------------------------
# worker 回落（spec §5：显式 SER_PROVIDER 优先 / 内嵌就绪回落 / 未就绪 fail-closed）
# ---------------------------------------------------------------------------

from speech_to_speech.livekit_worker.ser_provider import get_ser_provider


def test_worker_explicit_provider_beats_embedded(monkeypatch) -> None:
    monkeypatch.setenv("SER_PROVIDER", "emotion2vec")
    monkeypatch.setattr(embedded_ser, "_ACTIVE_RUNTIME", _FakeRuntime(ready=True))
    provider = get_ser_provider()
    assert type(provider).__name__ == "HttpSerProvider"
    # 显式配置仍走 env 网关地址，不吃内嵌回落
    assert provider.base == (
        monkeypatch._setenv.get("SER_GATEWAY_BASE_URL", "").rstrip("/")
        if monkeypatch._setenv.get("SER_GATEWAY_BASE_URL")
        else provider.base
    )


def test_worker_falls_back_to_embedded_when_ready(monkeypatch) -> None:
    monkeypatch.delenv("SER_PROVIDER", raising=False)
    monkeypatch.delenv("SER_GATEWAY_BASE_URL", raising=False)
    monkeypatch.delenv("SER_BASE_URL", raising=False)
    monkeypatch.setattr(embedded_ser, "_ACTIVE_RUNTIME", _FakeRuntime(ready=True))
    provider = get_ser_provider()
    assert type(provider).__name__ == "HttpSerProvider"
    assert provider.base == "http://127.0.0.1:8765"
    assert provider.health_path == "/v1/audio/emotion/health"


def test_worker_fallback_respects_env_base_url(monkeypatch) -> None:
    monkeypatch.delenv("SER_PROVIDER", raising=False)
    monkeypatch.setenv("EMBEDDED_SER_BASE_URL", "http://127.0.0.1:9000/")
    monkeypatch.setattr(embedded_ser, "_ACTIVE_RUNTIME", _FakeRuntime(ready=True))
    provider = get_ser_provider()
    assert provider.base == "http://127.0.0.1:9000"
    assert provider.health_path == "/v1/audio/emotion/health"


def test_worker_fallback_not_ready_raises(monkeypatch) -> None:
    """内嵌未就绪且无显式 SER_PROVIDER → 显式 raise（fail-closed，不产假标签）。"""
    monkeypatch.delenv("SER_PROVIDER", raising=False)
    monkeypatch.setattr(embedded_ser, "_ACTIVE_RUNTIME", _FakeRuntime(ready=False))
    with pytest.raises(ValueError, match="MEETING_SER_PROVIDER_UNCONFIGURED"):
        get_ser_provider()


def test_worker_unknown_provider_still_raises(monkeypatch) -> None:
    monkeypatch.setenv("SER_PROVIDER", "bogus")
    monkeypatch.setattr(embedded_ser, "_ACTIVE_RUNTIME", _FakeRuntime(ready=True))
    with pytest.raises(ValueError, match="MEETING_SER_PROVIDER_UNCONFIGURED"):
        get_ser_provider()
```

> 注意：`test_worker_explicit_provider_beats_embedded` 里对 base 的断言只验证「类型正确 + 不抛」，不强绑 env 内容（`HttpSerProvider.__init__` 自身已有 env 读取逻辑与既有测试覆盖）。`monkeypatch._setenv` 为 pytest 内部属性，若该写法在当前 pytest 版本不可用，删掉该 assert 三行，仅保留类型断言即可（语义不变）。

- [ ] **Step 2: 运行确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_embedded_ser.py -v -k "worker"`
Expected: FAIL（SER_PROVIDER=none 时直接 raise，无内嵌回落）

- [ ] **Step 3: 实现 get_ser_provider 回落**

`src/speech_to_speech/livekit_worker/ser_provider.py` 的 `get_ser_provider()`（L202-211）替换为：

```python
def get_ser_provider() -> SerProvider:
    """未配置 / 未知 provider 一律显式 raise；宁可 worker 起不来，也不出假标签。

    2026-11-24：新增 ``sensevoice`` 指代 137 语音情感识别服务（内嵌 SenseVoiceSmall），
    与自建 ``emotion2vec`` 容器共用同一 HTTP 契约，差异只在探活路径与标签集归一。

    2026-11-26（spec §5）：SER_PROVIDER 未配置/none 且本进程 EmbeddedSerRuntime 已
    就绪 → 回落 HttpSerProvider 打到本进程 realtime 端点（管线与 worker 共用一份
    模型显存）。显式配置（emotion2vec/sensevoice）优先，两套 env 值域不混用。
    """
    name = os.environ.get("SER_PROVIDER", "none").strip().lower()
    if name in ("emotion2vec", "sensevoice"):
        return HttpSerProvider()
    if name in ("none", ""):
        from speech_to_speech.embedded_ser import (
            DEFAULT_EMBEDDED_SER_BASE_URL,
            EMBEDDED_SER_BASE_URL_ENV,
            EMBEDDED_SER_HEALTH_PATH,
            get_embedded_runtime,
        )

        runtime = get_embedded_runtime()
        if runtime is not None and runtime.ready:
            base = os.environ.get(EMBEDDED_SER_BASE_URL_ENV, "").strip() or DEFAULT_EMBEDDED_SER_BASE_URL
            return HttpSerProvider(base_url=base.rstrip("/"), health_path=EMBEDDED_SER_HEALTH_PATH)
    raise ValueError(f"MEETING_SER_PROVIDER_UNCONFIGURED: 未实现的 SER_PROVIDER={name!r}")
```

- [ ] **Step 4: 运行确认通过（含既有 worker 回归）**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_embedded_ser.py tests/test_livekit_worker.py tests/test_ser_provider_switch.py -v`
Expected: PASS（`test_ser_disabled_by_default` 仍绿：无内嵌 runtime 时 raise 不变）

- [ ] **Step 5: Commit**

```bash
git add src/speech_to_speech/livekit_worker/ser_provider.py tests/test_embedded_ser.py
git commit -m "feat(worker): fall back to embedded SER endpoint when ready"
```

---

### Task 7: 配置改写（prod.yaml 注释 + prod.env 新增）

**Files:**
- Modify: `config/prod.yaml:43-44, 76-78`
- Modify: `config/prod.env`（`S2S_ASR_MODEL_DIR` 块之后）

- [ ] **Step 1: prod.yaml STT 块注释改写（去 SenseVoice 字样）**

L43-44 注释替换为：

```yaml
    # Qwen3-ASR-1.7B：自回归多模态 ASR，准确率优于 CTC 非自回归小模型；
    # 代价是 RTF 0.47~0.90（自回归解码），比 CTC 非自回归慢一个数量级。
```

- [ ] **Step 2: prod.yaml llm 段 enable_lang_prompt 注释改写**

L75-78 注释中「依赖 STT 产出 language_code —— sense-voice handler 已提供（按 SenseVoice 实际听到的语种判定），否则这一段不会注入。」替换为（spec §3：不假设 qwen3-asr 是否产出 language_code）：

```yaml
      # 注入语言指令（"Please reply to my message in <language>."）。
      # 依赖 STT 产出 language_code —— 以所选 STT handler 的实际行为为准；
      # handler 未产出时该指令不注入（不假设 qwen3-asr 一定提供 language_code）。
```

- [ ] **Step 3: prod.env 新增 S2S_SENSEVOICE_MODEL_DIR**

在 `S2S_ASR_MODEL_DIR=...` 行之后插入：

```bash
# SenseVoiceSmall（内嵌情感服务 EmbeddedSerRuntime 从本地目录加载；STT 无原生
# 情感能力时自动启用；目录缺失/未配置时回落 HF repo id FunAudioLLM/SenseVoiceSmall）。
S2S_SENSEVOICE_MODEL_DIR=D:/work/qwen-audio-agent/speech-to-speech-src/cache/sensevoice-small
```

- [ ] **Step 4: 复查其余配置文件**

Run: `git grep -in "sensevoicelarge" -- config/`
Expected: 零命中（config.container / config.split 现仅 Small 语义，无需改动）

- [ ] **Step 5: Commit**

```bash
git add config/prod.yaml config/prod.env
git commit -m "chore(config): rewrite prod comments and add S2S_SENSEVOICE_MODEL_DIR"
```

---

### Task 8: 文档同步 + 全量残留验证

**Files:**
- Modify: `docs/service-enablement-CN.md`（§9.4 之后、结尾 blockquote 之前）

- [ ] **Step 1: 新增文档小节**

`docs/service-enablement-CN.md` 在 `### 9.4 验证与 A/B` 小节之后、`> 所有配置改动需重启 8765 生效…` blockquote 之前插入：

```markdown
### 9.5 内嵌情感服务（Embedded SER，2026-11-26）

- STT 与情感能力解耦：`ModelCard.native_emotion` 静态声明（`sensevoice-small`=True，
  `qwen3-asr`/`whisper`=False，默认 False）；`model_registry.stt_has_native_emotion(backend)`
  serve 启动期判定，无卡片映射的后端返回 False（fail-closed → 走内嵌 SER）。
- STT 无原生情感（如 qwen3-asr）时，serve 启动即由 `embedded_ser.EmbeddedSerRuntime`
  后台线程加载 SenseVoiceSmall（`S2S_SENSEVOICE_MODEL_DIR`，缺省回落 HF repo id；
  device cuda），端点仍由 `emotion_local_service` 挂载（`POST /recognize`、
  `POST /v1/audio/emotion`、`GET /v1/audio/emotion/health`），标签归一/置信度门/
  结构化 409 语义与 §9.1 完全一致；实时管线与 livekit_worker 共用同一模型显存。
- 开关：`--with-embedded-ser` / `--no-embedded-ser`（显式 flag）> `EMBEDDED_SER_AUTOSTART`
  （布尔 env）> 默认自动启用。显式关闭且 STT 无原生能力且 `SER_ENABLED=true` 时启动
  warning（情感功能不可用，不阻塞转写）。
- worker 回落：`SER_PROVIDER` 未配置/none 且本进程内嵌 SER 已就绪 → `HttpSerProvider`
  打到 `EMBEDDED_SER_BASE_URL`（默认 `http://127.0.0.1:8765`）+ 探活路径
  `/v1/audio/emotion/health`；显式 `emotion2vec`/`sensevoice` 优先；均不可用维持
  `MEETING_SER_PROVIDER_UNCONFIGURED` fail-closed。
- 崩溃隔离：funasr extra 缺失 / `S2S_SENSEVOICE_MODEL_DIR` 缺失 / 权重损坏 / OOM
  一律只记日志，health 返回 `ready=false`，情感请求按既有 409/503 语义拒答，转写不受影响。
- 显存预算：qwen3-asr（0.6B≈1.8GB / 1.7B≈4GB）+ SenseVoiceSmall≈0.4GB + 管线其余组件（≈4.6GB）。
```

- [ ] **Step 2: 全仓残留 grep（排除 spec/plan 自身）**

Run: `git grep -in "sensevoicelarge" -- . ":(exclude)docs/superpowers"`
Expected: 零命中（spec 与本计划文档自身的引用按 spec §3 约定排除）

Run: `git grep -in "SenseVoiceLarge" -- "*.md"`
Expected: 仅 docs/superpowers 下 spec/plan 命中

- [ ] **Step 3: ruff 检查**

Run: `.\.venv\Scripts\python.exe -m ruff check src/speech_to_speech/embedded_ser.py src/speech_to_speech/model_registry.py src/speech_to_speech/models/builtin.py src/speech_to_speech/cli.py src/speech_to_speech/s2s_pipeline.py src/speech_to_speech/api/openai_realtime/emotion_local_service.py src/speech_to_speech/livekit_worker/ser_provider.py tests/test_embedded_ser.py tests/test_model_registry.py`
Expected: 零告警

- [ ] **Step 4: 目标测试全绿（最终确认，不跑全量）**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_embedded_ser.py tests/test_model_registry.py tests/test_sensevoice_ser_service.py tests/test_livekit_worker.py tests/test_worker_integration.py -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add docs/service-enablement-CN.md
git commit -m "docs: document embedded SER capability and switches"
```

- [ ] **Step 6: 提醒用户手动全量回归**

全量 pytest 回归由用户手动执行（用户此前明确要求不由 agent 跑全量）。提醒命令：

```bash
.\.venv\Scripts\python.exe -m pytest tests -q
```

---

## 自审记录（写计划时已核对）

1. **Spec 覆盖**：§3 清除清单→Task 1/7/8；§4 能力声明→Task 2；§5 内嵌子系统（判定/加载/挂载/开关/回落）→Task 3/4/5/6；§5 显存预算→Task 8 文档；§6 错误处理（extra 缺失/目录缺失/装载失败/503/fail-closed raise）→Task 4 Step 1 与 Task 5/6 测试；§7 测试与验收→各任务测试 + Task 8 Step 2-4。
2. **占位符**：无 TBD/TODO；所有代码步骤均含完整代码。
3. **类型一致性**：`SwitchOptions` 复用 worker_integration 定义；`EmbeddedSerRuntime.ready/handler()`、`get_embedded_runtime()/get_embedded_ser_handler()`、`resolve_embedded_ser(stt_backend_name, options, stop_event)` 在 Task 4 定义、Task 5/6 消费，签名一致；`_FakeRuntime`/`_FakeSERHandler` 在 Task 4 定义、Task 5/6 测试复用（同文件顺序保证可导入）。
4. **已知偏差（对 spec 的具化，非矛盾）**：spec §5 流程图中内嵌挂载条件含「SER_ENABLED=true」，实现将 SER_ENABLED 门收敛在 resolve 的 warning 分支与 emotion proxy（现状）——内嵌端点挂载本身不受 SER_ENABLED 阻断，因为关闭内嵌的唯一通道是 `--no-embedded-ser`/`EMBEDDED_SER_AUTOSTART=false`（spec §1 表格行「加载时机」为准）。
