# Spec A：统一模型注册框架（ModelCard / ModelRegistry）

> 日期：2026-11-10
> 状态：设计已批准，待 spec 审阅
> 工程：`d:/work/qwen-audio-agent/speech-to-speech-src`
> 关联：Spec B（5 个模型适配层）在本 spec 完成并通过验收后另开
> 验收口径：代码就绪 + 契约测试；**不下载权重、不加载真实模型**

---

## 1. 背景与问题

### 1.1 现有能力盘点（只读核查结论）

| 能力 | 现状 | 证据 |
|---|---|---|
| 统一接口 | `BaseHandler[InT,OutT]`（`baseHandler.py:32`）+ `pipeline/handler_types.py` 类型别名 + `pipeline/messages.py` 消息类；生命周期 `setup() / process() -> Iterator / cleanup() / on_session_end()` | `src/speech_to_speech/baseHandler.py` |
| 注册机制 | `BackendSpec`（frozen dataclass，字段 `name / kind / config_type / create_handler / config_prefix / normalize_config / required_extra / capabilities`）+ `STT_BACKENDS`(15) / `LLM_BACKENDS`(4) / `TTS_BACKENDS`(12)，共 **31 个后端**；`build_backend_registry()` 做 kind 一致性与重名校验；`_load_handler()` 延迟导入 | `backend_registry.py:103-183,351-707` |
| 配置化 | CLI 模式与 YAML 文件模式二选一；`--stt / --llm_backend / --tts` 的 choices、参数类拼装、YAML schema 校验**全部从三张注册表自动派生**；YAML 内优先级为 `显式字段 > {env: NAME} > 默认` | `module_arguments.py:62-85`；`s2s_pipeline.py:230-273`；`config.py:128-139,371-438,441-538` |
| 音频契约 | STT 输入 `16 kHz 单声道 float32 numpy`（`VADAudio.audio`）；TTS 输出 `16 kHz int16 PCM（小端 <i2）/ 512 samples 每块`；结束 yielded `AUDIO_RESPONSE_DONE = b"__RESPONSE_DONE__"`；`should_listen` / `CancelScope` / `SpeculativeTurnTracker` 负责打断与陈旧轮 | `handler_types.py`；`messages.py`；`qwen3_tts_handler.py:660-793`；`websocket_router.py:249-255` |
| 可选依赖 | `BackendSpec.required_extra` → `create_backend_handler()` 包装 `ImportError` 为 `pip install "speech-to-speech[<extra>]"` 提示 | `backend_registry.py:186-206` |
| 测试基线 | `test_backend_registry.py`(45) / `test_config.py`(33) / `test_configured_runtime.py`(33)；CI 命令 `ruff check src/ tests/`、`ruff format --check src/ tests/`、`mypy src/`、`pytest tests/ -x -q` | `tests/`；`.github/workflows/ci.yml` |

### 1.2 真正的缺口

用户需求中的「名称、类型、版本、加载参数」里，`BackendSpec` **已覆盖名称、类型、加载参数**（`name` / `kind` / `config_type`），缺的是：

1. **版本**、**权重来源（repo_id / 权重格式）**、**资源预算（显存）**、**许可**、**可用状态**；
2. 一个可按模型维度查询的**元信息门面**，以及可写入配置文件的**加载参数覆盖通道**；
3. 一份面向后续新增模型的**接入规范**，把"最小改动清单 + 音频契约 + 报错约定 + 测试清单"固化下来。

本 spec 只补这三项，**不重写注册中心、不新增模型 Handler**。

### 1.3 已核实的目标模型事实

| 模型 | 事实 | 来源 |
|---|---|---|
| Breeze TTS 2 | HF `BreezeBlue/Breeze-TTS-2`，3B 稠密 Safetensors（F32/BF16）；官方 PyTorch 推理仓库 `github.com/breezeblue-ai/breeze-tts`（**2026-11-10 已直连验证可达**，Apache-2.0 代码）；提供 CLI / 进程内库 / 流式 API 三种推理入口；**输出 24 kHz 单声道 s16le PCM**；eager 显存 ~7.7 GiB（建议 12 GB 卡）、`--fast-all` ~14.4 GiB（建议 24 GB 卡）；**权重与自托管输出仅限研究与非商业用途** | 官方 GitHub README + HF 模型卡（详见 §1.4）；社区 GGUF 版数据来自第三方检索 |
| MiniCPM-o 4.5 | HF `openbmb/MiniCPM-o-4_5`，9.4B **单一端到端 omni checkpoint**（Qwen3-8B LLM + SigLIP2 视觉编码器 + Whisper-medium 音频编码器 + CosyVoice2 语音解码器），Apache-2.0；**无官方独立 ASR/TTS 权重**；全双工协议无 Function Call / 输入转写 | 联网检索（2026-11-10）；`docs/voice-frontends/minicpm-o.zh.md` |
| 本地缓存 | `cache/` 仅有 `qwen3-asr-0.6b-hf` / `qwen3-asr-model-hf` / `qwen3-tts-model` / `nltk_data` / `smart-turn-v3.2-cpu.onnx`；全仓 `*.gguf` 0 命中 | 本地目录核查 |

