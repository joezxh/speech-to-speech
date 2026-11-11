# 模型接入规范（Model Integration Guide）

> 工程：`speech-to-speech-src`；适用版本：Spec A 统一模型注册框架落地后（HEAD `ce04d05`）。
> 面向读者：Spec B 适配层实现者（新增模型 Handler、参数 dataclass、`BackendSpec` 与一致性测试）。
> 关联文档：`docs/superpowers/specs/2026-11-10-s2s-model-registry-design.md`（设计决策 D1–D7）、`docs/model-combination-matrix-CN.md`（显存/硬件矩阵）、`docs/parameter-catalog.md`（参数目录）。
> 口径声明：**以当前代码实现为准**。本文描述的是已经落地的 `model_registry.py` / `models/builtin.py` / `backend_registry.py` / `config.py` / `cli.py` 行为，而不是早期草稿措辞。

**先对齐几个容易写错的事实**：

- `ModelStatus` 只有三个取值：`available | planned | deprecated`。`unregistered` **不是** `ModelStatus`，它只是 `speech-to-speech models list` 为「已注册但没有任何 `ModelCard` 关联的后端」生成的 CLI 行标签。
- 当前目录共 **9 张 card**：3 `available`、5 `planned`、1 `deprecated`；`models list` 另有 27 行 `unregistered`（31 个后端中只有 4 个有关联 card）。
- `get_model()` 返回 card **不做任何状态检查**（供 `config.py` 的 `models:` 段校验与覆盖副本使用）；`resolve_model()` 才会拒绝 `planned`。
- 商用场景（D7）**禁止自托管 Breeze TTS 2 权重**：路径 L 用 CosyVoice2（或 Apache-2.0 的 `phonon` 兜底）作为本地商用 TTS；路径 R 走 BreezeBlue 付费托管 API（`https://api.breeze.blue/v1`、`xi-api-key`、**非 OpenAI 兼容**协议）。
- `min_vram_gb` 是**单一 float 基准数值**；其它量化档 / 快路径档一律写入 `card.notes`。Breeze 的 7.7 / 14.4 GiB 只是研究用途参考值，**不进入商用部署预算**。

---

## 1. 三层扩展点：ModelCard / BackendSpec / BaseHandler

系统把「模型」拆成三层，各自的职责边界互不重叠，改哪一层取决于你要加什么：

| 层 | 定义位置 | 职责 | 何时改 |
|---|---|---|---|
| `ModelCard` | `model_registry.py`（结构）、`models/builtin.py`（内置清单） | **元信息**：名称 / 类型 / 版本 / repo / 权重格式 / 显存 / 许可 / 状态 / 加载参数声明 | 只加元信息、只想让模型可被查询 / 被 `models:` 覆盖时 |
| `BackendSpec` | `backend_registry.py`（`STT_BACKENDS` / `LLM_BACKENDS` / `TTS_BACKENDS`，共 31 条） | **后端构造**：`name` / `kind` / `config_type` / `create_handler`（handler factory）/ `config_prefix` / `normalize_config` / `required_extra` / `capabilities` / `models` | 要真正把某个模型跑起来（可被 `--stt` / `--llm_backend` / `--tts` 或 YAML `blocks.*.backend` 选中）时 |
| `BaseHandler` | `baseHandler.py`（`BaseHandler[InT, OutT]`）、各 `STT/`、`TTS/`、`LLM/` 目录下的 Handler | **推理契约**：`setup()` / `process() -> Iterator` / `cleanup()` / `on_session_end()`，以及输入 / 输出队列与音频格式 | 实现新模型的加载与推理逻辑时 |

**`ModelCard` 是纯声明**：frozen dataclass，不加载权重、不 import 任何 handler 模块，也不驱动加载。实际参数链路仍是

```
config_type dataclass → spec.normalize() → setup_kwargs → BaseHandler.setup()
                                  ↑
                    ModelCard（旁路元信息，不参与）
```

因此 `normalize_dataclass_config()` 的 `config_prefix` 前缀剥离与 `gen_kwargs` 合并逻辑保持单一事实来源；card 的 `default_load_params` 只是声明与校验依据，Handler 不得绕过 `spec.normalize()` 自行拼参数。

**`BackendSpec` 是构造入口**：`create_handler` 是一个 `(HandlerContext, Mapping[str, Any]) -> Any` 的 factory；`HandlerContext` 携带 `stop_event`、四个队列、`should_listen`、`cancel_scope`、`speculative_turns`、`pipeline_index`、`sample_rate` 等管线本地状态。仓库内的 `_simple_handler_factory()` / `_load_handler()` 保持**延迟导入**——注册表构建期不会 import 任何 STT/TTS/LLM handler 模块。`capabilities`（`bypasses_transcription_notifier` / `supports_audio_input` / `supports_llm_proxy` / `streams_audio_chunks`）影响 stage 组装而非后端选择。

**`BaseHandler` 是运行时契约**：构造函数调用 `setup(*setup_args, **setup_kwargs)`，`run()` 在独立线程里循环消费 `queue_in`、把 `process()` yield 出的结果放入 `queue_out`，`cleanup()` 负责收尾并投递 `PIPELINE_END`。

**最小改动结论**：新增一个可运行的模型 = **一个参数 dataclass + 一个 Handler + 一条带 `models` 的 `BackendSpec`**。只加元信息（例如先把模型登记为 `planned` 供查询）则**只写 card**，不碰 Handler 与注册表；`planned` / `deprecated` card 允许指向尚未实现的 `backend_name`，`validate()` 不会因此报错。

