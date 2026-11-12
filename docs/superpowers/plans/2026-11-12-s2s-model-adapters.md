# Spec B：S2S 模型适配层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 6 张 `planned` ModelCard 变成可调用的模型适配层，并让 `models:` 段的覆盖值真正注入运行时加载参数。

**Architecture:** 沿用 Spec A 的 `BackendSpec` / `ModelCard` 注册框架，只追加 2 条 TTS 后端（`breeze-tts-2`、`cosyvoice2`）与 1 处 `config.py` 注入逻辑；其余 4 张 card 复用既有 `whisper` / `transformers` 后端。Breeze 推理拆成可注入 adapter，权重检查与音频重采样是无第三方依赖的纯函数，全部契约测试用 stub 驱动。

**Tech Stack:** Python 3.10+、pytest、`numpy` / `librosa` / `soxr`（均已在 dependencies）、`dataclasses`、`transformers`；Breeze 官方 `breeze_infer` 与 CosyVoice 官方源码只在构建期提供，运行时不导入。

**Spec:** `docs/superpowers/specs/2026-11-12-s2s-model-adapters-design.md`（执行者须同时读该 spec 与 `docs/model-integration-guide-CN.md`）

## Global Constraints

- 验收口径：**代码就绪 + 契约测试；不下载权重、不触网、不占 GPU、不加载真实模型**。全部测试用 stub/mock 与 `tmp_path`。
- 音频契约：STT 输入 16 kHz float32 `VADAudio`；TTS 输出 **16 kHz int16 little-endian PCM / 512 samples 每块**，结尾恰好一个 `AUDIO_RESPONSE_DONE`。
- **31 条既有 `BackendSpec(...)` 构造逐字不改**；只追加 2 条新 spec；`BackendSpec` 结构不加字段。
- `cli.py`、`config/prod.yaml`、9 个 `docker-compose*.yml`、`example_configs/mac.yaml` **不动**。
- 最终 `models list`：**9 张 `available` / 0 张 `planned` / 27 行 `unregistered`**；`--json` 沿用 Spec A 的 10 字段、不含 `repo_id` 键。
- `default_load_params` 的键必须是 `config_type` 的**真实 dataclass 字段名**：`stt_model_name`、`cosyvoice_tts_model_name`、`breeze_tts_model_name`，而 LLM 是 **`model_name`（无前缀）**。
- **`*_model_name` 一律不加入 `config.py:_PATH_FIELDS`**；只增补纯路径字段 `breeze_tts_ref_audio` / `cosyvoice_tts_prompt_wav`。
- 不引入模型级选择器、不新增环境变量前缀、不新增 CLI flag；`{env: NAME}` 继续可用。
- 无 `models:` 段时行为与改前逐字一致；`blocks.*.settings` 显式值始终优先于 card 默认值。
- 每个 Task 结束跑 `pytest <该任务测试> -q` 并独立 commit；全量 CI：`ruff check src/ tests/`、`ruff format --check src/ tests/`、`mypy src/`、`pytest tests/ -x -q`。

## Review Focus

以下 5 类是 spec 隐含、但最容易在实现时漏测的输入/条件；每条已在其所属 Task 的测试步骤中钉住：

1. **同一 stage 的 `models:` 段同时激活两张指向同一 backend 的 card** → 应抛 `ConfigurationError`，不能随机选一张（Task 7）。
2. **`models:` 段写空 mapping `{}` 激活 card** → card 内置 `default_load_params` 应全部注入，不能被当成「无覆盖」跳过（Task 7）。
3. **部分覆盖 `default_load_params`**（只写一个非模型名字段）→ 内置 `model_name` 不能被整体替换丢弃，否则权重切换静默失效（Task 7）。
4. **24 kHz 输入尾部不足 512 samples 或含超范围浮点** → 补零到整块、不削波不越界、仍只 yield 一个 `AUDIO_RESPONSE_DONE`（Task 1 / Task 4）。
5. **权重目录缺失且官方依赖也未安装** → `ModelWeightsMissingError` 优先、原样冒泡，不被 `required_extra` 的 ImportError 遮蔽，且禁止静默回退（Task 3 / Task 4；Task 6 覆盖互补的 ImportError 包装侧）。

---

## 文件结构

| 文件 | 责任 | 新建/修改 |
|---|---|---|
| `src/speech_to_speech/audio_utils.py` | 24→16 kHz 重采样 + 512 samples 切块的共享纯函数 | 新建 |
| `src/speech_to_speech/TTS/breeze_tts_runtime.py` | `check_breeze_weights()` 纯函数、`BreezeInferenceAdapter` Protocol、`OfficialBreezeAdapter` | 新建 |
| `src/speech_to_speech/TTS/breeze_tts_handler.py` | `BreezeTTSHandler`，接受注入 adapter，产出管线音频契约 | 新建 |
| `src/speech_to_speech/arguments_classes/breeze_tts_arguments.py` | `BreezeTTSHandlerArguments`（`breeze_tts_` 前缀） | 新建 |
| `src/speech_to_speech/TTS/cosyvoice_handler.py` | 修 3 处不一致、改用 `audio_utils.py` | 修改 |
| `src/speech_to_speech/arguments_classes/cosyvoice_tts_arguments.py` | 统一 `fp16`、补 `prompt_wav` | 修改 |
| `src/speech_to_speech/backend_registry.py` | 追加 2 条 spec + 顶部 2 个 import | 修改 |
| `src/speech_to_speech/models/builtin.py` | 6 张 card 翻 `available`、补元信息 | 修改 |
| `src/speech_to_speech/model_registry.py` | 新增 `ModelWeightsMissingError` | 修改 |
| `src/speech_to_speech/config.py` | 注入接线、合并语义、`_PATH_FIELDS` | 修改 |
| `pyproject.toml` | 新增 `breeze` / `cosyvoice` 两个 optional extra | 修改 |
| `tests/test_audio_utils.py` / `test_breeze_tts_runtime.py` / `test_breeze_tts_handler.py` / `test_cosyvoice_registration.py` / `test_model_runtime_wiring.py` / `test_spec_b_cards.py` | 新增契约测试（组织方式按 spec §7 由实施者定） | 新建 |
| `tests/test_model_registry.py` / `tests/test_model_config_overrides.py` | 按新事实更新 6 处状态硬编码断言 | 修改 |
| `docs/model-integration-guide-CN.md` / `docs/superpowers/specs/2026-11-10-s2s-model-registry-design.md` / `docs/parameter-catalog.md` | 接入规范落地、历史漂移修正、新参数登记 | 修改 |