### 1.4 Breeze TTS 2 官方仓库核查（2026-11-10）

**验证方式**：直接抓取 `https://github.com/breezeblue-ai/breeze-tts`（main 分支，17 commits）README 全文成功，并用 `https://huggingface.co/BreezeBlue/Breeze-TTS-2` 模型卡交叉核对。此前「容器无法直连 github.com」的假设**已不适用于本轮网络环境**；本 spec 相应风险条目已改写为 §9 的「依赖获取路径」。

**仓库结构**：`breeze_infer/`、`configs/`、`docker/`、`models/`、`tests/`、`infer.py`、`requirements.txt`、`LICENSE`、`README.md`。

| 推理入口 | 命令 / 接口 | 输出与约束 |
|---|---|---|
| CLI 离线合成 | `python infer.py <ckpt> --text ... --output out.wav`；支持 `--ref-audio` / `--ref-text` / `--instruction` / `--cfg-scale 4` / `--fast-all` | 生成 WAV 文件 |
| **进程内库**（符合 D1） | `load_runtime()` 返回 `audio_tokenizer`；`model.generate(**prepare_inputs(), output_audio=True, audio_tokenizer=...)` | `repetition_penalty=1.1`；`no_repeat_ngram_size` 与 `encoder_no_repeat_ngram_size` 必须为 `0`；`output_audio=False` 只返回 codec token；**README 未说明该路径是否流式** |
| 流式 API（备选） | `python -m breeze_infer.api <ckpt> --host 0.0.0.0 --port 7860`；`POST /v1/audio/speech`（multipart：`text` / `ref_audio` / `ref_text` / `instruction` / `cfg_scale` / `seed`）；另有 `POST /v1/audio/speech/batch`（≤128 段、`X-Segment-Bytes` 分段、`max_new_tokens` 上限 1500）与 `GET /v1/model`（`frame_rate=12.5`、`model_digest`、`max_batch_texts=128`） | **streaming mono 24 kHz signed 16-bit LE PCM**；**单并发**，流式与 batch 共享一个推理槽，忙时返回 `409` |

**环境与显存**：Linux + Python ≥3.10 + CUDA NVIDIA GPU；`python -m pip install -r requirements.txt`；`<ckpt>` 可为本地目录或 HF repo id，用 `--revision` 固定版本；官方明确「All required model components are included in the Breeze TTS 2 checkpoint」（`audio_tokenizer` 属 checkpoint 组件）。eager 推理 ~7.7 GiB（建议 12 GB 卡），`--fast-all` ~14.4 GiB（建议 24 GB 卡）；Docker 构建 `bash docker/build.sh` 默认面向 H100/Hopper(sm90)，A100 需 `FLASH_ATTN_CUDA_ARCHS=80`。

**性能与能力**：H100 + 预热 fast path 下 TTFA <40 ms、RTF 0.32（约 3.1× 实时）；单模型支持中英双语；Voice Clone / Voice Design / Voice Direction 三模式；vocal events 英文用 `(laugh)`、中文用 `[笑]` 等内联标记。

**许可（重大约束）**：代码为 Apache-2.0，`audio_tokenizer` 基于 Qwen3-TTS（Apache-2.0）；但**模型权重、checkpoints、adapters、衍生模型及自托管输出**受 `BreezeBlue Research and Non-Commercial License` 约束，**仅限研究与非商业用途**；只有 BreezeBlue 付费托管平台/API 的输出可商用，付费订阅也不授予自托管权重的商用权。

**对本 spec 的四点影响**：
1. 官方输出 24 kHz s16le 与管线 16 kHz int16 / 512 samples 契约不一致 → Spec B 必须做重采样与块切分（§7.4）。
2. 官方流式 API 单并发且忙时返回 `409`，与 D1「进程内加载」是不同路径 → Spec B 优先进程内库路径，服务路径仅作备选。
3. 官方低延迟指标来自 H100 + 预热 fast path + streaming API；进程内 `model.generate()` 是否流式**官方 README 未说明** → Spec B 需 PoC 验证，若不流式则首音延迟显著上升（§9）。
4. 权重非商业许可 → 商用场景不得采用自托管 Breeze TTS 2，须由用户确认使用场景（§9）。

---

## 2. 已确认决策

