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
| Breeze TTS 2 | HF `BreezeBlue/Breeze-TTS-2`，3B 稠密 Safetensors（F32/BF16）；官方 PyTorch 推理仓库 `github.com/breezeblue-ai/breeze-tts`（**2026-11-10 已直连验证可达**，Apache-2.0 代码）；提供 CLI / 进程内库 / 流式 API 三种推理入口；**输出 24 kHz 单声道 s16le PCM**；eager 显存 ~7.7 GiB（建议 12 GB 卡）、`--fast-all` ~14.4 GiB（建议 24 GB 卡）；**权重与自托管输出仅限研究与非商业用途 → 本工程商用场景下禁止自托管（D7 / §6.4）** | 官方 GitHub README + HF 模型卡（详见 §1.4）；合规路径见 §1.5；社区 GGUF 版数据来自第三方检索 |
| MiniCPM-o 4.5 | HF `openbmb/MiniCPM-o-4_5`，9.4B **单一端到端 omni checkpoint**（Qwen3-8B LLM + SigLIP2 视觉编码器 + Whisper-medium 音频编码器 + CosyVoice2 语音解码器），Apache-2.0；**无官方独立 ASR/TTS 权重**；全双工协议无 Function Call / 输入转写 | 联网检索（2026-11-10）；`docs/voice-frontends/minicpm-o.zh.md` |
| 本地缓存 | `cache/` 仅有 `qwen3-asr-0.6b-hf` / `qwen3-asr-model-hf` / `qwen3-tts-model` / `nltk_data` / `smart-turn-v3.2-cpu.onnx`；全仓 `*.gguf` 0 命中 | 本地目录核查 |

### 1.4 Breeze TTS 2 官方仓库核查（2026-11-10）

**验证方式**：直接抓取 `https://github.com/breezeblue-ai/breeze-tts`（main 分支，17 commits）README 全文成功，并用 `https://huggingface.co/BreezeBlue/Breeze-TTS-2` 模型卡交叉核对。此前「容器无法直连 github.com」的假设**已不适用于本轮网络环境**；本 spec 相应风险条目已改写为 §9 的「依赖获取路径」。

**仓库结构**：`breeze_infer/`、`configs/`、`docker/`、`models/`、`tests/`、`infer.py`、`requirements.txt`、`LICENSE`、`README.md`。

| 推理入口 | 命令 / 接口 | 输出与约束 |
|---|---|---|
| CLI 离线合成 | `python infer.py <ckpt> --text ... --output out.wav`；支持 `--ref-audio` / `--ref-text` / `--instruction` / `--cfg-scale 4` / `--fast-all` | 生成 WAV 文件 |
| 进程内库（**研究/非商业用途；D7 商用禁用**） | `load_runtime()` 返回 `audio_tokenizer`；`model.generate(**prepare_inputs(), output_audio=True, audio_tokenizer=...)` | `repetition_penalty=1.1`；`no_repeat_ngram_size` 与 `encoder_no_repeat_ngram_size` 必须为 `0`；`output_audio=False` 只返回 codec token；**README 未说明该路径是否流式** |
| 流式 API（**研究/非商业用途；D7 商用禁用**） | `python -m breeze_infer.api <ckpt> --host 0.0.0.0 --port 7860`；`POST /v1/audio/speech`（multipart：`text` / `ref_audio` / `ref_text` / `instruction` / `cfg_scale` / `seed`）；另有 `POST /v1/audio/speech/batch`（≤128 段、`X-Segment-Bytes` 分段、`max_new_tokens` 上限 1500）与 `GET /v1/model`（`frame_rate=12.5`、`model_digest`、`max_batch_texts=128`） | **streaming mono 24 kHz signed 16-bit LE PCM**；**单并发**，流式与 batch 共享一个推理槽，忙时返回 `409` |