**Scope 说明**：spec 的 6 张 card 与 `config.py` 接线共享同一份注册表与 `validate()` 校验，任一中间态单独拆成 plan 都会让 `bind_model_cards()` 在导入期报错，因此本计划按依赖顺序做成一条可增量验收的链，不做多 plan 拆分。

---

### Task 1: 共享音频工具 `audio_utils.py`

**Files:**
- Create: `src/speech_to_speech/audio_utils.py`
- Test: `tests/test_audio_utils.py`

**Interfaces:**
- Consumes: `numpy`（已在 dependencies）、`librosa` 或 `soxr`（按 spec §7 由实施者定）
- Produces:
  - `resample_pcm_24k_to_16k(pcm: np.ndarray, *, input_dtype: str) -> np.ndarray`（`input_dtype` 取 `"int16"` 或 `"float32"`；返回 `dtype=np.int16`）
  - `iter_pcm_chunks(pcm_i16: np.ndarray, chunk_size: int = 512) -> Iterator[np.ndarray]`（每块恰好 `chunk_size`，尾部补零）

- [ ] **Step 1: 写失败测试** `tests/test_audio_utils.py`
  - `test_int16_24k_to_16k_sample_count_converges_by_two_thirds`：24000 samples 的 int16 输入，断言输出长度 16000、`dtype == np.int16`。
  - `test_float32_input_is_normalized_and_clipped`：`np.array([-2.0, 0.0, 2.0], dtype=np.float32)`，断言输出全在 `int16` 范围内、无 `nan`/`inf`、无静默 wrap。
  - `test_iter_pcm_chunks_pads_tail`：`np.arange(600, dtype=np.int16)`、`chunk_size=512`，断言产出 `[512, 512]` 两块、第二块尾部 424 个零。
  - `test_iter_pcm_chunks_exact_multiple_has_no_extra_block`：1024 samples 断言恰好 2 块。

- [ ] **Step 2: 运行确认失败** `pytest tests/test_audio_utils.py -q` → FAIL（`ModuleNotFoundError: speech_to_speech.audio_utils`）

- [ ] **Step 3: 实现** `src/speech_to_speech/audio_utils.py` 的两个函数。int16 输入先归一到 float32 再重采样，乘 32767 后 `np.clip` 到 int16 范围；float32 输入直接重采样后同样 clip。`iter_pcm_chunks` 用 reshape + `np.pad` 补零。

- [ ] **Step 4: 运行确认通过** `pytest tests/test_audio_utils.py -q` → PASS（4 tests）

- [ ] **Step 5: Commit** `git add src/speech_to_speech/audio_utils.py tests/test_audio_utils.py && git commit -m "feat(tts): add shared 24k-to-16k PCM resampling utilities"`

---

### Task 2: `ModelWeightsMissingError` 异常类型

**Files:**
- Modify: `src/speech_to_speech/model_registry.py:17-26`
- Test: `tests/test_model_registry.py`（追加用例）

**Interfaces:**
- Consumes: `ModelRegistryError(ValueError)`
- Produces: `ModelWeightsMissingError(ModelRegistryError)`，可被 `from speech_to_speech.model_registry import ModelWeightsMissingError` 导入

- [ ] **Step 1: 写失败测试** 在 `tests/test_model_registry.py` 追加：
  - `test_model_weights_missing_error_is_registry_error`：断言 `issubclass(ModelWeightsMissingError, ModelRegistryError)` 且 `issubclass(..., ValueError)`，且**不是** `ImportError`。

- [ ] **Step 2: 运行确认失败** `pytest tests/test_model_registry.py::test_model_weights_missing_error_is_registry_error -q` → FAIL（import error）

- [ ] **Step 3: 实现** 在 `model_registry.py` 的 `ModelLicenseError` 之后定义 `ModelWeightsMissingError(ModelRegistryError)`，docstring 写明「权重目录缺失或缺少必备 checkpoint 组件」。

- [ ] **Step 4: 运行确认通过** `pytest tests/test_model_registry.py -q` → PASS

- [ ] **Step 5: Commit** `git add src/speech_to_speech/model_registry.py tests/test_model_registry.py && git commit -m "feat(model-registry): add ModelWeightsMissingError"`

---

### Task 3: Breeze 权重检查纯函数与推理 adapter

**Files:**
- Create: `src/speech_to_speech/TTS/breeze_tts_runtime.py`
- Test: `tests/test_breeze_tts_runtime.py`

**Interfaces:**
- Consumes: `ModelWeightsMissingError`（Task 2）；标准库 + `numpy` 仅允许出现在模块顶层
- Produces:
  - `check_breeze_weights(repo_id: str, revision: str | None = None, *, cache_dir: Path | None = None) -> None`（无第三方依赖）
  - `class BreezeInferenceAdapter(Protocol)`：`load(*, repo_id, revision, device, fast_all) -> None`、`synthesize(*, text, ref_audio, ref_text, instruction, cfg_scale, seed) -> np.ndarray`、`sample_rate -> int`、`close() -> None`
  - `class OfficialBreezeAdapter`：实现上述 Protocol，`sample_rate == 24000`