---

## 2. 最小改动清单与「禁止手改」清单

### 2.1 必改文件

| 文件 | 改动 |
|---|---|
| `src/speech_to_speech/STT/<name>_handler.py`（或 `TTS/` / `LLM/`） | 新增 `BaseHandler` 子类，实现 `setup()` / `process()` / `cleanup()`；遵守 §4 音频契约 |
| `src/speech_to_speech/arguments_classes/<name>_arguments.py` | 新增参数 dataclass。**字段名必须与 `BackendSpec.config_prefix` 对齐**：`normalize_dataclass_config()` 会剥掉 `f"{config_prefix}_"` 前缀，`gen_` 前缀字段会被合并进 `gen_kwargs`。例如 `config_prefix="qwen3_tts"` 对应 `qwen3_tts_device` / `qwen3_tts_blocksize` |
| `src/speech_to_speech/backend_registry.py` | ① 顶部 import 新参数类；② 在对应 `STT_BACKENDS` / `LLM_BACKENDS` / `TTS_BACKENDS` 列表**追加**一条 `BackendSpec`（设置 `name` / `kind` / `config_type` / `create_handler` / `config_prefix`，按需 `required_extra` / `capabilities` / `models`） |
| `src/speech_to_speech/models/builtin.py` | 在 `builtin_model_cards()` 追加 `ModelCard`（或把 card 直接放进 `BackendSpec.models`）；字段规范见 §3 |

`BackendSpec` 的 `models: tuple[ModelCard, ...] = ()` 是带默认值、位于所有既有字段之后的可选字段，因此**不得改写现有 31 条构造**。

### 2.2 条件项（只有满足条件才改）

- `pyproject.toml`：新后端依赖第三方包时新增 optional extra，并把名字填进 `BackendSpec.required_extra`。`create_backend_handler()` 会把 `ImportError` 包装成 `pip install "speech-to-speech[<extra>]"` 提示。
- `config.py` 的 `_PATH_FIELDS`：新增参数若是本地文件路径、需要 `~` 展开与存在性检查时才加入（例如 `qwen3_tts_gguf_talker_path`）。
- `docs/parameter-catalog.yaml`：参数目录同步（文档性质，不影响运行）。
- `config/prod.yaml`：仅当生产默认值需要变化时改；本框架默认不改。
- `docker-compose*.yml`：仅当部署编排需要新挂载 / 新环境变量时改；本框架默认不改（见 §9 兼容性红线）。

### 2.3 自动派生，**禁止手改**

这三处全部从三张注册表推导，手工编辑会破坏「单一事实来源」，并直接违反 §9 兼容性红线：

- `arguments_classes/module_arguments.py` 的 **CLI choices**：`"choices": tuple(STT_BACKENDS)` / `tuple(LLM_BACKENDS)` / `tuple(TTS_BACKENDS)`，以及 `s2s_pipeline.py` 里预解析器的 `--stt` / `--llm_backend` / `--tts` choices。新增后端后 choices 自动扩展，不用加一行代码。
- `s2s_pipeline.py` 的**参数类拼装**：`HfArgumentParser` 由 `VADHandlerArguments` + `*(spec.config_type for spec in selected_specs)` 组成，随后 `spec.normalize(...)` 生成 `BackendSelection`。
- `config.py` 的 **YAML 校验**：`registries[kind][backend].config_type` 决定 `blocks.*.settings` 的合法键（错误提示 `"Choose an existing registered backend."`）；`models:` 段的 `default_load_params` 合法性由 `load_param_types(model_id)`（即 `config_type` 的类型提示）决定。

同理，`cli.py` 的 `models list` 只读 `list_models()` 与三张注册表，新增 card / 后端后输出自动变化，无需手改。

---

## 3. ModelCard 填写规范

### 3.1 13 个字段（`model_registry.py`）

`@dataclass(frozen=True)`；前 7 个必填，其余有默认值。

| 字段 | 类型 | 默认值 / 约束 |
|---|---|---|
| `id` | `str` | 必填 |
| `name` | `str` | 必填 |
| `kind` | `ModelKind = Literal["stt", "llm", "tts"]` | 必填；必须与 `BackendSpec.kind` 一致 |
| `version` | `str` | 必填；不接受空串，用权重目录 / HF revision 语义 |
| `provider` | `str` | 必填 |
| `weight_format` | `WeightFormat = Literal["safetensors", "gguf", "mlx", "remote"]` | 必填；`remote` 时 `repo_id=None` |
| `backend_name` | `str` | 必填；`status="available"` 时必须存在于对应注册表 |
| `repo_id` | `str \| None` | `None`；HF repo 或本地目录 |
| `default_load_params` | `Mapping[str, Any]` | `{}`；键必须是关联 `config_type` 的字段名 |
| `min_vram_gb` | `float \| None` | `None`；**单一基准数值**（默认加载配置下单路峰值 GiB） |
| `license` | `str \| None` | `None`；未核实一律填 `None`，**禁止猜测** |
| `status` | `ModelStatus = Literal["available", "planned", "deprecated"]` | `"available"` |
| `notes` | `str` | `""`；写「同源组件非品牌模型」、量化档、必备子目录、许可提示 |