**环境与显存**：Linux + Python ≥3.10 + CUDA NVIDIA GPU；`python -m pip install -r requirements.txt`；`<ckpt>` 可为本地目录或 HF repo id，用 `--revision` 固定版本；官方明确「All required model components are included in the Breeze TTS 2 checkpoint」（`audio_tokenizer` 属 checkpoint 组件）。eager 推理 ~7.7 GiB（建议 12 GB 卡），`--fast-all` ~14.4 GiB（建议 24 GB 卡）；Docker 构建 `bash docker/build.sh` 默认面向 H100/Hopper(sm90)，A100 需 `FLASH_ATTN_CUDA_ARCHS=80`。

**性能与能力**：H100 + 预热 fast path 下 TTFA <40 ms、RTF 0.32（约 3.1× 实时）；单模型支持中英双语；Voice Clone / Voice Design / Voice Direction 三模式；vocal events 英文用 `(laugh)`、中文用 `[笑]` 等内联标记。

**许可（重大约束）**：代码为 Apache-2.0，`audio_tokenizer` 基于 Qwen3-TTS（Apache-2.0）；但**模型权重、checkpoints、adapters、衍生模型及自托管输出**受 `BreezeBlue Research and Non-Commercial License` 约束，**仅限研究与非商业用途**；只有 BreezeBlue 付费托管平台/API 的输出可商用，付费订阅也不授予自托管权重的商用权。

**对本 spec 的四点影响**：
1. 官方输出 24 kHz s16le 与管线 16 kHz int16 / 512 samples 契约不一致 → **路径 R（托管 API）仍需**解码、重采样与块切分（§7.4）。
2. 本地流式 API 单并发且忙时返回 `409`、进程内库是否流式未说明 → **D7 禁止本地权重路径后，二者均不进入商用实现**，仅保留为研究用途的实施参考。
3. 官方低延迟指标来自 H100 + 预热 fast path + streaming API → 商用路径 L（CosyVoice2）与路径 R（托管 API）的延迟**均需 Spec B 实测**，不得沿用 40 ms 指标（§9）。
4. 权重非商业许可 → **用户已确认本工程存在商用场景**，自托管 Breeze TTS 2 禁止采用，改按 D7 / §6.4 的两条合规路径处理（§9）。

### 1.5 商用合规路径核查（2026-11-10）

**路径 L（推荐，默认）：替换为可商用本地 TTS，零新增模型。**
- `FunAudioLLM/CosyVoice2-0.5B` 本就是 D2「MiniCPM 同源三段」中的 TTS 组件，无需为 Breeze 空位再引入新模型；其官方仓库 `FunAudioLLM/CosyVoice` 的 `LICENSE` 已抓取核实为 **Apache License 2.0**（无额外非商业条款），项目内 `docs/models.md:32` 亦记为 Apache-2.0。模型 0.5B / 25 Hz，官方支持 streaming inference（文本输入流 + 音频输出流），本仓 `TTS/cosyvoice_handler.py` 已存在但未注册。
- 兜底候选为仓内已注册的轻量后端：`phonon`（`gradium/phonon-31m-en`，仓内 `TTS/README.md` 明确标注 Apache-2.0，纯 CPU、原生流式）；`kokoro`（82M，CPU 可跑）的许可需同样核对后才可作为商用兜底。
- **待核对项**：CosyVoice 的**代码**许可已核实；**权重**许可需在 Spec B 启动前核对 HF 模型卡 / ModelScope 页面（HF 模型卡未显式展示 license 字段）。核对通过前不得把 `cosyvoice2` card 标为 `available`。

**路径 R（可选）：BreezeBlue 付费托管 API。**
- 基址 `https://api.breeze.blue/v1`，鉴权头 `xi-api-key: $BREEZE_API_KEY`；`POST /v1/text-to-speech/{voice_id}?output_format=...`（同步）、`?delivery=async`（异步 job + 轮询/下载）、HTTP streaming 接受 `pcm` / `mp3` / `wav`；**Realtime WebSocket TTS** 面向 voice agent 与 barge-in，单连接多轮，默认 `output_format="pcm"`、**24 kHz mono**。输出格式另有 `mp3` / `wav_24000` / `wav_48000` / `mp3_24000_128`。
- **不是 OpenAI 兼容 `/v1/audio/speech`**，为自有协议 + 官方 SDK（`breeze_blue` Python / `@breeze.blue/sdk` Node）；单次 HTTP 请求 ≤1000 字符（可申请至 2000），中文非流式 >500 字符自动分段（≤5 段、段间 0.25 s 静音）；支持 `instructions` / `voice_settings.guidance_scale` / `speed` / `volume` / `language_code` / `model_id`，51 语言走 `breeze-tts-2-multilingual`。
- 商用输出以官方 ToS + 有效付费订阅为准，**须由用户/法务确认**；自托管权重的商用权不因订阅而获得。
- 若采用：需新建 `breeze-tts-remote` backend（或适配层转 `--tts openai`），并处理 mp3/wav 解码、24 kHz/48 kHz → 16 kHz 重采样、512 samples 块切分、网络超时与打断；本地显存 0，但**数据出域**。