| # | 决策 | 影响 |
|---|---|---|
| D1 | 目标模型以**本地权重进程内加载**（HF / transformers / GGUF）接入 | Spec B 的 Handler 自带权重加载；Breeze TTS 2 官方提供进程内库路径 `load_runtime()` / `model.generate()`（§1.4），与 D1 一致，流式 API 仅作备选；本 spec 只定义元信息与报错约定 |
| D2 | MiniCPM 三段按**同源组件**口径：ASR=Whisper-medium、TTS=CosyVoice2、LLM=Qwen3-8B（MiniCPM-o 4.5 内部同源组件的官方独立权重），另可选 MiniCPM-2B/4B | 必须写入 card 的 `notes`：「非 MiniCPM 品牌独立模型」，避免误导 |
| D3 | 验收为**代码就绪 + 契约测试**：写真实加载/推理代码但不下载权重，用 mock/stub 验证 | 本 spec 全部测试不触网、不占显存 |
| D4 | 范围拆两层：**Spec A = 框架层**（本文件），Spec B = 5 个适配层 | 本 spec 不实现任何新模型 Handler |
| D5 | 架构采用**方案 1**：`BackendSpec` 加可选 `models` 字段 + 独立 `ModelCard`/`ModelRegistry`；card 只作元信息声明，不驱动加载 | 31 条既有 `BackendSpec(...)` 构造逐字不改 |
| D6 | **GitHub 可达性已于 2026-11-10 验证**：官方 `breezeblue-ai/breeze-tts` README 全文已抓取，事实纳入 §1.4 | §9 的 GitHub 风险条目改写为「依赖获取路径」，不再以「无法直连」为前提；Spec B 可在构建期克隆仓库安装 `requirements.txt` |

**非目标（明确排除，不写进实现计划）**：重写 CLI/YAML 派生逻辑；外置 manifest 与 `entry_points` 插件发现；下载或验证任何权重；改动 9 个 `docker-compose*.yml`、`config/prod.yaml`、`docs/parameter-catalog.yaml`；修改外层 Node 网关 `server/src/voice/providers/` 的任何文件；接入 MiniCPM-o 端到端全双工协议。

---

## 3. 架构与组件

### 3.1 文件改动清单

| 文件 | 类型 | 具体改动 |
|---|---|---|
| `src/speech_to_speech/model_registry.py` | 新增 | `ModelKind`、`ModelStatus`、`ModelCard`、`ModelRegistry`、`ModelRegistryError`、`ModelNotAvailableError`；模块级单例 `MODEL_REGISTRY` 与门面 `register_model() / list_models() / resolve_model() / validate_models()` |
| `src/speech_to_speech/models/__init__.py` | 新增 | 空包标记 |
| `src/speech_to_speech/models/builtin.py` | 新增 | 内置 `ModelCard` 清单（见 §6）；函数 `builtin_model_cards() -> tuple[ModelCard, ...]` |
| `src/speech_to_speech/backend_registry.py` | 修改 | `BackendSpec` 增加**带默认值**的可选字段 `models: tuple[ModelCard, ...] = ()`；新增 `bind_model_cards()`，在三张注册表构建完成后把 card 注册进 `MODEL_REGISTRY` 并执行 `validate_models()`；`build_backend_registry()` 与 `create_backend_handler()` 原逻辑不变 |
| `src/speech_to_speech/config.py` | 修改（3 处） | ① `validate_config()` 顶层白名单加入 `"models"`（`config.py:374`），并新增 `_validate_models_section()` 做结构校验；② 新增 `_apply_model_overrides()` 生成每 pipeline 的 card 副本；③ `resolve_config()` 把结果写入 `ResolvedPipeline.model_cards`（`ResolvedPipeline` 增加带默认值的字段） |
| `src/speech_to_speech/cli.py` | 修改（2 处） | `Command` 类型加入 `"models"`；`main()` 中在 `_dispatch()` 之前分流 `models list [--kind ...] [--json]` 到只读打印函数，**不经过** `_run_file_command()` 与 `run_pipeline_command()`，因此不受「File mode accepts only --file and --name」约束 |
| `docs/model-integration-guide-CN.md` | 新增 | 接入规范（目录见 §7） |
| `tests/test_model_registry.py` | 新增 | 见 §8 |
| `tests/test_model_config_overrides.py` | 新增 | 见 §8 |

**不改动**：`module_arguments.py`、`s2s_pipeline.py` 的参数类拼装与 choices 派生、`configured_runtime.py`、`baseHandler.py`、`pipeline/*`、所有现有 Handler、`pyproject.toml`（本 spec 无新依赖）。

### 3.2 `ModelCard` 字段定义

