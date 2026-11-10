# 统一模型注册框架（Spec A）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `speech-to-speech-src` 增加 `ModelCard` / `ModelRegistry` 元信息层、YAML `models:` 覆盖通道、`models list` 只读命令与接入规范文档，且不改动任何既有后端行为。

**Architecture:** 沿用方案 1：`BackendSpec` 加一个带默认值的可选 `models` 字段，独立 `model_registry.py` 提供卡片注册/查询/校验；`models/builtin.py` 声明内置卡片；`config.py` 在 `resolve_config()` 内按 pipeline 生成卡片副本；`cli.py` 提供只读列举。卡片只作元信息声明，不进 `spec.normalize()` 链。

**Tech Stack:** Python 3.11+、dataclasses、`HfArgumentParser`、PyYAML（经 `speech_to_speech._config_yaml`）、pytest、ruff、mypy。

## Global Constraints

- 验收为**代码就绪 + 契约测试**：写真实加载/推理代码但不下载权重，用 mock/stub 验证；全部测试不触网、不占显存。
- **31 条 `BackendSpec(...)` 构造逐字不改**；`--stt/--llm_backend/--tts` 的 choices 与默认值不变；`config/prod.yaml` 与 9 个 `docker-compose*.yml` 内容不变；`example_configs/mac.yaml` 不变。
- **不改动**：`module_arguments.py`、`s2s_pipeline.py` 的参数类拼装与 choices 派生、`configured_runtime.py`、`baseHandler.py`、`pipeline/*`、所有现有 Handler、`pyproject.toml`（Spec A 无新依赖）。
- Audio 契约（写入接入规范，本 spec 不实现 Handler）：STT 输入 16 kHz float32 `VADAudio`；TTS 输出 16 kHz int16 PCM / 512 samples 块 + `AUDIO_RESPONSE_DONE`。
- CLI 模式与 YAML 文件模式二选一；YAML 内优先级 `显式字段 > {env: NAME} > 默认`；环境变量引用缺失即报错、不回退默认。
- **用户已确认本工程存在商用场景（D7）：禁止自托管 Breeze TTS 2 权重**；`breeze-tts-2` card 为 `deprecated`，Spec B 走路径 L（CosyVoice2 等可商用本地 TTS）或路径 R（BreezeBlue 付费托管 API）。Spec A 不实现任何远程调用或权重加载。
- `min_vram_gb` 为**单一基准数值**（默认加载配置下单路峰值 GiB），其它量化档/快路径写入 `card.notes`。
- 状态分布（按 card 计）：3 张 `available`、5 张 `planned`、1 张 `deprecated`、27 个无 card 的已注册后端显示 `unregistered`。
- CI 同款命令：`ruff check src/ tests/`、`ruff format --check src/ tests/`、`mypy src/`、`pytest tests/ -x -q`。
- 导入 `model_registry` 不得触发任何 `speech_to_speech.STT.*` / `TTS.*` / `LLM.language_model` 模块导入（既有延迟导入边界）。
- 提交信息使用英文 conventional commit 前缀（如 `feat(model-registry): ...`）；每次提交只包含本任务文件。

---

## File Structure

| 文件 | 职责 | 任务 |
|---|---|---|
| `src/speech_to_speech/model_registry.py` | `ModelCard` / `ModelRegistry` / 三个异常 / 模块级门面；不 import 任何 handler | T1 |
| `src/speech_to_speech/models/__init__.py` | 包标记 | T2 |
| `src/speech_to_speech/models/builtin.py` | 9 张内置卡片（3 available / 5 planned / 1 deprecated） | T2 |
| `src/speech_to_speech/backend_registry.py` | `BackendSpec.models` 可选字段 + 末尾 `bind_model_cards()` 调用 | T3 |
| `src/speech_to_speech/config.py` | 顶层 `models:` 白名单与校验、`ResolvedPipeline.model_cards`、`_apply_model_overrides()`、`resolve_config()` 接线 | T4 |
| `src/speech_to_speech/cli.py` | `models` 子命令、`Command` 类型、parser、`_dispatch()` 分流、只读打印 | T5 |
| `docs/model-integration-guide-CN.md` | 9 节接入规范 | T6 |
| `tests/test_model_registry.py` | 卡片/注册/校验/门面/延迟导入/许可告警测试 | T1、T2、T3 |
| `tests/test_model_config_overrides.py` | YAML `models:` 覆盖、隔离、错误路径、JSON 输出测试 | T4、T5 |
| `example_configs/models-overrides.yaml` | 示例 YAML（不改动既有 `config/prod.yaml`） | T4 |

---

### Task 1: `model_registry.py` 核心与门面

**Files:**
- Create: `src/speech_to_speech/model_registry.py`
- Test: `tests/test_model_registry.py`

**Interfaces:**
- Consumes: 无（新模块，仅标准库）。
- Produces: `ModelKind`、`ModelStatus`、`WeightFormat`、`ModelCard`、`ModelRegistry`、`ModelRegistryError`、`ModelNotAvailableError`、`ModelLicenseError`、`MODEL_REGISTRY`、`register_model(card)`、`list_models(*, kind=None, status=None) -> tuple[ModelCard, ...]`、`get_model(model_id) -> ModelCard`（不检查 status）、`resolve_model(model_id) -> ModelCard`（拒绝 `planned`）、`load_param_types(model_id) -> Mapping[str, Any]`、`bind_model_cards(registries)`、`validate_models()`。

- [ ] **Step 1: Write the failing test**

创建 `tests/test_model_registry.py`：