- [ ] **Step 1: 写失败测试** `tests/test_breeze_tts_runtime.py`
  - `test_check_weights_raises_with_repo_and_download_command(tmp_path)`：`tmp_path / "missing"` 不存在，断言抛 `ModelWeightsMissingError`，消息含 repo id、`audio_tokenizer`、`huggingface-cli download` 字样。
  - `test_check_weights_accepts_complete_checkpoint(tmp_path)`：造出含 `audio_tokenizer/` 子目录与一个 `*.safetensors` 的目录，断言返回 `None`。
  - `test_runtime_module_imports_without_breeze_infer`：导入模块后断言 `sys.modules` 中无 `breeze_infer`。
  - `test_official_adapter_load_checks_weights_before_import`（用 `monkeypatch` 让 `import_module` 抛 AssertionError 记录被调用）：`load(repo_id=<缺失目录>)` 断言 `ModelWeightsMissingError` 且 import 从未发生 —— 钉住**权重先于 import** 的顺序（Review Focus #5 第一半）。
  - `test_official_adapter_sample_rate_is_24000`：`OfficialBreezeAdapter().sample_rate == 24000`（不调用 `load()`）。

- [ ] **Step 2: 运行确认失败** `pytest tests/test_breeze_tts_runtime.py -q` → FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现** `breeze_tts_runtime.py`
  - 顶层只 import 标准库（`pathlib`、`threading`、`typing`）与 `numpy`；**不得** import `breeze_infer`。
  - `check_breeze_weights()`：解析 `cache_dir` 或本地路径，检查目录存在与 `audio_tokenizer/` 必备组件，失败抛 `ModelWeightsMissingError`，消息含 repo id、必备子目录、下载/安装命令。
  - `OfficialBreezeAdapter.load()` 顺序固定：`check_breeze_weights()` → 方法体内 `from breeze_infer... import ...` → `load_runtime()`；导入失败抛 `ImportError`（由 `create_backend_handler()` 包装成 `pip install "speech-to-speech[breeze]"` 提示）。
  - `synthesize()` 内 `prepare_inputs()` + `model.generate(output_audio=True, audio_tokenizer=..., repetition_penalty=1.1, no_repeat_ngram_size=0, encoder_no_repeat_ngram_size=0)`；单推理槽用 `threading.Lock` 互斥。
  - 官方包的具体导入路径与 `prepare_inputs()` 参数组装按 spec §7 由实施者依官方 README 定。

- [ ] **Step 4: 运行确认通过** `pytest tests/test_breeze_tts_runtime.py -q` → PASS（5 tests，全程未安装 `breeze_infer`）

- [ ] **Step 5: Commit** `git add src/speech_to_speech/TTS/breeze_tts_runtime.py tests/test_breeze_tts_runtime.py && git commit -m "feat(tts): add Breeze runtime adapter with standalone weight check"`

---

### Task 4: `BreezeTTSHandlerArguments` 与 `BreezeTTSHandler`

**Files:**
- Create: `src/speech_to_speech/arguments_classes/breeze_tts_arguments.py`
- Create: `src/speech_to_speech/TTS/breeze_tts_handler.py`
- Test: `tests/test_breeze_tts_handler.py`

**Interfaces:**
- Consumes: `audio_utils.resample_pcm_24k_to_16k` / `iter_pcm_chunks`（Task 1）、`BreezeInferenceAdapter` / `OfficialBreezeAdapter`（Task 3）、`BaseHandler[TTSIn, TTSOut]`、`AUDIO_RESPONSE_DONE`、`EndOfResponse`、`CancelScope`、`SpeculativeTurnTracker`
- Produces:
  - `@dataclass class BreezeTTSHandlerArguments`，字段 `breeze_tts_model_name: str = "BreezeBlue/Breeze-TTS-2"`、`breeze_tts_revision`、`breeze_tts_device="cuda"`、`breeze_tts_fast_all=False`、`breeze_tts_ref_audio`、`breeze_tts_ref_text`、`breeze_tts_instruction=""`、`breeze_tts_cfg_scale=4.0`、`breeze_tts_seed`、`breeze_tts_chunk_size=512`、`breeze_tts_gen_*`（由 `normalize_dataclass_config()` 合并进 `gen_kwargs`）
  - `class BreezeTTSHandler(BaseHandler[TTSIn, TTSOut])`，`setup(should_listen, ..., adapter: BreezeInferenceAdapter | None = None, ...)`；`process(tts_input: TTSIn) -> Iterator[TTSOut]`

- [ ] **Step 1: 写失败测试** `tests/test_breeze_tts_handler.py`（用 `BaseHandler.__new__` 或直接构造，风格参照 `tests/test_phonon_tts_handler.py:41-55`）
  - `test_process_yields_16k_int16_512_sample_chunks`：注入 stub adapter 返回 24000 samples 的 int16 正弦，断言所有音频块 `dtype == np.int16`、每块 512 samples、总数按 2/3 收敛。
  - `test_process_yields_exactly_one_done_sentinel`：`TTSInput(text="你好")` 后跟 `EndOfResponse()`，断言 `AUDIO_RESPONSE_DONE` 恰好 1 个。
  - `test_tail_is_zero_padded` —— Review Focus #4 的 handler 侧：stub 返回 600 samples，断言最后一块长度 512 且尾部补零、无额外空块。
  - `test_stub_adapter_receives_three_mode_params`：断言 `ref_audio` / `ref_text` / `instruction` / `cfg_scale` 原样透传到 `synthesize()`。
  - `test_weights_missing_error_propagates_without_fallback`：stub adapter 的 `load()` 抛 `ModelWeightsMissingError`，断言异常原样冒泡、且未调用其它 adapter 的 `synthesize()` —— Review Focus #5 第二半。
  - `test_stale_turn_is_dropped`：用 `SpeculativeTurnTracker` + `tests.turns.reopen` 构造陈旧 `TTSInput`，断言不产出音频块。
  - `test_interruption_stops_chunk_yield`：用 `CancelScope` 在生成中标记 stale，断言提前停止。
  - `test_arguments_dataclass_defaults`：断言 `BreezeTTSHandlerArguments().breeze_tts_model_name == "BreezeBlue/Breeze-TTS-2"`、`breeze_tts_chunk_size == 512`。