`@dataclass(frozen=True)`，全部字段有明确类型与默认值策略：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | `str` | 是 | 稳定标识，小写连字符，如 `breeze-tts-2`；全局唯一 |
| `name` | `str` | 是 | 展示名，如 `Breeze TTS 2` |
| `kind` | `ModelKind = Literal["stt","llm","tts"]` | 是 | 必须与关联 `BackendSpec.kind` 一致 |
| `version` | `str` | 是 | 模型版本；现有模型用权重目录/HF revision 语义（如 `1.7b-hf`），不接受空串 |
| `provider` | `str` | 是 | 发布方，如 `BreezeBlue` / `OpenBMB` / `Alibaba Qwen` |
| `repo_id` | `str \| None` | 否 | HF repo 或本地目录；`weight_format="remote"` 时为 `None` |
| `weight_format` | `Literal["safetensors","gguf","mlx","remote"]` | 是 | 权重格式 |
| `backend_name` | `str` | 是 | 关联的 `BackendSpec.name`；`status="available"` 时必须存在于对应注册表 |
| `default_load_params` | `Mapping[str, Any]` | 否（默认 `{}`） | 加载参数元信息；键必须与关联 `config_type` dataclass 的字段名一致（由一致性测试保证） |
| `min_vram_gb` | `float \| None` | 否（默认 `None`） | **单一数值**：默认加载配置下的单路基准显存（GiB）；其它量化档/快路径档一律写入 `notes`；`None` 表示未申报 |
| `license` | `str \| None` | 否（默认 `None`） | 未核实则填 `None`，**禁止猜测** |
| `status` | `ModelStatus = Literal["available","planned","deprecated"]` | 是（默认 `"available"`） | `planned` = 元信息已登记、适配层未实现（Spec B）；`deprecated` = 保留但不再推荐 |
| `notes` | `str` | 否（默认 `""`） | 必须写明「同源组件非品牌模型」、必备子目录、量化档等 |

**card 不驱动加载**：Handler 的实际参数仍来自 `config_type` → `spec.normalize()` → `setup_kwargs`。card 的 `default_load_params` 是**声明与校验依据**；Spec B 的 Handler 可主动调用 `resolve_model()` 读取，但不得绕过 `spec.normalize()`。这样 `normalize_dataclass_config()` 的 `config_prefix` 剥离与 `gen_kwargs` 合并逻辑保持单一事实来源。

### 3.3 `ModelRegistry` API

| 方法 | 签名语义 | 行为 |
|---|---|---|
| `register` | `(card: ModelCard) -> None` | id 重复抛 `ModelRegistryError` |
| `get` | `(model_id: str) -> ModelCard` | 不存在抛 `ModelRegistryError`，消息列出相近 id |
| `list` | `(*, kind=None, status=None) -> tuple[ModelCard, ...]` | 按 `id` 稳定排序 |
| `by_backend` | `(backend_name: str) -> tuple[ModelCard, ...]` | 供 `models list` 反查 |
| `validate` | `() -> None` | 校验 id 唯一、`kind` 与 backend 一致、`backend_name` 存在、`status="available"` 的 backend 必须能构造（只查注册表，不 import handler）、`default_load_params` 键名属于对应 `config_type` 字段；一次性收集全部冲突后抛出 |
| `resolve_model` | 门面 `(model_id) -> ModelCard` | `status="planned"` 抛 `ModelNotAvailableError`，消息含 Spec B 与接入规范章节号；`deprecated` 返回 card 但由 CLI 打印告警 |

**无 card 的后端不虚构元信息**：`models list` 对没有 card 的后端显示 `unregistered` 行（只列 backend name 与 kind），不填写版本/许可/显存。Spec B 之外不批量补卡。

---

## 4. 配置化与数据流

### 4.1 模型选择（不变）

- YAML 文件模式：`blocks.<stage>.backend`
- CLI 模式：`--stt / --llm_backend / --tts`
- 不新增第三套选择器、不新增环境变量前缀、不动 `Command` 之外的命令语义。

### 4.2 新增 YAML 顶层 `models:` 段

作用：**按 `model_id` 覆盖 `default_load_params` 与 `repo_id`**，用于切换本地权重目录、设备、dtype 等，无需改代码。

约束：
1. `validate_config()` 顶层白名单扩展为 `{"schema_version","runtime","blocks","pipelines","models"}`；
2. 段结构为 `models: {<model_id>: {repo_id?, default_load_params?}}`，只允许这两个键；`model_id` 必须是已注册 card，否则报 `ConfigurationError` 并列出可用 id；
3. `default_load_params` 的键必须存在于该 card 关联 `config_type` 的字段中；值类型沿用 `_settings()` 的既有严格校验；
4. 环境变量引用沿用 `{env: NAME}`，缺失即报错、不回退默认。

### 4.3 覆盖作用域

`_apply_model_overrides(document, environment)` 在 `resolve_config()` 内、逐 pipeline 循环中执行，产出 `model_cards: Mapping[str, ModelCard]`（`dataclasses.replace` 生成副本），写入 `ResolvedPipeline.model_cards`。