### 3.2 填写规则

- **状态机**：`planned → available → deprecated`。`planned` = 元信息已登记、适配层（Spec B）未实现；`available` = 已实现且 `backend_name` 已注册；`deprecated` = 保留可查询但不再推荐。`unregistered` 只是 CLI 行标签，**不是** `ModelStatus`，不得写进 `status`。
- **命名**：`id` 用小写连字符（如 `qwen3-asr-1.7b-hf`），全局唯一；`register()` 对重复 id 抛 `ModelRegistryError`。
- **`min_vram_gb` 只填一个数**：其它量化档 / 快路径档写入 `notes`。例如 `qwen3.5-4b-transformers` 填 `8.0`（FP16），把「4bit NF4 约 2.1 GB」写进 `notes`；`minicpm-homologous-qwen3-8b` 填 `16.0`，把「Q8 约 8.5 GB / Q4 约 5.0 GB」写进 `notes`。`None` 表示**未申报**，不是占位符，`models list --json` 输出 `null`。
- **未核实字段一律 `None` 并在 `notes` 说明**：`minicpm-2b` / `minicpm-4b` 的 `repo_id` 留 `None` 待 Spec B 核实；`qwen3-tts-1.7b-customvoice` 的 `license` 为 `None`。
- **同源组件必须标注「非品牌独立模型」**：MiniCPM-o 4.5 是单一端到端 omni checkpoint，没有官方独立 ASR/TTS/LLM 权重；`whisper-medium` / `cosyvoice2` / `minicpm-homologous-qwen3-8b` 的 `provider` 与 `notes` 必须写明「MiniCPM-o 同源组件，非 MiniCPM 品牌独立模型」，避免误导。
- **`validate()` 一次性收集全部冲突**：id 唯一、`kind` 与 backend 一致、`available` 的 `backend_name` 已注册、`default_load_params` 键名属于 `config_type` 字段；失败抛 `ModelRegistryError`。

### 3.3 查询 / 解析 API 与当前目录

- `get_model(model_id)`：**不做状态检查**，返回 card。供 `config.py` 校验 `models:` 段、生成 pipeline 局部的 card 副本（`dataclasses.replace`），也供仅做元信息查询的调用方。
- `resolve_model(model_id)`：对 `planned` 抛 `ModelNotAvailableError`，消息为 `Model ... is planned; its adapter layer is Spec B. See docs/model-integration-guide-CN.md section 3.`——即**本指南 §3**；对 `deprecated` 返回 card（**不阻断**），但许可告警必须随该状态暴露：`cli.py` 的 `models list` 在 stderr 打印「商用场景禁止自托管」告警，部署文档同步记录（见 §5）。此外 `config.py` 会拒绝把 `deprecated` card 通过 `repo_id` 覆盖指向自托管权重（`Deprecated non-commercial weights cannot be configured`）——**deprecated card 可查询，但绝不能指向自托管权重**。
- 当前 9 张 card（§9 用 `models list` 核对）：
  - `available`（3）：`qwen3-asr-1.7b-hf`、`qwen3-tts-1.7b-customvoice`、`qwen3.5-4b-transformers`。
  - `planned`（5）：`whisper-medium`、`cosyvoice2`、`minicpm-homologous-qwen3-8b`、`minicpm-2b`、`minicpm-4b`。
  - `deprecated`（1）：`breeze-tts-2`（D7 商用禁用自托管）。

---

## 4. Handler 契约（音频 / 打断 / 透传）

### 4.1 生命周期

`setup(*setup_args, **setup_kwargs)` 加载权重并初始化；`process(input) -> Iterator[OutT]` 逐项产出；`cleanup()` 释放资源；`on_session_end()` 处理软重置。`run()` 负责队列循环、`PIPELINE_END` 与 `stop_event`。TTS Handler 一般经 `setup_should_listen=True` 把 `should_listen` 事件注入 `setup_args`。

### 4.2 音频契约（**不可协商**）

- **STT 输入**：`VADAudio`，其中 `VADAudio.audio` 是 **16 kHz** 单声道 **float32** numpy 数组（见 `pipeline/messages.py`、`pipeline/handler_types.py` 的 `STTIn = VADAudio`）。
- **TTS 输出**：**16 kHz int16 PCM 小端**（`<i2`），每块 **512 samples**（各参数类 `*_blocksize` / `*_chunk_size` 默认 512）；响应结束时 yield 哨兵 `AUDIO_RESPONSE_DONE = b"__RESPONSE_DONE__"`。
- `should_listen` **仅在 `EndOfResponse` 之后恢复**，不得在音频块中途打开麦克风。
- `CancelScope` / `SpeculativeTurnTracker` 依据 `cancel_generation` / `turn_id` / `turn_revision` 丢弃陈旧轮（`should_process_input()`），避免上一轮音频串到新一轮。
- 语言码（`language` / `detect_llm_output_language`）与 `speaker_attribution`（`VADAudio.speaker_attribution`）必须原样透传，不得在 Handler 内丢失或伪造。

### 4.3 商用路径专项