- [ ] **Step 2: 运行确认失败** `pytest tests/test_breeze_tts_handler.py -q` → FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现**
  - `breeze_tts_arguments.py`：按 Interfaces 字段定义 dataclass，字段名带 `breeze_tts_` 前缀，`gen_*` 字段用 `metadata` help 标明会合并进 `gen_kwargs`。
  - `breeze_tts_handler.py`：`setup()` 中 `adapter = adapter or OfficialBreezeAdapter()`，调用 `adapter.load(repo_id=breeze_tts_model_name, revision=..., device=..., fast_all=...)`；保存 `should_listen` / `cancel_scope` / `speculative_turns` / `chunk_size`。
  - `process()` 结构照 `TTS/cosyvoice_handler.py:119-150`：`EndOfResponse` 分支做陈旧轮判断并 yield 一次 `AUDIO_RESPONSE_DONE`；普通 `TTSInput` 调 `adapter.synthesize()` → `resample_pcm_24k_to_16k(..., input_dtype="int16")` → `iter_pcm_chunks(...)`；打断用 `CancelScope.is_stale()`。
  - `cleanup()` 调 `adapter.close()`；`on_session_end()` 记录 debug 日志。

- [ ] **Step 4: 运行确认通过** `pytest tests/test_breeze_tts_handler.py tests/test_audio_utils.py -q` → PASS

- [ ] **Step 5: Commit** `git add src/speech_to_speech/arguments_classes/breeze_tts_arguments.py src/speech_to_speech/TTS/breeze_tts_handler.py tests/test_breeze_tts_handler.py && git commit -m "feat(tts): add Breeze TTS 2 handler and arguments"`

---

### Task 5: CosyVoice2 三处不一致修复与共享工具接入

**Files:**
- Modify: `src/speech_to_speech/arguments_classes/cosyvoice_tts_arguments.py:5-44`
- Modify: `src/speech_to_speech/TTS/cosyvoice_handler.py:21-23, 47-64, 170-186`
- Test: `tests/test_cosyvoice_tts_handler.py`

**Interfaces:**
- Consumes: `audio_utils.resample_pcm_24k_to_16k` / `iter_pcm_chunks`（Task 1）
- Produces: `CosyVoiceTTSHandlerArguments`（新增字段 `cosyvoice_tts_prompt_wav: str | None = None`、`cosyvoice_tts_fp16: bool = False`），`CosyVoiceTTSHandler` 保持 `setup/process/cleanup` 签名不变

- [ ] **Step 1: 写失败测试** `tests/test_cosyvoice_tts_handler.py`
  - `test_arguments_fp16_default_matches_handler_signature`：用 `inspect.signature(CosyVoiceTTSHandler.setup)` 断言 `fp16` 默认值 `False`，且 dataclass 的 `cosyvoice_tts_fp16` 默认值也是 `False`。
  - `test_arguments_has_prompt_wav_field`：断言 `cosyvoice_tts_prompt_wav` 存在、默认 `None`，且 `normalize_dataclass_config(..., prefix="cosyvoice_tts")` 产出的键是 `prompt_wav`。
  - `test_stream_uses_shared_resampler`：`monkeypatch` `audio_utils.resample_pcm_24k_to_16k` 记录调用；用 `BaseHandler.__new__` 构造最小 handler、喂 float32 数组进 `_stream()`，断言调用发生且输出 `dtype == np.int16`、块长 512。
  - `test_tail_chunk_is_padded`：600 samples 输入断言末块补零 —— Review Focus #4 的 CosyVoice 侧。
  - `test_stream_does_not_import_librosa_directly`：断言 `cosyvoice_handler.py` 源码中不再出现 `librosa.resample`（改用共享工具）。

- [ ] **Step 2: 运行确认失败** `pytest tests/test_cosyvoice_tts_handler.py -q` → FAIL（`cosyvoice_tts_prompt_wav` 不存在、`fp16` 默认值不一致）

- [ ] **Step 3: 实现**
  - 参数类：把 `cosyvoice_tts_fp16` 默认改为 `False`（与 handler 一致）、新增 `cosyvoice_tts_prompt_wav: str | None = None` 并写 help 文案。
  - handler：`_stream()` 中的 `librosa.resample(...)` + 手工 `chunk_size` 切块替换为 `resample_pcm_24k_to_16k(audio, input_dtype="float32")` + `iter_pcm_chunks(..., self.chunk_size)`，保留 `leftover` 合并与 `CancelScope.is_stale()` 打断逻辑；移除顶层 `import librosa` 与 `COSYVOICE_SR` / `PIPELINE_SR` 常量（或仅保留供日志用，按 spec §7 定）。
  - `setup()` 的 `fp16` 默认保持 `False`；`prompt_wav` 参数已存在，无需改签名。