```python
import subprocess
import sys
from dataclasses import FrozenInstanceError, dataclass

import pytest

from speech_to_speech import model_registry as mr
from speech_to_speech.model_registry import (
    ModelCard,
    ModelLicenseError,
    ModelNotAvailableError,
    ModelRegistry,
    ModelRegistryError,
    list_models,
    resolve_model,
    validate_models,
)


def card(**overrides):
    base = dict(
        id="test-tts",
        name="Test TTS",
        kind="tts",
        version="1",
        provider="Test",
        weight_format="safetensors",
        backend_name="fake-tts",
    )
    base.update(overrides)
    return ModelCard(**base)


@dataclass
class FakeArgs:
    model_name: str = "x"
    device: str = "cuda"


class FakeSpec:
    def __init__(self, kind, config_type=FakeArgs):
        self.kind = kind
        self.config_type = config_type


def registries():
    return {"stt": {}, "llm": {}, "tts": {"fake-tts": FakeSpec("tts")}}


def test_card_is_frozen():
    with pytest.raises(FrozenInstanceError):
        card().name = "changed"


def test_register_rejects_duplicate_id():
    reg = ModelRegistry()
    reg.register(card())
    with pytest.raises(ModelRegistryError, match="Duplicate"):
        reg.register(card())


def test_list_filters_and_sorts_by_id():
    reg = ModelRegistry()
    reg.register(card(id="z", status="planned"))
    reg.register(card(id="a", kind="stt"))
    assert [c.id for c in reg.list()] == ["a", "z"]
    assert [c.id for c in reg.list(kind="stt")] == ["a"]
    assert [c.id for c in reg.list(status="planned")] == ["z"]


def test_get_unknown_lists_known_ids():
    reg = ModelRegistry()
    reg.register(card())
    with pytest.raises(ModelRegistryError, match="test-tts"):
        reg.get("missing")


def test_by_backend():
    reg = ModelRegistry()
    reg.register(card())
    assert [c.id for c in reg.by_backend("fake-tts")] == ["test-tts"]


def test_bind_detects_kind_mismatch_and_missing_available_backend():
    reg = ModelRegistry()
    reg.register(card(kind="stt", status="available"))
    reg.register(card(id="ghost", status="available", backend_name="no-such-backend"))
    with pytest.raises(ModelRegistryError, match="validation failed"):
        reg.bind(registries())


def test_bind_allows_planned_card_with_unregistered_backend():
    reg = ModelRegistry()
    reg.register(card(status="planned", backend_name="future-tts"))
    reg.bind(registries())
    assert reg.get("test-tts").status == "planned"


def test_bind_rejects_unknown_load_param_and_exposes_types():
    reg = ModelRegistry()
    reg.register(card(default_load_params={"bogus": 1}))
    with pytest.raises(ModelRegistryError, match="unknown load params"):
        reg.bind(registries())
    reg2 = ModelRegistry()
    reg2.register(card())
    reg2.bind(registries())
    assert set(reg2.load_param_types("test-tts")) == {"model_name", "device"}


def test_resolve_model_planned_raises_and_deprecated_returns(monkeypatch):
    reg = ModelRegistry()
    reg.register(card(id="planned-model", status="planned"))
    reg.register(card(id="deprecated-model", status="deprecated"))
    monkeypatch.setattr(mr, "MODEL_REGISTRY", reg)
    with pytest.raises(ModelNotAvailableError, match="Spec B"):
        resolve_model("planned-model")
    assert resolve_model("deprecated-model").status == "deprecated"


def test_license_error_is_registry_error():
    assert issubclass(ModelLicenseError, ModelRegistryError)


def test_module_level_facades(monkeypatch):
    monkeypatch.setattr(mr, "MODEL_REGISTRY", ModelRegistry())
    mr.register_model(card(id="facade", status="planned", backend_name="future-tts"))
    assert [c.id for c in list_models(status="planned")] == ["facade"]
    assert mr.get_model("facade").status == "planned"
    validate_models()


def assert_no_handler_modules(module: str) -> None:
    code = (
        f"import sys, {module}; "
        "prefixes = ('speech_to_speech.STT.', 'speech_to_speech.TTS.', 'speech_to_speech.LLM.'); "
        "assert not [k for k in sys.modules if k.startswith(prefixes)], "
        "sorted(k for k in sys.modules if k.startswith(prefixes))"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_import_does_not_load_backend_handlers():
    assert_no_handler_modules("speech_to_speech.model_registry")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_model_registry.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'speech_to_speech.model_registry'`.

- [ ] **Step 3: Write minimal implementation**

创建 `src/speech_to_speech/model_registry.py`：

```python
"""Static model metadata for ASR / LLM / TTS components.

Importing this module never imports a backend handler module.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from typing import Any, Literal, get_type_hints

ModelKind = Literal["stt", "llm", "tts"]
ModelStatus = Literal["available", "planned", "deprecated"]
WeightFormat = Literal["safetensors", "gguf", "mlx", "remote"]


class ModelRegistryError(ValueError):
    """Invalid model catalog state."""


class ModelNotAvailableError(ModelRegistryError):
    """A model whose adapter layer is not implemented was resolved."""


class ModelLicenseError(ModelRegistryError):
    """A commercial deployment selected a non-commercial weight."""


@dataclass(frozen=True)
class ModelCard:
    id: str
    name: str
    kind: ModelKind
    version: str
    provider: str
    weight_format: WeightFormat
    backend_name: str
    repo_id: str | None = None
    default_load_params: Mapping[str, Any] = field(default_factory=dict)
    min_vram_gb: float | None = None
    license: str | None = None
    status: ModelStatus = "available"
    notes: str = ""


class ModelRegistry:
    def __init__(self) -> None:
        self._cards: dict[str, ModelCard] = {}
        self._backend_index: dict[str, tuple[ModelKind, dict[str, Any]]] = {}

    def register(self, card: ModelCard) -> None:
        if card.id in self._cards:
            raise ModelRegistryError(f"Duplicate model id: {card.id!r}.")
        self._cards[card.id] = card

    def get(self, model_id: str) -> ModelCard:
        try:
            return self._cards[model_id]
        except KeyError:
            known = ", ".join(sorted(self._cards)) or "<none>"
            raise ModelRegistryError(f"Unknown model id {model_id!r}. Known ids: {known}.") from None

    def list(
        self, *, kind: ModelKind | None = None, status: ModelStatus | None = None
    ) -> tuple[ModelCard, ...]:
        selected = (
            item
            for item in self._cards.values()
            if (kind is None or item.kind == kind) and (status is None or item.status == status)
        )
        return tuple(sorted(selected, key=lambda item: item.id))

    def by_backend(self, backend_name: str) -> tuple[ModelCard, ...]:
        return tuple(
            sorted(
                (item for item in self._cards.values() if item.backend_name == backend_name),
                key=lambda item: item.id,
            )
        )

    def bind(self, registries: Mapping[str, Mapping[str, Any]]) -> None:
        index: dict[str, tuple[ModelKind, dict[str, Any]]] = {}
        for kind, registry in registries.items():
            for name, spec in registry.items():
                hints = get_type_hints(spec.config_type)
                index[name] = (kind, hints)
        self._backend_index = index
        self.validate()

    def load_param_types(self, model_id: str) -> Mapping[str, Any]:
        card = self.get(model_id)
        entry = self._backend_index.get(card.backend_name)
        return entry[1] if entry else {}

    def validate(self) -> None:
        problems: list[str] = []
        for card in self._cards.values():
            entry = self._backend_index.get(card.backend_name)
            if entry is None:
                if card.status == "available":
                    problems.append(
                        f"{card.id}: available card references unregistered backend {card.backend_name!r}."
                    )
                continue
            kind, hints = entry
            if card.kind != kind:
                problems.append(f"{card.id}: kind {card.kind!r} != backend kind {kind!r}.")
            unknown = sorted(set(card.default_load_params) - set(hints))
            if unknown:
                problems.append(
                    f"{card.id}: unknown load params {unknown} for backend {card.backend_name!r}."
                )
        if problems:
            raise ModelRegistryError("Model catalog validation failed:\n" + "\n".join(problems))


MODEL_REGISTRY = ModelRegistry()


def register_model(card: ModelCard) -> None:
    MODEL_REGISTRY.register(card)


def list_models(
    *, kind: ModelKind | None = None, status: ModelStatus | None = None
) -> tuple[ModelCard, ...]:
    return MODEL_REGISTRY.list(kind=kind, status=status)


def get_model(model_id: str) -> ModelCard:
    return MODEL_REGISTRY.get(model_id)


def resolve_model(model_id: str) -> ModelCard:
    card = MODEL_REGISTRY.get(model_id)
    if card.status == "planned":
        raise ModelNotAvailableError(
            f"Model {card.id!r} is planned; its adapter layer is Spec B. "
            "See docs/model-integration-guide-CN.md section 3."
        )
    return card


def load_param_types(model_id: str) -> Mapping[str, Any]:
    return MODEL_REGISTRY.load_param_types(model_id)


def bind_model_cards(registries: Mapping[str, Mapping[str, Any]]) -> None:
    from speech_to_speech.models.builtin import builtin_model_cards

    for card in builtin_model_cards():
        MODEL_REGISTRY.register(card)
    MODEL_REGISTRY.bind(registries)


def validate_models() -> None:
    MODEL_REGISTRY.validate()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_model_registry.py -q`