- **路径 L（本地商用 TTS，默认推荐）**：用 `FunAudioLLM/CosyVoice2-0.5B`（或其权重许可未通过时的 Apache-2.0 `phonon` CPU 兜底）填 Breeze 的 TTS 位。**先核对 CosyVoice2 输出采样率**，不是 16 kHz 就重采样；再切成 512 samples 的 int16 小端块并补 `AUDIO_RESPONSE_DONE`。仓内 `cosyvoice_tts_arguments.py` 已有 `cosyvoice_tts_chunk_size=512`，`TTS/cosyvoice_handler.py` 存在但**尚未注册**。代码仓库 LICENSE 已核实为 Apache-2.0，**权重许可须在标 `available` 前核对**。
- **路径 R（BreezeBlue 付费托管 API，可选）**：基址 `https://api.breeze.blue/v1`，鉴权头 `xi-api-key: $BREEZE_API_KEY`。这是 **BreezeBlue 自有协议，不是 OpenAI 兼容 `/v1/audio/speech`**，因此不能直接复用 `--tts openai` 后端。优先用 Realtime WebSocket TTS（默认 `pcm`，24 kHz mono，面向 voice agent / barge-in）；HTTP 另有 `wav_24000` / `wav_48000` / mp3。Handler 必须完成：mp3/wav 解码 → 24 kHz/48 kHz → 16 kHz 重采样 → 512 samples 块切分 → `AUDIO_RESPONSE_DONE`；同时处理网络超时、重连与打断（打断时取消在途请求、丢弃已排队音频）。单次 HTTP 请求有字符上限、中文非流式会自动分段，须计入端到端延迟。
- **仅研究用途参考**：Breeze 本地权重的 Voice Clone / Voice Design / Voice Direction 三模式、vocal events 内联标记（`(laugh)` / `[笑]`）、`--revision` 固定权重版本、官方 24 kHz mono s16le 输出、本地流式 API 单并发忙时 `409`、H100 + 预热 fast path 的 TTFA/RTF 指标——**均不作为商用实现或验收依据**（D7 禁止自托管）。

两条路径的共同出口都是 **16 kHz int16 PCM / 512 samples 块 + `AUDIO_RESPONSE_DONE`**，且不得把官方 H100 低延迟指标直接写进本仓验收线。

---

## 5. 错误约定

| 异常 / 场景 | 约定 |
|---|---|
| `ModelWeightsMissingError` | Spec A 只约定**接口与消息格式**，异常类由 Spec B 的 Handler 实现。消息必须含 `repo_id`、必备子目录（研究用途下 Breeze checkpoint 自带 `audio_tokenizer/`）、以及下载 / 安装命令；**禁止静默回退到其他模型**。模板：`Weights for <repo_id> missing; required subdirs: <...>; install with: <download command>` |
| `ModelLicenseError` | 已在 `model_registry.py` 定义（`ModelRegistryError` 子类）。商用场景（D7）选中 `deprecated` 的自托管权重 card 时抛出，消息含许可名称（`BreezeBlue Research and Non-Commercial License`）与 §6.4 的路径 L / 路径 R 指引，**禁止静默回退到自托管权重**；触发点由 Spec B 的 Handler / `BackendSpec` 实现。配置层另有 `ConfigurationError` 拦截 `deprecated` card 的 `repo_id` 覆盖 |
| 远程 API 错误 | `401`（`xi-api-key` 无效 / 订阅失效）、`429` + `Retry-After`（退避重试）、连接 / 读取超时、`5xx`：一律转成可定位的错误并终止当前响应，不得吞掉异常继续播放静音或陈旧音频；打断时取消在途请求 |
| `required_extra` | `BackendSpec.required_extra` → `create_backend_handler()` 把 `ImportError` 包装为 `pip install "speech-to-speech[<extra>]"` 提示，见 §2.2 |
| `{env: NAME}` 缺失 | 沿用既有「缺失即报错、不回退默认」 |

**许可告警是硬性要求**：必须同时出现在**部署文档**与 `speech-to-speech models list` 输出中。当前实现由 `cli.py` 对 `status="deprecated"` 的 card 在 stderr 打印告警（含「商用场景禁止自托管」与路径 L / R 指引），`--json` 输出保留 `status=deprecated` 与 `license` 字段。

---

## 6. 显存与资源申报

- **`min_vram_gb` 是单一 float 基准数值**：默认加载配置下单路峰值 GiB。其它量化档 / 快路径档写入 `card.notes`（例如 `qwen3.5-4b-transformers` 的 4bit NF4、`minicpm-homologous-qwen3-8b` 的 Q8/Q4、`breeze-tts-2` 的 `--fast-all` 14.4 GiB）。
- **叠加规则**：现有管线单路实测底座 **4.6 GB（4633 MiB）**，并发公式为

  ```
  floor(可用显存GB × 0.85 ÷ 4.6)
  ```

  本机 RTX 5070 Ti Laptop 12 GB 上，S2S + Qwen3.5-4B Q4 已达 11878 MiB（仅余约 67 MiB），说明底座不可压缩、新增本地模型必须单独申报显存。
- **Breeze 的数字仅研究用途参考**：官方 eager 约 7.7 GiB、`--fast-all` 约 14.4 GiB，叠加 4.6 GB 管线后约 12.3 GB / 19 GB——**这些值不进入商用部署预算**（D7 禁止自托管 Breeze TTS 2 权重）。
- **商用路径**：路径 L 用 CosyVoice2 的**实测** `min_vram_gb`（Spec B 实测后填写，启动前为 `None`），兜底 Apache-2.0 `phonon` 为纯 CPU、本地显存近 0；路径 R 本地显存为 **0**（代价是付费、外网依赖、数据出域）。
- Spec B 必须为每个新模型申报 `min_vram_gb`，并在文档中给出「互斥选型 / 量化档 / 多卡」建议；Qwen3-8B FP16（约 16 GB）需 24 GB 卡或 Q4/Q8 量化。Spec A 只负责让这些数字可被注册与查询。