**推荐理由**：路径 L 保持 D1 本地加载、数据不出域、与 D2 合并后 Spec B 模型数不增；路径 R 仅在必须保留 Breeze 音质时启用，代价是付费、外网依赖、协议适配与数据出域。

---

## 2. 已确认决策

| # | 决策 | 影响 |
|---|---|---|
| D1 | 目标模型以**本地权重进程内加载**（HF / transformers / GGUF）接入 | Spec B 的 Handler 自带权重加载；**适用范围为 MiniCPM 同源组件与路径 L 的可商用本地 TTS**；Breeze TTS 2 因 D7 **不得本地加载**，其官方进程内库路径（§1.4）仅在研究/非商业用途下才有意义；本 spec 只定义元信息与报错约定 |
| D2 | MiniCPM 三段按**同源组件**口径：ASR=Whisper-medium、TTS=CosyVoice2、LLM=Qwen3-8B（MiniCPM-o 4.5 内部同源组件的官方独立权重），另可选 MiniCPM-2B/4B | 必须写入 card 的 `notes`：「非 MiniCPM 品牌独立模型」，避免误导；CosyVoice2 同时承担路径 L 的 Breeze 替代位 |
| D3 | 验收为**代码就绪 + 契约测试**：写真实加载/推理代码但不下载权重，用 mock/stub 验证 | 本 spec 全部测试不触网、不占显存 |
| D4 | 范围拆两层：**Spec A = 框架层**（本文件），Spec B = 5 个适配层 | 本 spec 不实现任何新模型 Handler |
| D5 | 架构采用**方案 1**：`BackendSpec` 加可选 `models` 字段 + 独立 `ModelCard`/`ModelRegistry`；card 只作元信息声明，不驱动加载 | 31 条既有 `BackendSpec(...)` 构造逐字不改 |
| D6 | **GitHub 可达性已于 2026-11-10 验证**：官方 `breezeblue-ai/breeze-tts` README 全文已抓取，事实纳入 §1.4 | §9 的 GitHub 风险条目改写为「依赖获取路径」，不再以「无法直连」为前提；Spec B 可在构建期克隆仓库安装 `requirements.txt` |
| D7 | **用户已确认本工程存在商用场景**：Breeze TTS 2 权重与自托管输出仅限研究/非商业，故**禁止自托管 Breeze TTS 2** | Spec B 按 §6.4 二选一：**路径 L（推荐）** 用 CosyVoice2 等可商用本地 TTS 替代，**路径 R（可选）** 走 BreezeBlue 付费托管 API；`breeze-tts-2` card 标 `deprecated`，`models list` 打印许可告警 |

**非目标（明确排除，不写进实现计划）**：重写 CLI/YAML 派生逻辑；外置 manifest 与 `entry_points` 插件发现；下载或验证任何权重；改动 9 个 `docker-compose*.yml`、`config/prod.yaml`、`docs/parameter-catalog.yaml`；修改外层 Node 网关 `server/src/voice/providers/` 的任何文件；接入 MiniCPM-o 端到端全双工协议。

---

## 3. 架构与组件

### 3.1 文件改动清单