Expected: PASS（12 tests passed）。`bind_model_cards()` 延迟 import `models.builtin`，但本任务的测试不调用它，因此 Task 2 之前不会失败。

- [ ] **Step 5: Commit**

```bash
git add src/speech_to_speech/model_registry.py tests/test_model_registry.py
git commit -m "feat(model-registry): add ModelCard and ModelRegistry"
```

---

### Task 2: 内置卡片清单

**Files:**
- Create: `src/speech_to_speech/models/__init__.py`
- Create: `src/speech_to_speech/models/builtin.py`
- Test: `tests/test_model_registry.py`（追加）

**Interfaces:**
- Consumes: `ModelCard`（Task 1）。
- Produces: `builtin_model_cards() -> tuple[ModelCard, ...]`，供 `bind_model_cards()` 注册。

- [ ] **Step 1: Write the failing test**

在 `tests/test_model_registry.py` 末尾追加：

```python
def test_builtin_catalog_status_counts_and_license_gate():
    from speech_to_speech.models.builtin import builtin_model_cards

    cards = builtin_model_cards()
    assert len(cards) == 9
    assert len({c.id for c in cards}) == 9
    assert sorted(c.id for c in cards if c.status == "available") == [
        "qwen3-asr-1.7b-hf",
        "qwen3-tts-1.7b-customvoice",
        "qwen3.5-4b-transformers",
    ]
    assert [c.id for c in cards if c.status == "deprecated"] == ["breeze-tts-2"]
    assert sum(c.status == "planned" for c in cards) == 5

    breeze = next(c for c in cards if c.id == "breeze-tts-2")
    assert "Research and Non-Commercial" in breeze.license
    assert "商用" in breeze.notes
    assert breeze.min_vram_gb == 7.7

    qwen_llm = next(c for c in cards if c.id == "minicpm-homologous-qwen3-8b")
    assert qwen_llm.min_vram_gb == 16.0


def test_builtin_cards_bind_without_error():
    from speech_to_speech.models.builtin import builtin_model_cards

    reg = ModelRegistry()
    for item in builtin_model_cards():
        reg.register(item)
    reg.bind(
        {
            "stt": {"qwen3-asr": FakeSpec("stt"), "whisper": FakeSpec("stt")},
            "llm": {"transformers": FakeSpec("llm")},
            "tts": {"qwen3": FakeSpec("tts")},
        }
    )
    assert len(reg.list()) == 9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_model_registry.py -q -k "builtin"`
Expected: FAIL — `ModuleNotFoundError: No module named 'speech_to_speech.models'`.

- [ ] **Step 3: Write minimal implementation**

创建 `src/speech_to_speech/models/__init__.py`（空文件，内容为一行模块说明）：

```python
"""Built-in model card catalog."""
```

创建 `src/speech_to_speech/models/builtin.py`：