---

## 7. 一致性测试模板（Spec B 每个模型必须提供）

1. **card ↔ 参数类默认值一致**：`card.default_load_params` 的每个键都存在于 `load_param_types(card.id)`（即 `config_type` 的类型提示）中，值与 dataclass 默认值一致；`validate()` 会先做键名校验，测试再补值一致性断言。
2. **音频契约**：STT 输入采样率 16000 + float32；TTS 输出 16000 + int16 小端 `<i2`；每块 **512 samples**；结尾恰有一个 `AUDIO_RESPONSE_DONE`；`should_listen` 只在 `EndOfResponse` 后恢复；`CancelScope` / `SpeculativeTurnTracker` 能丢弃陈旧轮。**必须覆盖 24 kHz → 16 kHz 重采样正确性**（采样数按 2/3 收敛、无削波 / 无越界、尾部不足一块时正确补块），以及 mp3/wav 解码路径。
3. **权重缺失报错**：构造缺失权重目录，断言抛 `ModelWeightsMissingError` 且消息含 `repo_id`、必备子目录、下载命令；并断言**没有**回退到其它模型。
4. **许可闸门报错**：商用场景下选中 `deprecated` 自托管 card 断言抛 `ModelLicenseError`（消息含许可名与路径 L / 路径 R）；`models:` 段给它写 `repo_id` 断言抛 `ConfigurationError`；`models list` 的 stderr 含许可告警。
5. **registry 延迟导入不被破坏**：import `model_registry` / `models.builtin` / `backend_registry` 后，`sys.modules` 中不得出现任何 STT/TTS/LLM handler 模块（`_load_handler()` 必须保持惰性）。

**最小回归命令**：

```
pytest tests/test_model_registry.py -q
```

配合 `pytest tests/test_model_config_overrides.py -q` 与 `pytest tests/test_backend_registry.py -q` 覆盖 card、配置覆盖与注册表兼容性。所有测试不触网、不下载权重、不加载真实模型、不占 GPU。

---

## 8. Spec B 模型示例（草稿，尚未落地）

> 以下均为 **Spec B 示意**，不是当前仓库代码。当前 9 张 card 在 `models/builtin.py`；`BackendSpec.models` 是可选的双写位置，二选一即可，避免 `register()` 重复 id。

### 8.1 路径 L：CosyVoice2（新 TTS 后端）

`TTS/cosyvoice_handler.py`（`CosyVoiceTTSHandler`）与 `cosyvoice_tts_arguments.py`（`CosyVoiceTTSHandlerArguments`）已在仓内但未注册，只需追加一条 `BackendSpec`：

```python
# backend_registry.py 顶部新增 import
from speech_to_speech.arguments_classes.cosyvoice_tts_arguments import CosyVoiceTTSHandlerArguments

# TTS_BACKENDS 追加
BackendSpec(
    "cosyvoice2",
    "tts",
    CosyVoiceTTSHandlerArguments,
    _simple_handler_factory(
        "speech_to_speech.TTS.cosyvoice_handler",
        "CosyVoiceTTSHandler",
        setup_should_listen=True,
        context_kwargs=True,
    ),
    config_prefix="cosyvoice_tts",
    required_extra="cosyvoice",
    models=(ModelCard(
        id="example-tts", name="CosyVoice2", kind="tts", version="2",
        provider="Alibaba / MiniCPM-o 同源", weight_format="safetensors",
        backend_name="cosyvoice2", repo_id="FunAudioLLM/CosyVoice2-0.5B",
        min_vram_gb=None, license=None, status="planned",
        notes="MiniCPM-o 4.5 同源组件，非品牌独立模型；路径 L 的 Breeze 替代位；权重许可核对通过前不得标 available。",
    ),),
),
```

> **两条注册路径按 id 互斥**：card 既可以在 `models/builtin.py` 的 `builtin_model_cards()` 里登记，也可以放进 `BackendSpec.models`；`bind_model_cards()` 在导入时把两处的 card 一并注册到同一目录。**同一个 `id` 只能走其中一条路径**——两处同时出现相同 `id`（例如内置已登记的 `cosyvoice2`）会由 `register()` 抛 `ModelRegistryError`。因此本示例把 card id 取为 `example-tts`，与内置 card 不冲突，可安全复制。

权重下载命令（核对权重许可后执行）：

```
huggingface-cli download FunAudioLLM/CosyVoice2-0.5B --local-dir cache/CosyVoice2-0.5B
modelscope download --model iic/CosyVoice2-0.5B --local_dir cache/CosyVoice2-0.5B
```

兜底：`phonon`（`gradium/phonon-31m-en`，Apache-2.0，纯 CPU 流式）已注册，无需新 `BackendSpec`。

### 8.2 已注册后端下的变体：Whisper-medium / Qwen3-8B / MiniCPM-2B·4B

这四张 card 的 `backend_name` 分别指向**已注册**的 `whisper` / `transformers`，属于「后端下的模型变体」，**不需要新建 `BackendSpec`**：在 `builtin.py` 登记 card 后，用 YAML `models:` 覆盖 `default_load_params` 即可切换权重目录（`stt_model_name` / `llm_model_name` 等键必须是对应 `config_type` 的字段）。示意草稿：