| 文件 | 类型 | 具体改动 |
|---|---|---|
| `src/speech_to_speech/model_registry.py` | 新增 | `ModelKind`、`ModelStatus`、`ModelCard`、`ModelRegistry`、`ModelRegistryError`、`ModelNotAvailableError`、`ModelLicenseError`；模块级单例 `MODEL_REGISTRY` 与门面 `register_model() / list_models() / resolve_model() / validate_models()` |
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
| 权重缺失（Spec B Handler） | 统一抛 `ModelWeightsMissingError`：消息必须含 `repo_id`、必备子目录（研究用途下 Breeze TTS 2 的 `audio_tokenizer/`）、下载命令；**禁止静默回退到其他模型**。Spec A 只在接入规范 §7.5 约定该异常的接口与消息格式，异常类本身由 Spec B 实现 | Spec A 约定 / Spec B 实现 |
| 商用场景（D7）下选中 `deprecated` 的自托管权重 card | 抛 `ModelLicenseError`，消息含许可名称与 §6.4 的路径 L / R 指引，**禁止静默回退到自托管权重**；异常类型由 Spec A 在 `model_registry.py` 定义，触发点由 Spec B 的 Handler / BackendSpec 实现 | Spec A 定义类型 / Spec B 触发 |
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

### 6.2 目标新模型（仅登记元信息；`breeze-tts-2` 为 `deprecated`，其余为 `planned`）

| id | name | kind | version | provider | repo_id | weight_format | backend_name | min_vram_gb | license | notes |
|---|---|---|---|---|---|---|---|---|---|---|
| `breeze-tts-2` | Breeze TTS 2 | tts | `2` | BreezeBlue | `BreezeBlue/Breeze-TTS-2` | safetensors | `breeze-tts-2` | 7.7 | `BreezeBlue Research and Non-Commercial License`（权重；推理代码 Apache-2.0） | **`status="deprecated"`（D7 商用场景禁用自托管）**：本列为官方 **eager** 显存 GiB，`--fast-all` 快路径 **14.4 GiB** 需 24 GB 卡，二者**仅研究/非商业用途参考，不进入商用部署预算**。官方输出 24 kHz mono s16le PCM；本地流式 API 单并发、忙时 `409`；checkpoint 自带 `audio_tokenizer`；`--revision` 固定权重版本。**商用须按 §6.4 走路径 L 或 R**；若走路径 R，Spec B 另注册 `breeze-tts-2-hosted`（`weight_format="remote"`）card，本 card 不复用 |
| `whisper-medium` | Whisper-medium | stt | `medium` | OpenAI / MiniCPM-o 同源 | `openai/whisper-medium` | safetensors | `whisper` | `None`（未申报，待 Spec B 实测） | `None` | **MiniCPM-o 4.5 同源组件，非 MiniCPM 品牌独立模型** |
| `cosyvoice2` | CosyVoice2 | tts | `2` | Alibaba / MiniCPM-o 同源 | `FunAudioLLM/CosyVoice2-0.5B` | safetensors | `cosyvoice2` | `None`（未申报，待 Spec B 实测） | `None`（权重许可待核对） | **MiniCPM-o 4.5 同源组件，非 MiniCPM 品牌独立模型**，同时承担 §6.4 路径 L 的 Breeze 替代位；官方代码仓库 LICENSE 已核实为 Apache-2.0，**权重许可须在 Spec B 启动前核对，通过前不得标 `available`**；本仓 `cosyvoice_handler.py` 存在但未注册 |
| `minicpm-homologous-qwen3-8b` | Qwen3-8B（MiniCPM-o 同源 LLM） | llm | `3-8b` | Alibaba Qwen / MiniCPM-o 同源 | `Qwen/Qwen3-8B` | safetensors | `transformers` | 16.0 | `None` | **MiniCPM-o 4.5 同源组件，非 MiniCPM 品牌独立模型**；本列为默认 FP16；Q8 ≈8.5 GB / Q4 ≈5.0 GB 为可选量化档 |
| `minicpm-2b` / `minicpm-4b` | MiniCPM-2B / 4B | llm | `2b` / `4b` | OpenBMB | `None` | safetensors | `transformers` | 1.2 | `None` | **可选**；本列为 2B Q4 估值（`docs/models.md:72`）；Spec A 不填具体 repo（`repo_id=None`），Spec B 核实确切 repo id 后再补 |