- [ ] **Step 4: 运行确认通过** `pytest tests/test_cosyvoice_tts_handler.py tests/test_audio_utils.py -q` → PASS

- [ ] **Step 5: Commit** `git add src/speech_to_speech/arguments_classes/cosyvoice_tts_arguments.py src/speech_to_speech/TTS/cosyvoice_handler.py tests/test_cosyvoice_tts_handler.py && git commit -m "fix(tts): align CosyVoice arguments and reuse shared PCM utilities"`

---

### Task 6: 注册 2 条 BackendSpec、新增 optional extras

**Files:**
- Modify: `src/speech_to_speech/backend_registry.py:12-56`（顶部 import）、`TTS_BACKENDS` 列表末尾（当前 696-709）
- Modify: `pyproject.toml:68-119`
- Test: `tests/test_cosyvoice_registration.py`

**Interfaces:**
- Consumes: `BreezeTTSHandlerArguments`（Task 4）、`CosyVoiceTTSHandlerArguments`（Task 5）、`_simple_handler_factory`、`BackendSpec`
- Produces: `TTS_BACKENDS["breeze-tts-2"]`（`config_prefix="breeze_tts"`、`required_extra="breeze"`）、`TTS_BACKENDS["cosyvoice2"]`（`config_prefix="cosyvoice_tts"`、`required_extra="cosyvoice"`）；两条 spec 的 `models == ()`

- [ ] **Step 1: 写失败测试** `tests/test_cosyvoice_registration.py`
  - `test_two_new_tts_backends_registered`：断言 `set(TTS_BACKENDS) >= {"breeze-tts-2", "cosyvoice2"}`、两条 `kind == "tts"`、`config_prefix` / `required_extra` 如上、`models == ()`。
  - `test_backend_count_is_33`：断言 `len(STT_BACKENDS) + len(LLM_BACKENDS) + len(TTS_BACKENDS) == 33`。
  - `test_existing_31_spec_constructions_unchanged`：断言既有 31 条的 `(name, kind, config_type, config_prefix, required_extra)` 组合与硬编码期望一致（守住兼容红线）。
  - `test_optional_extras_exist_in_pyproject`：读 `pyproject.toml`，断言 `[project.optional-dependencies]` 含 `breeze` 与 `cosyvoice` 两组，且组内**不含** `git+` / `flash-attn` 等需运行时编译或联网 GitHub 的项。
  - `test_new_handler_modules_are_lazy`：调用 `tests/test_backend_registry.py` 的 `assert_no_handler_modules("speech_to_speech.backend_registry")`，断言 import 后 `sys.modules` 无 `breeze_tts_handler` / `cosyvoice_handler`。
  - `test_create_backend_handler_wraps_import_error_for_breeze`：用 `monkeypatch` 让 `_load_handler` 抛 `ImportError`，调用 `create_backend_handler()`，断言消息含 `pip install "speech-to-speech[breeze]"`。

- [ ] **Step 2: 运行确认失败** `pytest tests/test_cosyvoice_registration.py -q` → FAIL（后端未注册）

- [ ] **Step 3: 实现**
  - `backend_registry.py` 顶部追加两条 import（`BreezeTTSHandlerArguments`、`CosyVoiceTTSHandlerArguments`），保持字母序（ruff I001）。
  - `TTS_BACKENDS` 末尾追加两条 `BackendSpec`：工厂均为 `_simple_handler_factory(..., setup_should_listen=True, context_kwargs=True)`，模块/类名分别为 `speech_to_speech.TTS.breeze_tts_handler` / `BreezeTTSHandler` 与 `speech_to_speech.TTS.cosyvoice_handler` / `CosyVoiceTTSHandler`。**不填 `models`**（builtin 已有同 id card，双写会触发 `ModelRegistryError`）。
  - `pyproject.toml` 追加 `breeze` / `cosyvoice` 两组；具体包清单按 spec §7 由实施者定，约束：纯 PyPI 可安装、不含需运行时编译或联网 GitHub 的项，构建期安装步骤写进接入规范。
  - **注意**：此时 6 张 builtin card 仍是 `planned`，`ModelRegistry.validate()` 对未注册 backend 的 `planned` card 会 `continue`，导入期不会报错；`breeze-tts-2` / `cosyvoice2` 注册后也不会报错。

- [ ] **Step 4: 运行确认通过** `pytest tests/test_cosyvoice_registration.py tests/test_backend_registry.py -q` → PASS

- [ ] **Step 5: Commit** `git add src/speech_to_speech/backend_registry.py pyproject.toml tests/test_cosyvoice_registration.py && git commit -m "feat(registry): register Breeze TTS 2 and CosyVoice2 backends"`

---

### Task 7: `config.py` 运行时接线、合并语义与路径字段

**Files:**
- Modify: `src/speech_to_speech/config.py:49-61`（`_PATH_FIELDS`）、`405-423`（`_apply_model_overrides`）、`545-594`（`resolve_config`）
- Test: `tests/test_model_runtime_wiring.py`

**Interfaces:**
- Consumes: `_settings()` / `_mapping()` / `_error()` / `ConfigurationError` / `_apply_model_overrides()`（现有）、`BackendSelection`（`backend_registry.py`）
- Produces: `ResolvedStage.selection.config` 中被 `models:` 段激活的 card 的 `default_load_params` 值；`ResolvedPipeline.model_cards` 语义不变