```python
# 变体绑定示意：沿用既有 BackendSpec，仅补 card（Spec A 的 31 条构造逐字不改）
ModelCard(id="whisper-medium", name="Whisper-medium", kind="stt", version="medium",
          provider="OpenAI / MiniCPM-o 同源", weight_format="safetensors",
          backend_name="whisper", repo_id="openai/whisper-medium", status="planned",
          notes="MiniCPM-o 4.5 同源组件，非 MiniCPM 品牌独立模型。")

ModelCard(id="minicpm-homologous-qwen3-8b", name="Qwen3-8B（MiniCPM-o 同源 LLM）",
          kind="llm", version="3-8b", provider="Alibaba Qwen / MiniCPM-o 同源",
          weight_format="safetensors", backend_name="transformers",
          repo_id="Qwen/Qwen3-8B", min_vram_gb=16.0, status="planned",
          notes="同源组件，非品牌独立模型；Q8 约 8.5 GB / Q4 约 5.0 GB 写入 notes。")

# minicpm-2b / minicpm-4b 同理：backend_name="transformers"，repo_id=None 待核实
```

对应的 `BackendSpec` 草稿与 §8.1 完全同形，只是把构造参数换成既有后端的组合：Whisper-medium 用 `WhisperSTTHandlerArguments` + `_simple_handler_factory("speech_to_speech.STT.whisper_stt_handler", "WhisperSTTHandler", attach_speculative_turns=True)` + `config_prefix="stt"`；Qwen3-8B / MiniCPM-2B·4B 用 `LanguageModelHandlerArguments` + `_create_local_llm("transformers")` + `config_prefix="llm"`；四者都把各自的 card 放进 `models=(...)`，并让 card 的 `backend_name` 与新后端名一致。是否单建后端由 Spec B 决定，**本文推荐复用既有 `whisper` / `transformers` 后端**（上面「仅补 card」方案），这样 Spec A 的 31 条构造保持逐字不改。

权重下载命令：

```
huggingface-cli download openai/whisper-medium --local-dir cache/whisper-medium
huggingface-cli download Qwen/Qwen3-8B --local-dir cache/Qwen3-8B
# MiniCPM-2B / MiniCPM-4B 的确切 repo id 由 Spec B 核实后再补下载命令
```

### 8.3 路径 R：`breeze-tts-2-hosted` 远程 card

新建 `breeze-tts-remote` Handler + 参数 dataclass + `BackendSpec`，并注册一张 `weight_format="remote"` 的 card：

```python
BackendSpec(
    "breeze-tts-2-hosted",
    "tts",
    BreezeHostedTTSHandlerArguments,
    _simple_handler_factory(
        "speech_to_speech.TTS.breeze_hosted_handler",
        "BreezeHostedTTSHandler",
        setup_should_listen=True,
        context_kwargs=True,
    ),
    config_prefix="breeze_hosted_tts",
    capabilities=BackendCapabilities(streams_audio_chunks=True),
    models=(ModelCard(
        id="breeze-tts-2-hosted", name="Breeze TTS 2 (hosted)", kind="tts",
        version="2", provider="BreezeBlue", weight_format="remote",
        backend_name="breeze-tts-2-hosted", repo_id=None,
        min_vram_gb=0.0, license=None, status="planned",
        notes="https://api.breeze.blue/v1；xi-api-key；Realtime WebSocket TTS (pcm, 24 kHz mono) / wav_24000；"
              "非 OpenAI 兼容协议；输出须解码 + 24/48 kHz→16 kHz 重采样 + 512 samples 块切分；"
              "商用授权以官方 ToS 与有效付费订阅为准，须由用户/法务确认。",
    ),),
),
```

该 card 本地显存 0、`repo_id=None`（权重不出域在服务端），输出格式常为 `pcm` / `wav_24000` / `wav_48000` / mp3；`xi-api-key` 从环境变量注入，不写进代码。

### 8.4 `deprecated` 反例：`breeze-tts-2`

```python
ModelCard(
    id="breeze-tts-2", name="Breeze TTS 2", kind="tts", version="2",
    provider="BreezeBlue", weight_format="safetensors",
    backend_name="breeze-tts-2", repo_id="BreezeBlue/Breeze-TTS-2",
    min_vram_gb=7.7, license="BreezeBlue Research and Non-Commercial License",
    status="deprecated",
    notes="商用场景（D7）禁用自托管；--fast-all 14.4 GiB 仅研究用途参考；"
          "商用按 §6.4 走路径 L（CosyVoice2）或路径 R（breeze-tts-2-hosted）。",
)
```

**本指南不为该 `deprecated` 本地 card 提供任何下载 / 安装命令**：D7 禁止自托管 Breeze TTS 2 权重，Spec B 不得实现其本地权重加载 Handler。它只作为「许可闸门 + 状态机」的反例存在。

---

## 9. 验收清单

### 9.1 命令（CI 同款）

```
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/
pytest tests/ -x -q
```

其中 `ruff check src/ tests/` 与 `ruff format --check src/ tests/` 覆盖新增的 Handler、参数类与测试；`mypy src/` 校验 `BackendSpec` / `ModelCard` 的类型；`pytest tests/ -x -q` 为全量回归。最小回归另见 §7 的 `pytest tests/test_model_registry.py -q`。