> `min_vram_gb=None` 与 `license=None`（Breeze TTS 2 除外）是**明确的「未申报/未核实」语义**，不是占位符；`models list --json` 输出 `null`。Breeze TTS 2 的显存与许可均来自官方 GitHub README / HF 模型卡（§1.4）。**状态分布**（按 card 计，`minicpm-2b` 与 `minicpm-4b` 为两张 card）：§6.1 的 3 张为 `available`；本表 6 张中 5 张为 `planned`、1 张（`breeze-tts-2`）为 `deprecated`。

### 6.3 显存预算约束（写进接入规范，供 Spec B 选型）

现有管线单路实测 **4.6 GB（4633 MiB）**，并发公式 `floor(可用显存GB × 0.85 ÷ 4.6)`。本机 RTX 5070 Ti Laptop 12 GB 上：S2S + Qwen3.5-4B Q4 已达 11878 MiB（仅余 ~67 MiB）。因此：

- **Breeze TTS 2 自托管已被 D7 禁止**：官方 eager ~7.7 GiB / `--fast-all` ~14.4 GiB（叠加 4.6 GB 管线后约 12.3 GB / 19 GB）**仅为研究/非商业用途参考，不进入商用部署预算**。商用路径 L 下本地 TTS 改为 CosyVoice2-0.5B（`min_vram_gb` 由 Spec B 实测）；路径 R 下本地显存为 **0**。
- Qwen3-8B FP16（~16 GB）需 24 GB 卡或 Q4/Q8 量化。
- **许可闸门（D7）**：Breeze TTS 2 自托管权重与输出仅限研究/非商业；商用必须按 §6.4 走路径 L 或 R，不得静默回退到自托管权重。
- Spec B 必须为每个模型申报 `min_vram_gb` 并在文档中给出「互斥选型 / 量化档 / 多卡」建议；Spec A 只负责让这些数字可被注册与查询。

### 6.4 商用许可约束下的 Breeze 处理（D7）

**禁止项**：Spec B 不得实现 Breeze TTS 2 的本地权重加载 Handler，覆盖官方 `load_runtime()` / `model.generate()`、`breeze_infer.api`、`infer.py` 以及社区 GGUF 量化版；`models list` 对 `breeze-tts-2` 打印 `deprecated` 许可告警。

| 路径 | 内容 | Spec B 需交付 | 代价 |
|---|---|---|---|
| **L（默认推荐）** | 用 `FunAudioLLM/CosyVoice2-0.5B` 填 Breeze 的 TTS 位，与 D2 的 MiniCPM 同源 TTS **合并为同一个适配层**；兜底用仓内 Apache-2.0 的 `phonon` / `kokoro` | `cosyvoice2` 的 Handler + 参数 dataclass + 一条 `BackendSpec`；**Spec B 模型总数不增** | 需在 Spec B 启动前核实权重许可（§1.5）；音质与 Breeze 不同 |
| **R（可选）** | BreezeBlue 付费托管 API（`https://api.breeze.blue/v1`），优先用 Realtime WebSocket TTS（24 kHz mono PCM、面向 barge-in） | 新建 `breeze-tts-remote` Handler + 参数 dataclass + `BackendSpec`；注册 `breeze-tts-2-hosted`（`weight_format="remote"`）card | 付费、外网依赖、非 OpenAI 兼容协议需适配、数据出域、商用授权须由用户/法务确认 ToS |

两条路径共同要求：音频统一转成 **16 kHz int16 PCM / 512 samples 块 + `AUDIO_RESPONSE_DONE`**；网络路径须处理超时、打断与 `should_listen` 恢复；不得把官方 H100 + fast path 的 TTFA/RTF 指标直接写进本仓验收线。

**Spec A 边界**：两条路径的 Handler / BackendSpec 全部属于 Spec B。Spec A 只负责把 `breeze-tts-2` 标为 `deprecated`、把许可与替代信息写入 `card.notes` 与接入规范，使 `models list` 与配置校验能**显式暴露许可闸门**；本 spec 不新增任何远程调用代码、不引入新依赖、不改部署配置。

---