- [ ] **Step 1: 写失败测试** `tests/test_model_runtime_wiring.py`（用 `EXAMPLE = example_configs/models-overrides.yaml` 与 `tmp_path` 造 YAML，风格参照 `tests/test_model_config_overrides.py:14-53`）。**凡是把 `blocks.llm.backend` 改为 `transformers` 的用例，必须同时删除 `responses_api_api_key` 这个 `chat-completions` 专用 setting**，否则 `_settings()` 的 `_mapping()` 会因 unknown key 报错、掩盖真正要测的行为。同理 `blocks.tts.backend: breeze-tts-2` 时不得保留 `qwen3_tts_*` settings。
  - `test_explicit_card_defaults_are_injected`：直接用 `example_configs/models-overrides.yaml`（已含 `models: {qwen3-tts-1.7b-customvoice: {default_load_params: {qwen3_tts_device: cpu}}}` 且 `blocks.tts.backend: qwen3`），断言 `pipeline.stages["tts"].selection.config["device"] == "cpu"`。注意 `spec.normalize()` 会剥掉 `qwen3_tts_` 前缀，config 键是 `device`。此测试只依赖现有 3 张 `available` card，不依赖 Task 8。
  - `test_settings_explicit_value_wins`：在上例 YAML 的 `blocks.tts.settings` 显式写 `qwen3_tts_device: cuda`，断言 `selection.config["device"] == "cuda"`。
  - `test_two_cards_for_same_backend_raises` —— Review Focus #1：`models:` 同时写 `minicpm-2b: {}` 与 `minicpm-4b: {}` 且 `blocks.llm.backend: transformers`，断言抛 `ConfigurationError` 且消息含 "Only one model card"。
  - `test_empty_mapping_activates_builtin_defaults` —— Review Focus #2：用 `monkeypatch` 给 `mr.MODEL_REGISTRY` 注册一张临时 `available` card（`backend_name="transformers"`、`default_load_params={"model_name": "X"}`），YAML 写 `models: {<该 id>: {}}`，断言 `selection.config["model_name"] == "X"`。不依赖 Task 8。
  - `test_partial_override_preserves_builtin_model_name` —— Review Focus #3：同一临时 card 内置 `{"model_name": "X", "llm_device": "auto"}`，YAML 只覆盖 `llm_device: cpu`，断言副本 `default_load_params` 仍含 `model_name: "X"`、且 `selection.config["model_name"] == "X"`、`selection.config["device"] == "cpu"`。
  - `test_no_models_section_is_identical_to_baseline`：无 `models:` 段时断言 `selection.config` 与 `sources` 与改前快照一致、`model_cards == {}`。
  - `test_two_pipelines_do_not_leak`：`pipelines` 下两个命名 pipeline，断言各自的 `model_cards` 是不同对象、注入互不影响。
  - `test_repo_id_override_does_not_rewrite_settings`：沿用 `models-overrides.yaml` 里 `minicpm-homologous-qwen3-8b: {repo_id: {env: BREEZE_REPO}}`，把 `blocks.llm.backend` 改为 `transformers`，断言 `selection.config["model_name"]` 仍是 `LanguageModelHandlerArguments` 默认值 `Qwen/Qwen3.5-4B`（`repo_id` 不改写 settings）。
  - `test_hf_repo_id_is_not_treated_as_relative_path`：YAML `blocks.llm.backend: transformers` + `models: {minicpm-homologous-qwen3-8b: {default_load_params: {model_name: "Qwen/Qwen3-8B"}}}`，断言 `selection.config["model_name"] == "Qwen/Qwen3-8B"`（不带 `document.path.parent` 前缀）。
  - `test_ref_audio_relative_path_is_expanded`：YAML `blocks.tts.backend: breeze-tts-2` + `blocks.tts.settings.breeze_tts_ref_audio: assets/ref.wav`，断言 `stage.settings["breeze_tts_ref_audio"]` 以 `tmp_path` 开头（绝对路径）。
  - `test_sources_semantics_unchanged`：注入键的 `sources[(*path, key)]` 仍为 `"default"`，显式键仍为 `"file"`。

- [ ] **Step 2: 运行确认失败** `pytest tests/test_model_runtime_wiring.py -q` → FAIL（注入未实现；`test_partial_override...` 因整体替换而失败）

- [ ] **Step 3: 实现** `config.py` 三处小改
  - `_apply_model_overrides()`：`updates["default_load_params"] = {**card.default_load_params, **resolved_overrides}`，再 `replace(card, **updates)`；`repo_id` 更新逻辑不变。
  - `resolve_config()`：在 `for name in selected:` 循环内、`stages` 循环之前计算一次 `model_cards = _apply_model_overrides(document, environment)`；在 `_settings()` 返回后、`BackendSelection(...)` 之前，对 `kind != "vad"` 按 spec §6.2 伪代码筛 `card.backend_name == block["backend"]`：>1 张 `_error(document, path, "Only one model card may target a backend per stage.")`；1 张时按 `explicit_keys = set(_mapping(document, raw_settings, path, set(fields(config_type))))` 逐键注入（显式键不动）；`ResolvedPipeline(..., model_cards)` 复用同一份字典。
  - `_PATH_FIELDS` 只增补 `breeze_tts_ref_audio`、`cosyvoice_tts_prompt_wav`；**不得**加入任何 `*_model_name`。

- [ ] **Step 4: 运行确认通过** `pytest tests/test_model_runtime_wiring.py tests/test_model_config_overrides.py tests/test_config.py -q` → PASS

- [ ] **Step 5: Commit** `git add src/speech_to_speech/config.py tests/test_model_runtime_wiring.py && git commit -m "feat(config): inject active model card defaults into backend selections"`

---

### Task 8: builtin ModelCard 更新与既有断言同步

**Files:**
- Modify: `src/speech_to_speech/models/builtin.py:52-141`
- Modify: `tests/test_model_registry.py:153-166, 172-185, 194, 201-202`
- Modify: `tests/test_model_config_overrides.py:129-136`
- Test: `tests/test_spec_b_cards.py`