- **不写回** `MODEL_REGISTRY` 单例，保证命名 pipeline 池之间互不污染；
- `ResolvedPipeline` 增加带默认值字段 `model_cards: Mapping[str, ModelCard] = {}`，现有构造点不变；
- 未被覆盖的模型不在该字典中出现，消费者以 `resolve_model()` 读到的全局 card 为准；
- Spec A 的消费者只有 `models list` 与测试；Spec B 的 Handler 若需使用覆盖值，统一从当前 pipeline 的 `model_cards` 取，不得自行读环境变量。

### 4.4 只读子命令

`speech-to-speech models list [--kind stt|llm|tts] [--json]`：输出 `id / name / kind / version / provider / backend / status / weight_format / min_vram_gb / license`。`--json` 供 console 或脚本消费。`planned` 行明确标注「适配层见 Spec B」，`deprecated` 行打印告警。该命令不加载任何 handler、不读权重、不触网。

### 4.5 加载链路（不变）

```
config_type dataclass → spec.normalize() → setup_kwargs → BaseHandler.setup()
                                  ↑
                    ModelCard（旁路元信息，不参与）
```

---

## 5. 错误处理

| 场景 | 行为 | 责任层 |
|---|---|---|
| card id 重复 / kind 错位 / backend 不存在 / `available` 指向未注册 backend / `default_load_params` 键名非法 | 模块导入期 `validate_models()` 抛 `ModelRegistryError`，一次性列出**全部**冲突 | Spec A |
| 未知 `model_id` 出现在 `models:` 段 | `ConfigurationError`，列出可用 id | Spec A |
| `models:` 段出现非法键或值类型不符 | `ConfigurationError`，错误路径精确到 `("models", <id>, <key>)` | Spec A |
| 选中 `status="planned"` 且 `backend_name` 尚未注册的模型 | YAML `blocks.*.backend` 走既有 `"Choose an existing registered backend."`；显式 `resolve_model()` 抛 `ModelNotAvailableError`，消息指向接入规范 §3 与 Spec B | Spec A |
| `status="planned"` 但 `backend_name` 已注册（如 `transformers` 下的 MiniCPM 同源 LLM） | card 表示「该后端下的一个模型变体尚未验证」：**不阻断**既有 backend 的使用，Spec A 不引入模型级选择器；`models list` 明确显示 `planned` 并在 `notes` 说明需由 Spec B 提供该变体的加载配置 | Spec A |
| 权重缺失（Spec B Handler） | 统一抛 `ModelWeightsMissingError`：消息必须含 `repo_id`、必备子目录（Breeze TTS 2 的 `audio_tokenizer/`）、下载命令；**禁止静默回退到其他模型**。Spec A 只在接入规范 §7.5 约定该异常的接口与消息格式，异常类本身由 Spec B 实现 | Spec A 约定 / Spec B 实现 |
| 可选依赖缺失 | 沿用既有 `required_extra` 机制 | 既有 |
| `{env: NAME}` 未设置 | 沿用既有「缺失即报错、不回退默认」 | 既有 |

---

## 6. 内置 ModelCard 清单

### 6.1 现有模型（`status="available"`）

| id | name | kind | version | backend_name | weight_format | min_vram_gb | license | 数据性质 |
|---|---|---|---|---|---|---|---|---|
| `qwen3-asr-1.7b-hf` | Qwen3-ASR-1.7B | stt | `1.7b-hf` | `qwen3-asr` | safetensors | 1.8（另注：代码 help 标 ~4 GB） | `None` | `docs/hardware/performance-assumptions.md` 实测口径 |
| `qwen3-tts-1.7b-customvoice` | Qwen3-TTS-12Hz-1.7B-CustomVoice | tts | `12hz-1.7b` | `qwen3` | safetensors | 3.4 | `None` | 同上；许可需核实，故填 `None` |
| `qwen3.5-4b-transformers` | Qwen3.5-4B (transformers) | llm | `3.5-4b` | `transformers` | safetensors | 8.0 | `None` | `language_model_arguments.py`：本列为默认 FP16 ≈8 GB；4bit NF4 ≈2.1 GB 写入 `card.notes` |

> `models list` 的 `unregistered` 行定义为「没有任何 `ModelCard` 关联的已注册后端」。card 共关联 4 个已注册后端（`qwen3-asr`、`qwen3`、`transformers`、`whisper`），故其余 **27 个**后端在 Spec A 内**不补卡**。这是刻意选择：不猜测未核实的版本、许可与显存数字。

### 6.2 目标新模型（`status="planned"`，仅登记元信息，Spec B 翻为 `available`）