## 7. 接入规范文档目录（`docs/model-integration-guide-CN.md`）

1. **三层扩展点**：`ModelCard`（元信息）/ `BackendSpec`（后端）/ `BaseHandler`（推理）各自的职责边界与何时该改哪一层。
2. **最小改动清单**：Handler + 参数 dataclass + 一条带 `models` 的 `BackendSpec`；条件项 `pyproject.toml` optional extra、`_PATH_FIELDS`、`docs/parameter-catalog.yaml`、`config/prod.yaml`、compose。明确 CLI choices / 参数类拼装 / YAML 校验为**自动派生，禁止手改**。
3. **ModelCard 填写规范**：字段表、`status` 状态机（`planned → available → deprecated`）、命名规则、未核实字段一律 `None`、同源组件必须写 `notes`。
4. **Handler 契约**：`setup() / process() -> Iterator / cleanup()`；STT 输入 16 kHz float32 `VADAudio`；TTS 输出 16 kHz int16 PCM / 512 samples 块 + `AUDIO_RESPONSE_DONE`；`should_listen` 仅在 `EndOfResponse` 后恢复；`CancelScope` / `SpeculativeTurnTracker` 陈旧轮丢弃；语言码与说话人归属透传。**商用路径专项**：路径 L 需核对 CosyVoice2 输出采样率并做重采样/块切分；路径 R 需处理 BreezeBlue 自有协议（非 OpenAI 兼容）、mp3/wav 解码、24 kHz/48 kHz → 16 kHz 重采样、网络超时与打断。Breeze 本地权重路径的三模式、vocal events、`--revision` 等说明**仅保留为研究用途参考**。
5. **错误约定**：`ModelWeightsMissingError`（含 repo_id 与下载/安装命令）、`ModelLicenseError`（**商用场景下选中 `deprecated` 的自托管 card 时抛出，禁止静默回退**）、远程 API 的 `401` / `429` / `Retry-After` 与超时处理、`required_extra` 用法；**许可告警**必须写进部署文档与 `models list` 输出。
6. **显存与资源申报**：`min_vram_gb` 为**单一基准数值**（默认加载配置下单路峰值 GiB），其它量化档/快路径写入 `card.notes`；与管线 4.6 GB 底座的叠加规则；**Breeze 的 7.7 / 14.4 GiB 与 12.3 / 19 GB 叠加值仅研究用途参考，不进入商用预算**（§6.3）；商用路径 L 用 CosyVoice2 实测值、路径 R 本地显存为 0。
7. **一致性测试模板**：card↔参数类默认值一致、音频契约（采样率/dtype/块大小/哨兵，**含 24 kHz→16 kHz 重采样正确性**）、权重缺失报错、**许可闸门报错**、registry 延迟导入不被破坏。
8. **Spec B 五模型 card 示例**：路径 L 的 CosyVoice2、Whisper-medium、MiniCPM 同源 Qwen3-8B、可选 MiniCPM-2B/4B，逐条给出 BackendSpec 草稿与权重下载命令；另附**路径 R 的 `breeze-tts-2-hosted` remote card 示例**（`https://api.breeze.blue/v1`、`xi-api-key`、Realtime WebSocket TTS、`wav_24000`/`pcm` 输出格式）；`breeze-tts-2` 本地权重 card 只作为 `deprecated` 反例，不给下载/安装命令。
9. **验收清单**：ruff / mypy / pytest 命令、兼容性红线、`models list` 输出核对。

---

## 8. 测试与验收

### 8.1 新增测试

`tests/test_model_registry.py`：
- card 字段默认值与 frozen 语义；
- `register()` 重复 id 报错；`list(kind=..., status=...)` 过滤与稳定排序；
- `validate()` 检出 kind 错位、backend 不存在、`available` 指向未注册 backend、`default_load_params` 键名非法，且一次性列出全部冲突；
- `resolve_model()` 对 `planned` 抛 `ModelNotAvailableError` 且消息含规范章节；对 `deprecated` 返回 card；
- `models list` 对 `deprecated` 的 `breeze-tts-2` 打印**许可告警**（含「商用禁用自托管」与 §6.4 路径 L/R 指引），`--json` 输出 `status=deprecated`；
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