**Interfaces:**
- Consumes: `ModelCard`（字段见 `model_registry.py:29-43`）、Task 6 注册的两个 backend、`load_param_types()`
- Produces: 9 张 `available` card；`models list --json` 输出 9 `available` / 0 `planned` / 27 `unregistered`

- [ ] **Step 1: 写失败测试** `tests/test_spec_b_cards.py`
  - `test_all_nine_cards_are_available`：`len(builtin_model_cards()) == 9` 且 `all(c.status == "available")`。
  - `test_card_repo_ids_and_licenses`：断言 `breeze-tts-2` 的 `license` 含 "Research and Non-Commercial"、`cosyvoice2.license == "apache-2.0"`、`minicpm-2b.repo_id == "openbmb/MiniCPM-2B-dpo-bf16"`、`minicpm-4b.repo_id == "openbmb/MiniCPM3-4B"`、`minicpm-4b.min_vram_gb is None`。
  - `test_default_load_params_keys_are_real_dataclass_fields`：对 6 张 card 逐个断言 `set(card.default_load_params) <= set(load_param_types(card.id))`；特别断言 LLM 三张用的键是 `model_name`（不是 `llm_model_name`）、whisper 用 `stt_model_name`。
  - `test_validate_passes_with_all_available`：`validate_models()` 不抛异常。
  - `test_models_list_json_counts`：用 `tests/test_model_config_overrides.py:_models_list("--json")`，断言 `available == 9`、`planned == 0`、`deprecated == 0`、`unregistered == 27`，且每行键集合恰为 Spec A 的 10 字段（**不含 `repo_id`**）。
  - `test_notes_record_license_and_naming_exceptions`：断言 CosyVoice2 notes 含双源说明、MiniCPM 两张 notes 含商用授权与「非品牌独立模型」、`minicpm-4b` notes 含 `MiniCPM3-4B`。
  - `test_no_handler_modules_on_import`：`assert_no_handler_modules("speech_to_speech.models.builtin")`。

- [ ] **Step 2: 运行确认失败** `pytest tests/test_spec_b_cards.py -q` → FAIL（`status == "planned"`）

- [ ] **Step 3: 实现**
  - `builtin.py`：6 张 card `status="available"`；按 spec §6.5 表格填 `default_load_params` / `repo_id` / `license` / `min_vram_gb`；notes 补 Breeze 商业授权来源、CosyVoice2 学术免责声明与 HF/ModelScope 双源、MiniCPM 同源与商用单独授权、`minicpm-4b` 官方命名差异、所有 `None` 字段标注「未实测/未核实」。**现有 3 张 `available` card 逐字不改。**
  - `tests/test_model_registry.py`：`available` 列表改为 9 张 id、`planned == 0`、`breeze.status == "available"`；后端总数 `31 → 33`；全局 `get_model("breeze-tts-2").status == "available"`。`min_vram_gb == 7.7` 与许可/notes 断言保留。
  - **同一测试的假注册表必须换用真实 `config_type`**：`test_builtin_cards_bind_without_error()`（`tests/test_model_registry.py:172-185`）当前用 `FakeSpec(kind)`，默认 `config_type=FakeArgs`（只有 `model_name` / `device`）。6 张 card 翻 `available` 后 `ModelRegistry.validate()` 会校验 `default_load_params` 键名，而 `stt_model_name` / `cosyvoice_tts_model_name` / `breeze_tts_model_name` 不在 `FakeArgs` 中 → 报 unknown load params。改为 `FakeSpec("stt", WhisperSTTHandlerArguments)`、`FakeSpec("llm", LanguageModelHandlerArguments)`、`FakeSpec("tts", Qwen3TTSHandlerArguments)`，并补 `FakeSpec("tts", BreezeTTSHandlerArguments)` / `FakeSpec("tts", CosyVoiceTTSHandlerArguments)`；`qwen3-asr` 用 `FakeSpec("stt", Qwen3ASRSTTHandlerArguments)`。
  - `tests/test_model_config_overrides.py:129-136`：`available == 9`、`planned == 0`、`unregistered == 27`、`breeze["status"] == "available"`；许可断言保留。

- [ ] **Step 4: 运行确认通过** `pytest tests/test_spec_b_cards.py tests/test_model_registry.py tests/test_model_config_overrides.py -q` → PASS

- [ ] **Step 5: Commit** `git add src/speech_to_speech/models/builtin.py tests/test_spec_b_cards.py tests/test_model_registry.py tests/test_model_config_overrides.py && git commit -m "feat(model-registry): promote six model cards to available"`

---

### Task 9: 文档落地与全量回归

**Files:**
- Modify: `docs/model-integration-guide-CN.md`（§7.1、§7 第 4 条 `:182`、§8、§9.2、§9.3、§10）
- Modify: `docs/superpowers/specs/2026-11-10-s2s-model-registry-design.md:340`（§10 漂移句）
- Modify: `docs/parameter-catalog.md`（登记 `breeze_tts_*` 参数）
- Modify: `tests/test_spec_b_cards.py`（追加两条文档断言）
- Test: `tests/test_model_config_overrides.py::test_integration_guide_has_all_nine_sections`（回归，仍须通过）

**Interfaces:**
- Consumes: Task 1–8 全部落地产物
- Produces: 与代码一致的接入规范、参数目录、Spec A 漂移修正

- [ ] **Step 1: 写失败测试** 在 `tests/test_spec_b_cards.py` 追加：
  - `test_integration_guide_documents_runtime_wiring`：读 `docs/model-integration-guide-CN.md`，断言含「`_settings()` 之后」「`repo_id` 不改写 settings」「`_PATH_FIELDS`」与按 card 角色二分的一致性规则表头。
  - `test_spec_a_section_10_no_longer_excludes_breeze_self_host`：读 Spec A §10 行，断言不含「Breeze TTS 2 自托管权重适配层因 D7 不在 Spec B 范围内」。