### 9.2 兼容性红线（逐字不改）

- **31 条 `BackendSpec(...)` 构造逐字不改**（`STT_BACKENDS` 15 / `LLM_BACKENDS` 4 / `TTS_BACKENDS` 12）；新增后端只能追加，不能重写既有条目。
- **三个 CLI choices 与默认值不变**：`--stt`（默认 `parakeet-tdt`）、`--llm_backend`（默认 `transformers`，macOS 为 `mlx-lm`）、`--tts`（默认 `qwen3`）的 choices 仍由三张注册表派生。
- `config/prod.yaml` 与 **9 个 compose 文件**（`docker-compose*.yml`）内容不变；`example_configs/*` 不因本框架改动；`module_arguments.py` / `s2s_pipeline.py` / `config.py` 的派生逻辑禁止手改（§2.3）。
- `models list` 必须输出 **3 `available` / 5 `planned` / 1 `deprecated` / 27 `unregistered`** 行；`--json` 可解析、`null` 语义正确、`deprecated` 行带许可告警；`unregistered` 行不虚构版本 / 许可 / 显存。

### 9.3 交付验收点

1. 本指南含 §1–§9 全部九节、无占位内容；`resolve_model()` 的 `ModelNotAvailableError` 消息指向本文档 §3。
2. 一个带 `models:` 覆盖的示例 YAML 可被 `resolve_config()` 正确解析，且不影响未覆盖的 pipeline。
3. 全部测试不触网、不下载权重、不加载真实模型、不占用 GPU。
4. §9.1 四条命令全绿，既有 `test_backend_registry.py` / `test_config.py` / `test_configured_runtime.py` 零回归。

## 本次验收（Spec A）

> 本节记录 Spec A（Task 1–7）在本 checkout 上的实际验收结果。命令均在仓库根目录
> `speech-to-speech-src` 下执行，工具取自 `.venv/Scripts/`：Python 3.14.0、
> ruff 0.17.2、mypy 2.4.0、pytest 9.1.1。逐字输出见 `.git/sdd/task-7-report.md`。
> 验收基线为首个实现提交 `d6d5f55` 的父提交 **`4c4bb4d`**。

### 仓库级四条命令（Global Constraints 同款）

| 命令 | 退出码 | 实际结果 | 归类 |
| --- | --- | --- | --- |
| `ruff check src/ tests/` | 0 | `All checks passed!` | 通过（仓库级干净） |
| `ruff format --check src/ tests/` | 1 | `19 files would be reformatted, 289 files already formatted` | **基线**：19 个文件均为本分支未改动的既有格式问题（含 `cli.py`，见下） |
| `mypy src/` | 1 | `Found 17 errors in 7 files (checked 162 source files)` | **基线**：7 个文件全部与本分支无关 |
| `pytest tests/ -x -q` | 1 | 前 220 项通过后，IDE `sitecustomize.py` tmpdir `PermissionError` 中断 | **基线**：既有失败 + IDE 环境问题，非本分支引入 |

**基线明细（未隐藏、未修复、未格式化无关文件）：**

- `ruff format --check` 的 19 个文件：`LLM/provider_errors.py`、`LLM/responses_api_language_model.py`、`STT/sensevoice_handler.py`、`TTS/cosyvoice_handler.py`、`TTS/qwen3_tts_handler.py`、`api/openai_realtime/websocket_router.py`、`arguments_classes/*`(2)、`pipeline/turn_latency.py`、`utils/model_monitor.py`、`cli.py`、`tests/openai_realtime/*`(4)、`tests/test_console_*.py`(3)、`tests/test_qwen3_tts_handler_backend.py`。
  - 其中 `src/speech_to_speech/cli.py:344` 是本分支修改文件，但该 `if any(...)` 代码块是 `git diff 4c4bb4d -- src/speech_to_speech/cli.py` 中**未改动的上下文行**（无 `+`/`-`）。对基线版本 `4c4bb4d:src/speech_to_speech/cli.py` 单独运行 `ruff format --check`，同样报 `1 file would be reformatted`（基线 `cli.py:268`，同样的 `if any(...)`）。行号从 268 平移到 344 仅因本分支新增 `_run_models_command()`（+76 行）。故归类为**基线**，本分支未引入新的格式问题。
- `mypy src/` 的 17 个错误分布在 `LLM/utils.py`、`pipeline/console.py`、`utils/model_monitor.py`、`api/openai_realtime/voice_controls.py`、`LLM/language_model.py`、`LLM/responses_api_language_model.py`、`api/openai_realtime/websocket_router.py`，均非本分支 6 个源码文件。
- `pytest tests/ -x -q`（原样）：`pytest_sessionfinish` 清理 `C:\Users\...\AppData\Local\Temp\pytest-of-joezxh\pytest-current` 时被 IDE 注入的 `D:\devtools\CodeBuddy\...\sitecustomize.py` 拦截，抛 `PermissionError: [WinError 5] 拒绝访问。`。改带仓库内 `--basetemp` 后重跑：`1 failed, 220 passed, 1 skipped, 2 warnings in 57.55s`，首个失败为 `tests/openai_realtime/test_conversation_delete.py::test_generated_assistant_is_deletable_by_wire_id`（`IndexError`），与本分支无关。
- 不带 `-x`、带仓库内 `--basetemp` 的完整回归：`248 failed, 2975 passed, 12 skipped, 10 warnings, 3 errors in 306.20s`。其中 `tests/test_config.py` 恰有 **4 个 Windows 专有基线失败**：`test_schema_references_paths_and_provider_error_redaction`、`test_collection_environment_and_failed_home_expansion`、`test_config_path_home_expansion_is_safe`、`test_parser_size_and_depth_boundaries`。全量 `FAILED`/`ERROR` 清单中**不含** `test_model_registry.py`、`test_model_config_overrides.py`、`test_backend_registry.py`、`test_configured_runtime.py`。