```python
"""Static model cards shipped with speech-to-speech.

These are metadata only. None of these cards loads weights or imports handlers.
"""

from __future__ import annotations

from speech_to_speech.model_registry import ModelCard


def builtin_model_cards() -> tuple[ModelCard, ...]:
    return (
        ModelCard(
            id="qwen3-asr-1.7b-hf",
            name="Qwen3-ASR-1.7B",
            kind="stt",
            version="1.7b-hf",
            provider="Alibaba Qwen",
            weight_format="safetensors",
            backend_name="qwen3-asr",
            repo_id="Qwen/Qwen3-ASR-1.7B-hf",
            min_vram_gb=1.8,
            status="available",
            notes="docs/hardware/performance-assumptions.md 实测口径；代码 help 另标约 4 GB。",
        ),
        ModelCard(
            id="qwen3-tts-1.7b-customvoice",
            name="Qwen3-TTS-12Hz-1.7B-CustomVoice",
            kind="tts",
            version="12hz-1.7b",
            provider="Alibaba Qwen",
            weight_format="safetensors",
            backend_name="qwen3",
            repo_id="Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
            min_vram_gb=3.4,
            status="available",
            notes="许可未核实，license=None。",
        ),
        ModelCard(
            id="qwen3.5-4b-transformers",
            name="Qwen3.5-4B (transformers)",
            kind="llm",
            version="3.5-4b",
            provider="Alibaba Qwen",
            weight_format="safetensors",
            backend_name="transformers",
            repo_id="Qwen/Qwen3.5-4B",
            min_vram_gb=8.0,
            status="available",
            notes="默认 FP16 约 8 GB；4bit NF4 约 2.1 GB。",
        ),
        ModelCard(
            id="breeze-tts-2",
            name="Breeze TTS 2",
            kind="tts",
            version="2",
            provider="BreezeBlue",
            weight_format="safetensors",
            backend_name="breeze-tts-2",
            repo_id="BreezeBlue/Breeze-TTS-2",
            min_vram_gb=7.7,
            license="BreezeBlue Research and Non-Commercial License",
            status="deprecated",
            notes=(
                "商用场景（D7）禁用自托管：权重与自托管输出仅限研究/非商业。"
                "--fast-all 快路径 14.4 GiB；两者仅研究用途参考，不进入商用部署预算。"
                "官方输出 24 kHz mono s16le PCM；本地流式 API 单并发、忙时 409；"
                "checkpoint 自带 audio_tokenizer；--revision 固定权重版本。"
                "商用须按 spec §6.4 走路径 L（CosyVoice2）或路径 R（付费托管 API）；"
                "路径 R 由 Spec B 另注册 breeze-tts-2-hosted(weight_format=remote) card。"
            ),
        ),
        ModelCard(
            id="whisper-medium",
            name="Whisper-medium",
            kind="stt",
            version="medium",
            provider="OpenAI / MiniCPM-o 同源",
            weight_format="safetensors",
            backend_name="whisper",
            repo_id="openai/whisper-medium",
            status="planned",
            notes="MiniCPM-o 4.5 同源组件，非 MiniCPM 品牌独立模型。",
        ),
        ModelCard(
            id="cosyvoice2",
            name="CosyVoice2",
            kind="tts",
            version="2",
            provider="Alibaba / MiniCPM-o 同源",
            weight_format="safetensors",
            backend_name="cosyvoice2",
            repo_id="FunAudioLLM/CosyVoice2-0.5B",
            status="planned",
            notes=(
                "MiniCPM-o 4.5 同源组件，非 MiniCPM 品牌独立模型；"
                "同时承担 spec §6.4 路径 L 的 Breeze 替代位。"
                "官方代码仓库 LICENSE 为 Apache-2.0；权重许可须在 Spec B 启动前核对，"
                "通过前不得标 available。本仓 TTS/cosyvoice_handler.py 存在但未注册。"
            ),
        ),
        ModelCard(
            id="minicpm-homologous-qwen3-8b",
            name="Qwen3-8B（MiniCPM-o 同源 LLM）",
            kind="llm",
            version="3-8b",
            provider="Alibaba Qwen / MiniCPM-o 同源",
            weight_format="safetensors",
            backend_name="transformers",
            repo_id="Qwen/Qwen3-8B",
            min_vram_gb=16.0,
            status="planned",
            notes="MiniCPM-o 4.5 同源组件，非 MiniCPM 品牌独立模型；Q8 约 8.5 GB / Q4 约 5.0 GB。",
        ),
        ModelCard(
            id="minicpm-2b",
            name="MiniCPM-2B",
            kind="llm",
            version="2b",
            provider="OpenBMB",
            weight_format="safetensors",
            backend_name="transformers",
            min_vram_gb=1.2,
            status="planned",
            notes="可选；docs/models.md 的 2B Q4 估值。repo_id 待 Spec B 核实后补。",
        ),
        ModelCard(
            id="minicpm-4b",
            name="MiniCPM-4B",
            kind="llm",
            version="4b",
            provider="OpenBMB",
            weight_format="safetensors",
            backend_name="transformers",
            status="planned",
            notes="可选；repo_id 与显存待 Spec B 核实后补。",
        ),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_model_registry.py -q`
Expected: PASS（全部 14 tests）。

- [ ] **Step 5: Commit**

```bash
git add src/speech_to_speech/models/__init__.py src/speech_to_speech/models/builtin.py tests/test_model_registry.py
git commit -m "feat(model-registry): add builtin model cards"
```

---

### Task 3: `BackendSpec.models` 与注册表绑定

**Files:**
- Modify: `src/speech_to_speech/backend_registry.py:103-114`（`BackendSpec`）、`:12-56` 之后新增 import、文件末尾（`TTS_BACKENDS` 定义之后）
- Test: `tests/test_model_registry.py`（追加）

**Interfaces:**
- Consumes: `ModelCard`（Task 1）、`bind_model_cards()`（Task 1）、`builtin_model_cards()`（Task 2）。
- Produces: `BackendSpec.models: tuple[ModelCard, ...] = ()`；导入 `backend_registry` 时全局 `MODEL_REGISTRY` 已含 9 张内置卡片。

- [ ] **Step 1: Write the failing test**

在 `tests/test_model_registry.py` 末尾追加：

```python
def test_backend_spec_has_default_models_field():
    from speech_to_speech.backend_registry import STT_BACKENDS, TTS_BACKENDS, LLM_BACKENDS

    for registry in (STT_BACKENDS, LLM_BACKENDS, TTS_BACKENDS):
        for spec in registry.values():
            assert spec.models == (), spec.name
    assert len(STT_BACKENDS) + len(LLM_BACKENDS) + len(TTS_BACKENDS) == 31


def test_importing_backend_registry_populates_global_catalog():
    from speech_to_speech import model_registry as mr
    from speech_to_speech.backend_registry import STT_BACKENDS  # noqa: F401

    assert len(mr.list_models()) == 9
    assert mr.resolve_model("breeze-tts-2").status == "deprecated"


def test_backend_registry_import_keeps_handler_lazy_loading():
    assert_no_handler_modules("speech_to_speech.backend_registry")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_model_registry.py -q -k "backend_spec or populates or keeps_handler"`
Expected: FAIL — `AttributeError: 'BackendSpec' object has no attribute 'models'`。

- [ ] **Step 3: Write minimal implementation**

在 `src/speech_to_speech/backend_registry.py` 的 import 区（第 57-58 行附近）加入：

```python
from speech_to_speech.model_registry import ModelCard, bind_model_cards
```

把 `BackendSpec` 的最后一个字段后追加一行（保持现有 8 个字段逐字不变）：

```python
@dataclass(frozen=True)
class BackendSpec:
    """Static construction metadata for one built-in backend."""

    name: str
    kind: BackendKind
    config_type: type[Any]
    create_handler: HandlerFactory
    config_prefix: str | None = None
    normalize_config: ConfigNormalizer | None = None
    required_extra: str | None = None
    capabilities: BackendCapabilities = field(default_factory=BackendCapabilities)
    models: tuple[ModelCard, ...] = ()
```