| id | name | kind | version | provider | repo_id | weight_format | backend_name | min_vram_gb | license | notes |
|---|---|---|---|---|---|---|---|---|---|---|
| `breeze-tts-2` | Breeze TTS 2 | tts | `2` | BreezeBlue | `BreezeBlue/Breeze-TTS-2` | safetensors | `breeze-tts-2` | 7.7 | `BreezeBlue Research and Non-Commercial License`（权重；推理代码 Apache-2.0） | 本列为官方 **eager** 显存 GiB；`--fast-all` 快路径为 **14.4 GiB**，需 24 GB 卡。官方输出 **24 kHz mono s16le PCM → 必须重采样到 16 kHz 并切 512 samples 块**；流式 API 单并发、忙时 `409`；checkpoint 自带 `audio_tokenizer`；用 `--revision` 固定权重版本；**自托管权重与输出仅限研究/非商业**；社区 GGUF 版另有 Q8_0(3.3 GB)/Q4_K(2.4 GB) 量化档（第三方数据，非官方 PyTorch 路径） |
| `whisper-medium` | Whisper-medium | stt | `medium` | OpenAI / MiniCPM-o 同源 | `openai/whisper-medium` | safetensors | `whisper` | `None`（未申报，待 Spec B 实测） | `None` | **MiniCPM-o 4.5 同源组件，非 MiniCPM 品牌独立模型** |
| `cosyvoice2` | CosyVoice2 | tts | `2` | Alibaba / MiniCPM-o 同源 | `FunAudioLLM/CosyVoice2-0.5B` | safetensors | `cosyvoice2` | `None`（未申报，待 Spec B 实测） | `None` | **MiniCPM-o 4.5 同源组件，非 MiniCPM 品牌独立模型**；本仓 `cosyvoice_handler.py` 存在但未注册 |
| `minicpm-homologous-qwen3-8b` | Qwen3-8B（MiniCPM-o 同源 LLM） | llm | `3-8b` | Alibaba Qwen / MiniCPM-o 同源 | `Qwen/Qwen3-8B` | safetensors | `transformers` | 16.0 | `None` | **MiniCPM-o 4.5 同源组件，非 MiniCPM 品牌独立模型**；本列为默认 FP16；Q8 ≈8.5 GB / Q4 ≈5.0 GB 为可选量化档 |
| `minicpm-2b` / `minicpm-4b` | MiniCPM-2B / 4B | llm | `2b` / `4b` | OpenBMB | `None` | safetensors | `transformers` | 1.2 | `None` | **可选**；本列为 2B Q4 估值（`docs/models.md:72`）；Spec A 不填具体 repo（`repo_id=None`），Spec B 核实确切 repo id 后再补 |

> `min_vram_gb=None` 与 `license=None`（Breeze TTS 2 除外）是**明确的「未申报/未核实」语义**，不是占位符；`models list --json` 输出 `null`。Breeze TTS 2 的显存与许可均来自官方 GitHub README / HF 模型卡（§1.4）。

### 6.3 显存预算约束（写进接入规范，供 Spec B 选型）

现有管线单路实测 **4.6 GB（4633 MiB）**，并发公式 `floor(可用显存GB × 0.85 ÷ 4.6)`。本机 RTX 5070 Ti Laptop 12 GB 上：S2S + Qwen3.5-4B Q4 已达 11878 MiB（仅余 ~67 MiB）。因此：

- Breeze TTS 2 官方口径为 **eager ~7.7 GiB（建议 12 GB 卡）/ `--fast-all` ~14.4 GiB（建议 24 GB 卡）**，但这是**单独跑 Breeze** 的口径，不含本仓管线。叠加现有 4.6 GB 管线底座后：eager 约 **12.3 GB → 12 GB 卡无法同卡共存**（需 ≥16 GB 卡，或做互斥加载/卸载）；`--fast-all` 约 **19 GB → 需 24 GB 卡**。Spec B 不得直接沿用官方的 12 GB / 24 GB 建议值。
- Qwen3-8B FP16（~16 GB）需 24 GB 卡或 Q4/Q8 量化。
- **许可约束**：Breeze TTS 2 自托管权重与输出仅限研究/非商业；商用场景须换模型或改走 BreezeBlue 付费托管 API（§1.4、§9）。
- Spec B 必须为每个模型申报 `min_vram_gb` 并在文档中给出「互斥选型 / 量化档 / 多卡」建议；Spec A 只负责让这些数字可被注册与查询。

---

## 7. 接入规范文档目录（`docs/model-integration-guide-CN.md`）