1. `speech-to-speech models list` 能列出 3 个 `available`、5 个 `planned`、1 个 `deprecated`、27 个 `unregistered` 行（计数口径见 §6.1 / §6.2）；`--json` 可解析，且 `deprecated` 行带许可告警。
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
| 12 GB 卡无法同时常驻多个新模型 | Breeze 的 7.7 / 14.4 GiB 与叠加后的 12.3 / 19 GB **仅研究用途参考，不进入商用预算**（D7）；商用路径 L 下 CosyVoice2 显存由 Spec B 实测，路径 R 下本地显存为 0。本 spec 只让 `min_vram_gb` 可注册、可查询 |
| GitHub 依赖获取路径（**可达性已验证**） | 2026-11-10 已直连抓取官方 `breezeblue-ai/breeze-tts` README 全文。但 D7 禁止本地权重推理，**构建期不再需要克隆该仓库或安装其 `requirements.txt`**；路径 R 若采用，改用官方 SDK（`breeze_blue` / `@breeze.blue/sdk`）或 HTTPS 调用 `api.breeze.blue`，容器运行时不依赖 GitHub |
| **Breeze TTS 2 权重与自托管输出仅限研究/非商业**（`BreezeBlue Research and Non-Commercial License`）；**用户已确认商用场景（D7）** | 按 §6.4 处理：禁止自托管；`breeze-tts-2` 标 `deprecated` 并在 `models list` 打印许可告警；路径 L 用 CosyVoice2 等可商用本地 TTS，路径 R 用付费托管 API。**路径 R 的商用授权须由用户/法务核对官方 ToS 与订阅状态**；`ModelLicenseError` 与许可闸门测试写入接入规范 §7.5 / §7.7 |
| 官方输出 24 kHz s16le 与管线 16 kHz int16 / 512 samples 契约不一致 | 对路径 R 仍成立（Realtime WebSocket TTS 为 24 kHz mono PCM，HTTP 另有 `wav_24000` / `wav_48000` / mp3）：Spec B 必须做解码 + 重采样 + 512 samples 块切分；一致性测试模板（§7.7）覆盖重采样正确性。本地流式 API 的单并发 `409` 因 D7 不再进入商用实现 |
| 官方 Docker 默认面向 H100/Hopper(sm90)、A100 需 `FLASH_ATTN_CUDA_ARCHS=80` | 本地权重推理已被 D7 禁止，该风险**对商用路径不适用**；仅保留为研究用途的实施参考 |
| 官方低延迟指标（TTFA <40 ms / RTF 0.32）来自 H100 + 预热 fast path + streaming API | 商用路径 L（CosyVoice2）与路径 R（托管 API）的延迟**均需 Spec B 实测**，不得把 40 ms 写进本仓延迟验收线；路径 R 另需计入公网 RTT、1000 字符上限与中文自动分段（段间 0.25 s 静音） |
| **BreezeBlue 托管 API 非 OpenAI 兼容 `/v1/audio/speech`** | 路径 R 不能直接复用现有 `--tts openai` 后端：需新建 `breeze-tts-remote` Handler 或加协议适配层；同时评估付费成本、外网可用性、数据出域与 `xi-api-key` 密钥管理 |
| CosyVoice **代码**许可已核实为 Apache-2.0，但**权重**许可未在 HF 模型卡显式标注 | Spec B 启动前必须核对 HF / ModelScope 权重许可，通过前不得把 `cosyvoice2` card 标为 `available`；未通过则退回仓内已明确 Apache-2.0 的 `phonon` / `kokoro` 兜底 |
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

Spec A 完成并验收后，另开 **Spec B** 设计文档覆盖 5 个适配层（路径 L 的 CosyVoice2 / Whisper-medium / MiniCPM 同源 Qwen3-8B / 可选 MiniCPM-2B·4B，以及路径 R 可选的 `breeze-tts-2-hosted` 远程后端）的 Handler、参数 dataclass、`BackendSpec` 注册与契约测试。**Breeze TTS 2 自托管权重适配层因 D7 不在 Spec B 范围内**。