在 `TTS_BACKENDS = build_backend_registry(...)` 定义结束之后、文件末尾追加：

```python
bind_model_cards({"stt": STT_BACKENDS, "llm": LLM_BACKENDS, "tts": TTS_BACKENDS})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_model_registry.py -q && pytest tests/test_backend_registry.py -q`
Expected: 全部 PASS（`test_backend_registry.py` 45 tests 零回归，含其自身的延迟导入测试）。

- [ ] **Step 5: Commit**

```bash
git add src/speech_to_speech/backend_registry.py tests/test_model_registry.py
git commit -m "feat(model-registry): bind builtin cards to backend registry"
```

---

### Task 4: YAML `models:` 覆盖通道

**Files:**
- Modify: `src/speech_to_speech/config.py:11`（import）、`:15-16`（TYPE_CHECKING）、`:81-86`（`ResolvedPipeline`）、`:374`（白名单）、`:438` 之后（校验调用）、`:441-538`（`resolve_config()`）
- Create: `example_configs/models-overrides.yaml`
- Test: `tests/test_model_config_overrides.py`

**Interfaces:**
- Consumes: `ModelCard`、`get_model()`、`load_param_types()`（Task 1）；`_mapping()` / `_error()` / `_value()`（`config.py` 既有）。
- Produces: `ResolvedPipeline.model_cards: Mapping[str, ModelCard]`；`_validate_models_section(document)`；`_apply_model_overrides(document, environment) -> dict[str, ModelCard]`。

- [ ] **Step 1: Write the failing test**

创建 `tests/test_model_config_overrides.py`：

```python
from pathlib import Path

import pytest

from speech_to_speech.config import ConfigurationError, load_config, resolve_config
from speech_to_speech.model_registry import resolve_model

EXAMPLE = Path(__file__).resolve().parents[1] / "example_configs" / "models-overrides.yaml"


def test_example_yaml_resolves_model_overrides():
    config = resolve_config(load_config(EXAMPLE), environ={"BREEZE_REPO": "/models/Breeze-TTS-2"})
    pipeline = config.pipelines["prod"]
    assert pipeline.model_cards["qwen3-tts-1.7b-customvoice"].repo_id == "/models/qwen3-tts"
    assert pipeline.model_cards["qwen3-tts-1.7b-customvoice"].default_load_params == {"qwen3_tts_device": "cpu"}
    assert pipeline.model_cards["minicpm-homologous-qwen3-8b"].repo_id == "/models/Breeze-TTS-2"
    assert resolve_model("qwen3-tts-1.7b-customvoice").repo_id != "/models/qwen3-tts"


def test_overrides_are_pipeline_local():
    document = load_config(EXAMPLE)
    document.data["pipelines"]["second"] = {
        "stages": dict(document.data["pipelines"]["prod"]["stages"]),
        "num_pipelines": 1,
    }
    config = resolve_config(document, environ={"BREEZE_REPO": "/models/Breeze-TTS-2"})
    first = config.pipelines["prod"].model_cards["qwen3-tts-1.7b-customvoice"]
    second = config.pipelines["second"].model_cards["qwen3-tts-1.7b-customvoice"]
    assert first is not second
    assert first.repo_id == second.repo_id == "/models/qwen3-tts"
    assert resolve_model("qwen3-tts-1.7b-customvoice").repo_id != "/models/qwen3-tts"


def test_unknown_model_id_is_rejected(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(EXAMPLE.read_text(encoding="utf-8").replace(
        "qwen3-tts-1.7b-customvoice:", "no-such-model:", 1
    ), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="registered model id"):
        resolve_config(load_config(path), environ={"BREEZE_REPO": "/models/Breeze-TTS-2"})


def test_unknown_load_param_is_rejected(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(EXAMPLE.read_text(encoding="utf-8").replace(
        "qwen3_tts_device: cpu", "bogus: cpu", 1
    ), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="Unknown load param"):
        resolve_config(load_config(path), environ={"BREEZE_REPO": "/models/Breeze-TTS-2"})


def test_missing_env_reference_is_rejected(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(EXAMPLE.read_text(encoding="utf-8").replace(
        "BREEZE_REPO", "UNSET_MODEL_REPO", 1
    ), encoding="utf-8")
    with pytest.raises(ConfigurationError):
        resolve_config(load_config(path), environ={})


def test_models_section_rejects_unknown_key(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(EXAMPLE.read_text(encoding="utf-8").replace(
        "repo_id: /models/qwen3-tts", "unexpected: value", 1
    ), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="Unknown field"):
        resolve_config(load_config(path), environ={"BREEZE_REPO": "/models/Breeze-TTS-2"})


def test_deprecated_non_commercial_card_cannot_be_configured(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(EXAMPLE.read_text(encoding="utf-8").replace(
        "minicpm-homologous-qwen3-8b:", "breeze-tts-2:", 1
    ), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="Deprecated non-commercial"):
        resolve_config(load_config(path), environ={"BREEZE_REPO": "/models/Breeze-TTS-2"})
```

创建 `example_configs/models-overrides.yaml`：

```yaml
schema_version: 1
runtime: {}
blocks:
  vad:
    kind: vad
    backend: silero
  stt:
    kind: stt
    backend: qwen3-asr
  llm:
    kind: llm
    backend: chat-completions
    settings:
      responses_api_api_key: "not-needed"
  tts:
    kind: tts
    backend: qwen3
pipelines:
  prod:
    stages: {vad: vad, stt: stt, llm: llm, tts: tts}
    num_pipelines: 1
models:
  qwen3-tts-1.7b-customvoice:
    repo_id: /models/qwen3-tts
    default_load_params:
      qwen3_tts_device: cpu
  minicpm-homologous-qwen3-8b:
    repo_id: {env: BREEZE_REPO}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_model_config_overrides.py -q`
Expected: FAIL — `AttributeError: 'ResolvedPipeline' object has no attribute 'model_cards'`（或 `Unknown field` 来自顶层白名单）。

- [ ] **Step 3: Write minimal implementation**

`config.py` 的 import 行改为：

```python
from dataclasses import MISSING, dataclass, field, fields, replace
```

`TYPE_CHECKING` 块追加：

```python
if TYPE_CHECKING:
    from speech_to_speech.backend_registry import BackendSelection
    from speech_to_speech.model_registry import ModelCard
```