1. **三层扩展点**：`ModelCard`（元信息）/ `BackendSpec`（后端）/ `BaseHandler`（推理）各自的职责边界与何时该改哪一层。
2. **最小改动清单**：Handler + 参数 dataclass + 一条带 `models` 的 `BackendSpec`；条件项 `pyproject.toml` optional extra、`_PATH_FIELDS`、`docs/parameter-catalog.yaml`、`config/prod.yaml`、compose。明确 CLI choices / 参数类拼装 / YAML 校验为**自动派生，禁止手改**。
3. **ModelCard 填写规范**：字段表、`status` 状态机（`planned → available → deprecated`）、命名规则、未核实字段一律 `None`、同源组件必须写 `notes`。
4. **Handler 契约**：`setup() / process() -> Iterator / cleanup()`；STT 输入 16 kHz float32 `VADAudio`；TTS 输出 16 kHz int16 PCM / 512 samples 块 + `AUDIO_RESPONSE_DONE`；`should_listen` 仅在 `EndOfResponse` 后恢复；`CancelScope` / `SpeculativeTurnTracker` 陈旧轮丢弃；语言码与说话人归属透传。**Breeze TTS 2 专项**：官方 24 kHz mono s16le → 16 kHz 重采样与 512 samples 块切分、单推理槽互斥与 `409` 处理、Voice Clone / Design / Direction 三模式映射、中英 vocal events 标记（`[笑]` / `(laugh)`）透传、`--revision` 固定权重版本。
5. **错误约定**：`ModelWeightsMissingError`（含 repo_id、checkpoint 自带的 `audio_tokenizer` 说明、下载/安装命令）、官方流式 API `409` 单并发处理、禁止静默回退、`required_extra` 用法；**权重许可提示**（Breeze 研究/非商业限制）必须写在部署文档与 `models list` 输出中。
6. **显存与资源申报**：`min_vram_gb` 为**单一基准数值**（默认加载配置下单路峰值 GiB），其它量化档/快路径写入 `card.notes`；与管线 4.6 GB 底座的叠加规则（Breeze eager ≈12.3 GB / fast-all ≈19 GB）、互斥选型建议；官方 12 GB / 24 GB 建议值仅适用于单独运行 Breeze。
7. **一致性测试模板**：card↔参数类默认值一致、音频契约（采样率/dtype/块大小/哨兵，**含 24 kHz→16 kHz 重采样正确性**）、权重缺失报错、registry 延迟导入不被破坏。
8. **Spec B 五模型 card 示例**：Breeze TTS 2、Whisper-medium、CosyVoice2、MiniCPM 同源 Qwen3-8B、可选 MiniCPM-2B/4B，逐条给出 BackendSpec 草稿与权重下载命令；Breeze 另附官方三类入口（`infer.py` / `load_runtime()+model.generate()` / `breeze_infer.api`）、`requirements.txt` 安装、Docker `sm90` 默认与 A100 `FLASH_ATTN_CUDA_ARCHS=80` 构建说明。
9. **验收清单**：ruff / mypy / pytest 命令、兼容性红线、`models list` 输出核对。

---

## 8. 测试与验收

### 8.1 新增测试

`tests/test_model_registry.py`：
- card 字段默认值与 frozen 语义；
- `register()` 重复 id 报错；`list(kind=..., status=...)` 过滤与稳定排序；
- `validate()` 检出 kind 错位、backend 不存在、`available` 指向未注册 backend、`default_load_params` 键名非法，且一次性列出全部冲突；
- `resolve_model()` 对 `planned` 抛 `ModelNotAvailableError` 且消息含规范章节；对 `deprecated` 返回 card；
- 无 card 后端在 `models list` 中标 `unregistered`，不产生虚构版本/许可；
- 导入 `model_registry` 不触发任何 STT/TTS/LLM handler 模块导入（沿用既有延迟导入测试风格）。

`tests/test_model_config_overrides.py`：
- `models:` 段合法覆盖生成 card 副本；全局 `MODEL_REGISTRY` 不被污染；
- 两个命名 pipeline 各自覆盖互不影响；
- 未知 `model_id`、非法键、值类型不符、`{env:}` 缺失均报 `ConfigurationError` 且错误路径精确；
- 未覆盖模型不出现在 `ResolvedPipeline.model_cards`；
- `models list --json` 输出字段完整、`null` 语义正确。

### 8.2 回归与兼容性红线

- 既有 `test_backend_registry.py`(45) / `test_config.py`(33) / `test_configured_runtime.py`(33) 全绿；
- CI 同款命令全绿：`ruff check src/ tests/`、`ruff format --check src/ tests/`、`mypy src/`、`pytest tests/ -x -q`；
- **31 条 `BackendSpec(...)` 构造逐字不改**；`--stt/--llm_backend/--tts` 的 choices 与默认值不变；`config/prod.yaml` 与 9 个 `docker-compose*.yml` 内容不变；`example_configs/mac.yaml` 不变。

### 8.3 交付验收点

1. `speech-to-speech models list` 能列出 3 个 `available`、6 个 `planned`、27 个 `unregistered` 行（计数口径见 §6.1）；`--json` 可解析。
2. 一个示例 YAML 带 `models:` 覆盖，可被 `resolve_config()` 正确解析且不影响未覆盖 pipeline。
3. 全部测试不触网、不下载权重、不加载真实模型、不占用 GPU。
4. `docs/model-integration-guide-CN.md` 含 §7 全部 9 节，无占位内容。