### 本分支文件聚焦检查（全部通过）

检查范围恰为 6 个源码 + 2 个测试：`src/speech_to_speech/model_registry.py`、`models/__init__.py`、`models/builtin.py`、`backend_registry.py`、`config.py`、`cli.py`、`tests/test_model_registry.py`、`tests/test_model_config_overrides.py`。

| 检查 | 退出码 | 结果 |
| --- | --- | --- |
| `ruff check <8 files>` | 0 | `All checks passed!` |
| `ruff format --check <8 files>` | 1 | `1 file would be reformatted, 7 files already formatted`（仅 `cli.py:344`，已证实为基线平移，见上） |
| `mypy <8 files>` | 0 | `Success: no issues found in 8 source files` |

> 按 Global Constraints「不得格式化无关文件 / 不得修改计划外既有文件」，未对 `cli.py` 运行 `ruff format`；该唯一失败显式归类为 pre-existing baseline。

聚焦测试（Python 3.14，带仓库内 `--basetemp` 规避 IDE tmpdir 错误）：

| 命令 | 结果 | 退出码 |
| --- | --- | --- |
| `pytest tests/test_model_registry.py -q` | **17 passed** | 0 |
| `pytest tests/test_model_config_overrides.py -q` | **10 passed** | 0 |
| `pytest tests/test_backend_registry.py -q` | **96 passed**, 1 warning | 0 |
| `pytest tests/test_configured_runtime.py -q` | **49 passed** | 0 |

> `test_backend_registry.py` 的 1 条 warning 是 Python 3.14 下 torch 的 `torch.jit.script` DeprecationWarning，属环境基线噪声、非测试失败。
> 原样执行 `pytest tests/test_model_config_overrides.py -q` 时测试本体 10/10 通过，但 `pytest_sessionfinish` 触发同一 IDE tmpdir `PermissionError`（退出码 1）；加 `--basetemp` 后退出码 0、无噪声。

### CLI 验收

```
python -m speech_to_speech.cli models list
python -m speech_to_speech.cli models list --kind tts --json
```

- `models list` 共 **36 行数据**：**3 `available` / 5 `planned` / 1 `deprecated` / 27 `unregistered`**（9 张 card + 27 行 `unregistered`），与 §9.2 一致；退出码 0。
- stderr 出现许可告警：`Warning: breeze-tts-2 is deprecated: BreezeBlue Research and Non-Commercial License. 商用场景禁止自托管；…`（`--json` 模式同样输出）。
- `--kind tts --json` 输出经 `ConvertFrom-Json` 解析成功：`PARSE_OK=True ROWS=14`，其中 `available=1 / deprecated=1 / planned=1 / unregistered=11`，全部 `kind=tts`；`null` 语义正确。

### 兼容性红线核对

- `git diff 4c4bb4d -- src/speech_to_speech/backend_registry.py` 仅 3 处 `+`：顶部 `from speech_to_speech.model_registry import ModelCard, bind_model_cards`、`BackendSpec` 类体 `models: tuple[ModelCard, ...] = ()`、文件末尾 `bind_model_cards({"stt": ..., "llm": ..., "tts": ...})`。**没有任何 `BackendSpec(...)` 构造被改写**（31 条逐字不变）。
- `git diff 4c4bb4d -- config/prod.yaml docker-compose.yml docker-compose.local.yml docker-compose.thirdparty.yml` 输出**为空**（长度 0），退出码 0。
- `git diff --name-status 4c4bb4d HEAD` 共 11 个文件：新增 `docs/model-integration-guide-CN.md`、`example_configs/models-overrides.yaml`、`src/speech_to_speech/model_registry.py`、`src/speech_to_speech/models/__init__.py`、`src/speech_to_speech/models/builtin.py`、`tests/test_model_config_overrides.py`、`tests/test_model_registry.py`；修改 `docs/superpowers/plans/2026-11-10-s2s-model-registry.md`、`src/speech_to_speech/backend_registry.py`、`src/speech_to_speech/cli.py`、`src/speech_to_speech/config.py`。

### 资源与网络确认

**确认**：本次全部测试与 CLI 验收**未下载任何模型权重**、**未加载任何真实模型**、**未占用 GPU**、**未发起任何网络调用**。模型目录全程为内存中的 `ModelCard` 元数据与注册表绑定；`planned` / `deprecated` card 无权重加载路径；测试使用桩 / mock 与本地临时文件，不触网。

> 结论：本分支 6 个源码 + 2 个测试文件在 `ruff check`、`mypy` 与聚焦测试上全绿；`ruff format --check` 的唯一失败已证实为基线平移。四条仓库级命令的失败全部归类为 pre-existing baseline（未隐藏、未修复、未格式化无关文件）。CLI 验收计数与兼容性红线均符合 §9.2。