- [ ] **Step 2: 运行确认失败** `pytest tests/test_spec_b_cards.py -q` → FAIL（文档未更新）

- [ ] **Step 3: 实现文档修订**
  - 接入规范 §7.1：把一致性测试规则改为 spec §6.7 的二分表（默认模型 card / 模型变体 card）；§7 第 4 条把「`planned` 的 `breeze-tts-2`」改为「`available` 的 `breeze-tts-2`」，`deprecated` 闸门改用临时注册 card 验证。
  - 接入规范 §8：草稿改为落地说明（真实 `BackendSpec` 形态、card 在 `builtin.py`、不内联）；§9.2 的 `3 available / 6 planned / 27 unregistered` 改为 `9 / 0 / 27`，并把「`config.py` 的派生逻辑禁止手改」这句 Spec A 期红线改成「Spec B 允许 `config.py` 做 §6.2 接线与合并语义修正，其余派生逻辑不改」；§9.3 补入「无 `models:` 段行为不变」验收点；§10 追加本轮决策变更。
  - 补入三条易踩坑约定：`repo_id` 覆盖不改写 settings、注入发生在 `_settings()` 之后、注入值不做 `choices`/路径展开且 `*_model_name` 不进 `_PATH_FIELDS`。
  - 补入 Breeze / CosyVoice 构建期依赖安装步骤（官方仓库 requirements、PYTHONPATH、flash-attn 架构参数），明确运行时不依赖 GitHub。
  - Spec A §10 那句改为指向本 spec（§8/§12 的历史验收值**保留不改**，只加一行说明）。
  - `docs/parameter-catalog.md` 登记 `breeze_tts_*` 字段（含 `breeze_tts_model_name` 默认 `BreezeBlue/Breeze-TTS-2`、`breeze_tts_chunk_size` 默认 512）与 `cosyvoice_tts_prompt_wav`。

- [ ] **Step 4: 全量回归**
  - `ruff check src/ tests/` → 无输出
  - `ruff format --check src/ tests/` → 无输出
  - `mypy src/` → Success
  - `pytest tests/ -x -q` → 全绿
  - `python -m speech_to_speech.cli models list --json` → 9 `available` / 0 `planned` / 27 `unregistered`，`breeze-tts-2` 状态 `available`、无 deprecated 告警
  - 确认 `git status --short` 中 `config/prod.yaml`、9 个 `docker-compose*.yml`、`cli.py` 均无改动

- [ ] **Step 5: Commit**（**只 add 精确路径**，不要用 `git add docs/`：工作区存在用户明确不提交的未跟踪文件 `docs/model-combination-matrix-CN.md` 与 `docs/voiceprint-embedding-service-design-CN.md`）

```bash
git add docs/model-integration-guide-CN.md \
  docs/superpowers/specs/2026-11-10-s2s-model-registry-design.md \
  docs/parameter-catalog.md \
  tests/test_spec_b_cards.py
git commit -m "docs: land Spec B integration guide and acceptance updates"
```

---

## Self-Review

**1. Spec coverage** — 逐节对照：§2 目标 → Task 4/5/6/7/8；§3 约束 → Global Constraints；§4 现状核查 → 各 Task 的 Step 3 注记；§5 Approaches → 已锁定方案 1，计划只实现该方案；§6.1 文件清单 → 文件结构表全覆盖；§6.2 配置注入 → Task 7（含 4 条规则与 3 条限制）；§6.3 Breeze adapter → Task 3 + Task 4；§6.4 其余五模型 → Task 5 + Task 8；§6.5 card 表 → Task 8；§6.6 错误处理 → Task 2/3/6/7；§6.7 测试与验收 → Task 4/5/7/8/9；§7 留给 builder → 已在 Task 3/6 明确引用；§8 风险 → Task 9 文档落地。无缺口。

**2. Step scan** — 每个 Step 1 给出测试名与具体断言值；每个 Step 3 给出确切签名/字段/文件名与 spec 固定的值，只在算法不确定处（重采样实现、官方包导入路径）留选择，且这些选择已由 spec §7 授权。无 "add appropriate validation" 类空步骤。

**3. Type consistency** — `resample_pcm_24k_to_16k` / `iter_pcm_chunks` 在 Task 1 定义，Task 4/5 按同名同签名消费；`check_breeze_weights` / `BreezeInferenceAdapter` / `OfficialBreezeAdapter` 在 Task 3 定义，Task 4 消费；`BreezeTTSHandlerArguments` 在 Task 4 定义，Task 6 消费；两条 `BackendSpec` 的 `config_prefix` 与参数类前缀一致；`model_name`（无前缀）贯穿 Task 7/8。

**4. Review Focus** — 5 条分别钉在 Task 7（#1/#2/#3）、Task 1 与 Task 4/5（#4）、Task 3 与 Task 4（#5）；另有 Task 6 的 `test_create_backend_handler_wraps_import_error_for_breeze` 覆盖错误包装链路的互补一侧。

**5. Proportion** — 计划约 377 行、spec 421 行，篇幅相当；代码块仅用于测试名/断言清单与个别伪代码，未转录 Handler 实现。

**自检中修掉的 5 处**（已直接改在计划里）：Task 7 断言 typo 与 Task 8 顺序依赖、backend 切换时残留 settings 会掩盖测试、Task 8 假注册表 `FakeArgs` 会触发 unknown load params、Review Focus #5 的任务引用、`git add docs/` 会误提交两个用户明确不提交的未跟踪文档。