在模块顶层 import 区追加（不触发 handler 导入）：

```python
from speech_to_speech.model_registry import get_model, load_param_types
```

`ResolvedPipeline` 加字段：

```python
@dataclass
class ResolvedPipeline:
    num_pipelines: int
    stages: dict[str, ResolvedStage] = field(repr=False)
    options: dict[str, Any] = field(repr=False)
    model_cards: Mapping[str, ModelCard] = field(default_factory=dict, repr=False)
```

在 `_check_composition()` 之后、`resolve_config()` 之前新增两个函数：

```python
def _validate_models_section(document: ConfigDocument) -> None:
    """Validate the optional top-level models: mapping without reading env values."""
    if "models" not in document.data:
        return
    models = _mapping(document, document.data["models"], ("models",))
    for model_id, overrides in models.items():
        if not _ID.fullmatch(model_id):
            _error(document, ("models",), "Use valid model identifiers.")
        path = ("models", model_id)
        overrides = _mapping(document, overrides, path, {"repo_id", "default_load_params"})
        try:
            card = get_model(model_id)
        except ValueError:
            _error(document, ("models",), "Choose a registered model id.")
        if card.status == "deprecated" and "repo_id" in overrides:
            # Deprecated cards stay queryable, but never point a deployment at their weights.
            _error(document, path, "Deprecated non-commercial weights cannot be configured; use spec section 6.4.")
        params = _mapping(document, overrides.get("default_load_params", {}), (*path, "default_load_params"))
        allowed = load_param_types(model_id)
        unknown = sorted(set(params) - set(allowed))
        if unknown:
            _error(document, (*path, "default_load_params"), "Unknown load param; use config_type fields.")
        for key, value in params.items():
            _value(document, value, allowed[key], (*path, "default_load_params", key), None)
        if "repo_id" in overrides:
            _value(document, overrides["repo_id"], str, (*path, "repo_id"), None)


def _apply_model_overrides(document: ConfigDocument, environment: Mapping[str, str]) -> dict[str, ModelCard]:
    """Return per-pipeline card copies; never mutate the global registry."""
    if "models" not in document.data:
        return {}
    resolved: dict[str, ModelCard] = {}
    for model_id, overrides in document.data["models"].items():
        path = ("models", model_id)
        card = get_model(model_id)
        updates: dict[str, Any] = {}
        if "repo_id" in overrides:
            updates["repo_id"] = _value(document, overrides["repo_id"], str, (*path, "repo_id"), environment)
        if "default_load_params" in overrides:
            allowed = load_param_types(model_id)
            updates["default_load_params"] = {
                key: _value(document, value, allowed[key], (*path, "default_load_params", key), environment)
                for key, value in overrides["default_load_params"].items()
            }
        resolved[model_id] = replace(card, **updates)
    return resolved
```

`validate_config()` 第 374 行的白名单改为：

```python
    data = _mapping(document, document.data, (), {"schema_version", "runtime", "blocks", "pipelines", "models"})
```

并在 `validate_config()` 末尾（`_check_composition(...)` 循环之后，`return` 之前）追加：

```python
    _validate_models_section(document)
```

`resolve_config()` 中 `resolved[name] = ResolvedPipeline(...)` 改为：

```python
        resolved[name] = ResolvedPipeline(
            count, stages, options, _apply_model_overrides(document, environment)
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_model_config_overrides.py -q && pytest tests/test_config.py -q && pytest tests/test_configured_runtime.py -q`
Expected: 全部 PASS（`test_config.py` 33 tests、`test_configured_runtime.py` 33 tests 零回归）。

- [ ] **Step 5: Commit**

```bash
git add src/speech_to_speech/config.py tests/test_model_config_overrides.py example_configs/models-overrides.yaml
git commit -m "feat(model-registry): support per-pipeline YAML model overrides"
```

---

### Task 5: `models list` 只读子命令

**Files:**
- Modify: `src/speech_to_speech/cli.py:25`（`Command`）、`:48-57`（`_command_parser()`）、`:89-117`（`parse_command()`）、`:266-285`（`_dispatch()`）、`:287-336`（`main()`）
- Test: `tests/test_model_config_overrides.py`（追加）

**Interfaces:**
- Consumes: `list_models()`（Task 1）、三张 `*_BACKENDS`（Task 3）。
- Produces: `speech-to-speech models list [--kind stt|llm|tts] [--json]`；`_run_models_command(command_args) -> None`。

- [ ] **Step 1: Write the failing test**

把 `import json`、`import subprocess`、`import sys` 加到 `tests/test_model_config_overrides.py` 的**顶部 import 区**（放在模块末尾会触发 ruff E402），然后在文件末尾追加：

```python
def _models_list(*args):
    result = subprocess.run(
        [sys.executable, "-m", "speech_to_speech.cli", "models", "list", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result


def test_models_list_json_contains_status_counts():
    result = _models_list("--json")
    rows = json.loads(result.stdout)
    cards = [row for row in rows if row["status"] != "unregistered"]
    assert sum(row["status"] == "available" for row in cards) == 3
    assert sum(row["status"] == "planned" for row in cards) == 5
    assert sum(row["status"] == "deprecated" for row in cards) == 1
    assert sum(row["status"] == "unregistered" for row in rows) == 27
    breeze = next(row for row in rows if row["id"] == "breeze-tts-2")
    assert breeze["status"] == "deprecated"
    assert "Research and Non-Commercial" in breeze["license"]
    assert "商用" in result.stderr


def test_models_list_kind_filter():
    rows = json.loads(_models_list("--json", "--kind", "tts").stdout)
    assert all(row["kind"] == "tts" for row in rows if row["status"] != "unregistered")
```

> `python -m speech_to_speech.cli` 需要 `__main__` 入口；仓库 `cli.py` 末尾已有 `if __name__ == "__main__": main()`，可直接使用。

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_model_config_overrides.py -q -k models_list`
Expected: FAIL — 非零退出码 `unknown command 'models'`。

- [ ] **Step 3: Write minimal implementation**

`cli.py` 改动 1 — `Command` 类型：

```python
Command = Literal["serve", "talk", "local", "models"]
```

改动 2 — `_command_parser()` 内追加一行：

```python
    subparsers.add_parser("models", add_help=False, help="List registered model cards.")
```

改动 3 — `parse_command()` 三处：

```python
        parser.error("a command is required: serve, talk, local, or models")
```
```python
    if command_args[0] not in {"serve", "talk", "local", "models"}:
```
```python
    if command not in {"serve", "talk", "local", "models"}:
        parser.error(f"unknown command {command!r}; choose serve, talk, local, or models")
```

改动 4 — 新增 `_run_models_command()`（放在 `_dispatch()` 之前）：

```python
def _run_models_command(command_args: list[str]) -> None:
    import json

    from speech_to_speech.backend_registry import LLM_BACKENDS, STT_BACKENDS, TTS_BACKENDS
    from speech_to_speech.model_registry import list_models

    parser = argparse.ArgumentParser(prog="speech-to-speech models", allow_abbrev=False)
    parser.add_argument("action", choices=("list",))
    parser.add_argument("--kind", choices=("stt", "llm", "tts"), default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(command_args)

    cards = list_models(kind=args.kind)
    rows = [
        {
            "id": card.id,
            "name": card.name,
            "kind": card.kind,
            "version": card.version,
            "provider": card.provider,
            "backend": card.backend_name,
            "status": card.status,
            "weight_format": card.weight_format,
            "min_vram_gb": card.min_vram_gb,
            "license": card.license,
        }
        for card in cards
    ]
    for card in cards:
        if card.status == "deprecated":
            print(
                f"Warning: {card.id} is deprecated: {card.license}. 商用场景禁止自托管；"
                "见 docs/superpowers/specs/2026-11-10-s2s-model-registry-design.md §6.4 路径 L / R。",
                file=sys.stderr,
            )

    known = {card.backend_name for card in list_models()}
    registries = (("stt", STT_BACKENDS), ("llm", LLM_BACKENDS), ("tts", TTS_BACKENDS))
    for kind, registry in registries:
        if args.kind is not None and args.kind != kind:
            continue
        for name in sorted(registry):
            if name in known:
                continue
            rows.append(
                {
                    "id": name,
                    "name": name,
                    "kind": kind,
                    "version": None,
                    "provider": None,
                    "backend": name,
                    "status": "unregistered",
                    "weight_format": None,
                    "min_vram_gb": None,
                    "license": None,
                }
            )

    if args.as_json:
        print(json.dumps(rows, ensure_ascii=False))
        return
    print("ID\tKIND\tVERSION\tBACKEND\tSTATUS\tVRAM\tLICENSE")
    for row in rows:
        print(
            f"{row['id']}\t{row['kind']}\t{row['version'] or '-'}\t{row['backend']}\t"
            f"{row['status']}\t{row['min_vram_gb'] if row['min_vram_gb'] is not None else '-'}\t"
            f"{row['license'] or '-'}"
        )
```

改动 5 — `_dispatch()` 开头追加（在 `-f/--file` 检测之前）：

```python
    if command == "models":
        _run_models_command(command_args)
        return
```

改动 6 — `main()` 现有的 `argv = list(sys.argv[1:])` 之后、`parse_console_arguments(argv)` 之前插入提前分流（console 参数解析器不应看到 `--json`）：

```python
    if argv and argv[0] == "models":
        _run_models_command(argv[1:])
        return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_model_config_overrides.py -q && pytest tests/test_cli_defaults.py -q`
Expected: 全部 PASS；`speech-to-speech models list --json` 输出 3 available / 5 planned / 1 deprecated / 27 unregistered。

- [ ] **Step 5: Commit**

```bash
git add src/speech_to_speech/cli.py tests/test_model_config_overrides.py
git commit -m "feat(model-registry): add models list command"
```

---

### Task 6: 接入规范文档

**Files:**
- Create: `docs/model-integration-guide-CN.md`

**Interfaces:**
- Consumes: Task 1–5 的全部公开 API 名称。
- Produces: 9 节接入规范；`resolve_model()` 的 `ModelNotAvailableError` 消息指向其 §3。

- [ ] **Step 1: Write the failing test**

在 `tests/test_model_config_overrides.py` 末尾追加：

```python
def test_integration_guide_has_all_nine_sections():
    text = (
        Path(__file__).resolve().parents[1] / "docs" / "model-integration-guide-CN.md"
    ).read_text(encoding="utf-8")
    assert "## 1." in text and "## 9." in text
    for keyword in (
        "ModelCard",
        "BackendSpec",
        "BaseHandler",
        "16 kHz",
        "512 samples",
        "AUDIO_RESPONSE_DONE",
        "ModelWeightsMissingError",
        "ModelLicenseError",
        "路径 L",
        "路径 R",
        "ruff check",
    ):
        assert keyword in text, keyword
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_model_config_overrides.py -q -k integration_guide`
Expected: FAIL — `FileNotFoundError`。

- [ ] **Step 3: Write minimal implementation**

创建 `docs/model-integration-guide-CN.md`，包含以下 9 节（每节写入实际内容，不留占位）：

1. **三层扩展点**：`ModelCard` = 元信息（名称/类型/版本/repo/显存/许可/状态），`BackendSpec` = 后端构造（handler factory + config_type + capabilities），`BaseHandler` = 推理契约。新增一个模型的最小改动 = 一个参数 dataclass + 一个 Handler + 一条带 `models` 的 `BackendSpec`；只加元信息时只写 card。
2. **最小改动清单**：列出 `src/speech_to_speech/{STT,TTS,LLM}/<name>_handler.py`、`arguments_classes/<name>_arguments.py` 中字段须与 `config_prefix` 对齐、`backend_registry.py` 顶部 import 与 `*_BACKENDS` 追加 `BackendSpec`；条件项 `pyproject.toml` optional extra、`config.py:_PATH_FIELDS`、`docs/parameter-catalog.yaml`、`config/prod.yaml`、compose。明确 `module_arguments.py` choices、`s2s_pipeline.py` 参数类拼装、`config.py` 校验为**自动派生，禁止手改**。
3. **ModelCard 填写规范**：字段表（复述 Task 1 的 13 个字段与类型）、`status` 状态机 `planned → available → deprecated`、id 小写连字符且全局唯一、`min_vram_gb` 单一基准数值、未核实字段一律 `None` 并写进 `notes`、同源组件必须标注「非品牌独立模型」。`resolve_model()` 对 `planned` 抛 `ModelNotAvailableError`、对 `deprecated` 返回 card 并打印许可告警。
4. **Handler 契约**：`setup() / process() -> Iterator / cleanup()`；STT 输入 16 kHz float32 `VADAudio.audio`；TTS 输出 16 kHz int16 PCM（小端 `<i2`）/ 512 samples 块 + `AUDIO_RESPONSE_DONE`；`should_listen` 仅在 `EndOfResponse` 后恢复；`CancelScope` / `SpeculativeTurnTracker` 丢弃陈旧轮；语言码与 `speaker_attribution` 透传。商用路径专项：路径 L 核对 CosyVoice2 输出采样率后重采样；路径 R 处理 BreezeBlue 自有协议（非 OpenAI 兼容）、mp3/wav 解码、24 kHz/48 kHz → 16 kHz 重采样、网络超时与打断。Breeze 本地三模式 / vocal events / `--revision` 仅研究用途参考。
5. **错误约定**：`ModelWeightsMissingError`（含 `repo_id`、必备子目录、下载/安装命令）、`ModelLicenseError`（商用场景选中 `deprecated` 自托管 card 时抛，禁止静默回退）、远程 API 的 `401` / `429` / `Retry-After` 与超时、`required_extra` 用法。许可告警必须出现在部署文档与 `models list` 输出。
6. **显存与资源申报**：`min_vram_gb` 为单一基准数值；与管线 4.6 GB（4633 MiB）实测底座的叠加规则、并发公式 `floor(可用显存GB × 0.85 ÷ 4.6)`；Breeze 的 7.7 / 14.4 GiB 与 12.3 / 19 GB 叠加值**仅研究用途参考，不进入商用预算**；路径 L 用 CosyVoice2 实测值，路径 R 本地显存 0。
7. **一致性测试模板**：card↔参数类默认值一致、音频契约（采样率/dtype/块大小/哨兵、含 24 kHz→16 kHz 重采样正确性）、权重缺失报错、许可闸门报错、registry 延迟导入不被破坏；给出 `pytest tests/test_model_registry.py -q` 作为最小回归命令。
8. **Spec B 模型示例**：路径 L 的 CosyVoice2、Whisper-medium、MiniCPM 同源 Qwen3-8B、可选 MiniCPM-2B/4B 的 `BackendSpec` 草稿与权重下载命令；路径 R 的 `breeze-tts-2-hosted`（`weight_format="remote"`，`https://api.breeze.blue/v1`、`xi-api-key`、Realtime WebSocket TTS、`wav_24000`/`pcm`）；`breeze-tts-2` 本地 card 只作 `deprecated` 反例，不给下载命令。
9. **验收清单**：`ruff check src/ tests/`、`ruff format --check src/ tests/`、`mypy src/`、`pytest tests/ -x -q`；兼容性红线（31 条 `BackendSpec` 构造逐字不改、三个 CLI choices 与默认值不变、`config/prod.yaml` 与 9 个 compose 不变）；`models list` 输出 3 available / 5 planned / 1 deprecated / 27 unregistered。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_model_config_overrides.py -q -k integration_guide`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add docs/model-integration-guide-CN.md tests/test_model_config_overrides.py
git commit -m "docs(model-registry): add model integration guide"
```

---

### Task 7: 全量回归与验收

**Files:** 无新增；只运行命令并记录输出。

**Interfaces:**
- Consumes: Task 1–6 的全部交付。
- Produces: §8.2/§8.3 验收结论。

- [ ] **Step 1: 静态检查**

Run:
```bash
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/
```
Expected: 全部 exit 0。若 `ruff format --check` 报新文件格式问题，只对本计划新增/修改的 Python 文件运行 `ruff format <files>` 后重新检查，不要格式化无关文件。

- [ ] **Step 2: 全量测试**

Run: `pytest tests/ -x -q`
Expected: 全绿；至少包含 `test_backend_registry.py`(45)、`test_config.py`(33)、`test_configured_runtime.py`(33) 与新增的两个测试文件。

- [ ] **Step 3: CLI 验收**

Run:
```bash
speech-to-speech models list
speech-to-speech models list --kind tts --json
```
Expected: 表格含 9 张 card + 27 行 `unregistered`；`--json` 可解析；stderr 出现 `breeze-tts-2` 的商用禁用许可告警。

- [ ] **Step 4: 兼容性红线核对**

先用 `git log --oneline -10` 找到本计划首个实现提交的父提交，记为 `<baseline>`，然后运行：

```bash
git diff <baseline> -- src/speech_to_speech/backend_registry.py
git diff <baseline> -- config/prod.yaml docker-compose.yml docker-compose.local.yml docker-compose.thirdparty.yml
```

Expected: 第一条 diff 中只出现三处变化——`BackendSpec` 类体的 `models` 字段、顶部 `ModelCard` import、末尾 `bind_model_cards(...)` 调用；**没有任何 `BackendSpec(...)` 构造被改写**。第二条输出为空。

- [ ] **Step 5: 记录验收结论**

在 `docs/model-integration-guide-CN.md` 第 9 节末尾追加一段「本次验收」：记录上述四条命令的实际输出摘要、新增测试数量、以及「未下载权重 / 未加载真实模型 / 未占用 GPU」的确认。然后提交：

```bash
git add docs/model-integration-guide-CN.md
git commit -m "docs(model-registry): record Spec A acceptance results"
```

---

## Self-Review 结论（写计划时已完成）

**Spec coverage**：§3.1 文件改动清单 → Task 1/2/3/4/5/6；§3.2 字段 → Task 1；§3.3 API（`register/get/list/by_backend/bind/validate/resolve_model`）→ Task 1；§4.2 `models:` 段 → Task 4；§4.3 覆盖作用域 → Task 4；§4.4 只读子命令 → Task 5；§5 错误处理（含 `ModelLicenseError`）→ Task 1 + Task 6 §5；§6.1/6.2 卡片清单 → Task 2；§6.4 商用闸门 → Task 2 card 状态 + Task 6 §5/§8；§7 接入规范 9 节 → Task 6；§8 测试与验收 → Task 1/2/3/4/5/7。**无缺口**。

**Placeholder scan**：无 TBD / TODO / 「类似 Task N」/ 无代码的步骤。Task 6 的文档内容以逐节要点给出，Step 3 明确要求写成实际内容；Task 7 为命令型步骤，不含代码改动。

**Type consistency**：`ModelCard`、`ModelRegistry`、`get_model()`、`resolve_model()`、`load_param_types()`、`bind_model_cards()`、`list_models()`、`ResolvedPipeline.model_cards` 在 Task 1 定义、Task 2–5 使用的名称与签名一致；`_apply_model_overrides(document, environment)` 与 Task 4 的 `resolve_config()` 调用一致；`Command` 在 Task 5 三处同时扩展为四个字面量。