---

## 9. 风险与边界

| 风险 | 处置 |
|---|---|
| `BackendSpec` 加字段破坏 frozen dataclass 构造 | 新字段带默认值 `()`，位于所有现有字段之后；现有 31 条构造均为位置/关键字混合但不含新字段，保持兼容；由 `test_backend_registry.py` 回归验证 |
| `models:` 段被 `validate_config()` 拒绝 | 明确扩展顶层白名单（`config.py:374`），并新增 `_validate_models_section()`；写入 §3.1 改动清单 |
| `models list` 被 `_run_file_command()` 的 "only --file and --name" 拦截 | 在 `main()` 中早于 `_dispatch()` 分流，独立 parser；写入 §3.1 改动清单 |
| card 与参数类默认值漂移 | 一致性测试模板（§7.7），Spec B 每个模型必须提供；`validate()` 也校验键名合法 |
| 目标模型 repo_id / 显存数字未经实测 | Breeze TTS 2 的显存、许可、音频格式已由官方 GitHub README 与 HF 模型卡核实（§1.4）；其余 card 未核实字段仍填 `None` 并在 `notes` 说明；`minicpm-2b/4b` 的 `repo_id` 留 `None`，由 Spec B 核实后补 |
| 12 GB 卡无法同时常驻多个新模型 | 按官方口径重算：Breeze eager ~7.7 GiB + 管线 4.6 GB ≈ 12.3 GB，`--fast-all` ~14.4 GiB + 4.6 GB ≈ 19 GB → 分别需 ≥16 GB / 24 GB 卡或互斥加载（§6.3）。本 spec 只让 `min_vram_gb` 可注册、可查询 |
| GitHub 依赖获取路径（**可达性已验证**） | 2026-11-10 已直连抓取官方 `breezeblue-ai/breeze-tts` README 全文。依赖固定为**构建期** `git clone` + `python -m pip install -r requirements.txt` 烤入镜像，或预装 wheel；**容器运行时不得依赖 GitHub**。工具侧可达不等于容器网络命名空间可达，Spec B 需在目标容器内复核一次 |
| **Breeze TTS 2 权重与自托管输出仅限研究/非商业**（`BreezeBlue Research and Non-Commercial License`） | 若本工程存在商用场景，自托管 Breeze TTS 2 不可采用：改为使用 BreezeBlue 付费托管 API 的输出，或更换为 Apache-2.0 等可商用 TTS。**该使用场景须由用户明确确认**，并写入接入规范 §7.5 与 `models list` 输出 |
| 官方输出 24 kHz s16le 与管线 16 kHz int16 / 512 samples 契约不一致；流式 API 单并发、忙时 `409` | Spec B 的 Handler 必须实现重采样 + 块切分，并对单推理槽做互斥；一致性测试模板（§7.7）覆盖重采样正确性 |
| 官方 Docker 默认面向 H100/Hopper(sm90)，A100 需 `FLASH_ATTN_CUDA_ARCHS=80` | 目标卡若为 Blackwell / Ada，Spec B 需验证 flash-attn 构建架构参数；不得假设官方镜像可直接运行 |
| 官方低延迟指标（TTFA <40 ms / RTF 0.32）来自 H100 + 预热 fast path + streaming API，而 D1 选的是进程内 `model.generate()`；**该路径是否流式，官方 README 未说明** | Spec B 必须先做 PoC：若进程内路径不流式，需自行实现分块产出或退回到官方流式 API（届时须接受单并发与 `409` 约束）；不得把 40 ms 指标直接写进本仓延迟验收线 |
| 外层 Node 网关与 s2s 注册表无共用 | 本 spec 明确不修改 `server/src/voice/providers/`；MiniCPM-o 端到端 Provider 与 Spec B 的「同源组件三段」是不同接入路径，互不冲突 |

---

## 10. 交付物清单（Spec A）

| 类型 | 路径 |
|---|---|
| 代码 | `src/speech_to_speech/model_registry.py`、`src/speech_to_speech/models/__init__.py`、`src/speech_to_speech/models/builtin.py` |
| 代码改动 | `backend_registry.py`、`config.py`、`cli.py` |
| 文档 | `docs/model-integration-guide-CN.md`、本 spec |
| 测试 | `tests/test_model_registry.py`、`tests/test_model_config_overrides.py` |
| 验证结论 | §8.2 全部命令输出，以及既有测试零回归的证明 |

Spec A 完成并验收后，另开 **Spec B** 设计文档覆盖 5 个适配层（Breeze TTS 2 / Whisper-medium / CosyVoice2 / MiniCPM 同源 Qwen3-8B / 可选 MiniCPM-2B·4B）的 Handler、参数 dataclass、`BackendSpec` 注册与契约测试。
