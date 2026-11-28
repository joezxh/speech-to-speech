# S2S 部署参数清单（按 VAD / STT / LLM / TTS 分组）

> 本文件是「S2S 部署参数配置平台」参数单一事实来源的**人读版**；机器可读镜像见
> [`parameter-catalog.yaml`](./parameter-catalog.yaml)，平台设计见
> [`superpowers/specs/2026-10-23-s2s-deployment-parameter-platform-design.md`](./superpowers/specs/2026-10-23-s2s-deployment-parameter-platform-design.md)。
> YAML 语法与校验语义以 [`configuration.md`](./configuration.md) 为准，本文不复制其内容。
> 按**实际环境与现象**组织的参数组合手册（GPU 档位、边缘盒、噪声环境、弱网等）见
> [`deployment-tuning-playbook.md`](./deployment-tuning-playbook.md)；单旋钮怎么改仍见 [`model-pipeline.md`](./model-pipeline.md) §6。
>
> **§2–§7 是 pipeline 部署参数；§8 是控制台自己的运行开关（索引式覆盖）。**
> 机器可读文件 [`parameter-catalog.yaml`](./parameter-catalog.yaml) 里另有一段 `console_parameters`：
> 那是**控制台自己的运行开关**（探针节奏、LB 开关、路径、上限……），键集合与
> `console/backend/app/config/_schema.py` 的登记表双向一致，由
> `console/backend/scripts/validate_catalog_schema.py` 把关；它不进部署页的参数树。
> 本文 §8 只做生效方式与改造评估的索引，字段定义仍以 YAML 与登记表为准。

- 目录版本：`s2s-parameter-catalog-v1` / 人读版结构 `catalog-md-v2`
- 覆盖范围：`speech-to-speech-src` 启动参数通道 + 会话运行时通道 + 容器编排 + 客户端
- 取值基线：源码 `src/speech_to_speech/**` + 实际生效配置 [`config/prod.yaml`](../config/prod.yaml) + `silero-vad` 6.2.3 官方资料 + `fireredvad` 0.0.2 / `FireRedTeam/FireRedVAD` 官方资料
- 本次变化：**取消 A 层通用 / B 层后端的两段式结构**，改为 `VAD → STT → LLM → TTS → 平台公共` 的组件分组；暴露分级、来源优先级、生效方式、影响面、变更代价等元数据从「表 B」降级为参数行内的属性列；同时按注册表校正了后端名与控制台可选清单。
- 最近一次增补（生效方式专项）：新增 §7，把 170 行按「运行时可改 8 / 必须重启 162」重新切分，并对 162 个仅重启参数逐行给出可行性分级（高 22 / 中 54 / 低 44 / 不可行 42）与具体改造建议；新增 §8 补齐控制台 61 个配置项（56 hot / 5 startup）及 5 个重启项的评估；§2–§6 的参数行与取值**未改动**。
- 最近一次 VAD 补充：`firered` 的依赖包、权重目录、帧参数换算与热更新边界落到 §2.5；**参数条数不变，仍是 22 条**（`firered` 复用 `thresh` / `min_silence_ms` / `speech_pad_ms` / `sample_rate`，只新增了原本已登记的 2 个专属参数）。

---

## 0. 阅读指南

### 0.1 章节地图

| 章 | 内容 | 归属 | 参数条数 |
|---|---|---|---|
| §1 | 当前生产栈 + 各组件的可选项清单 | 总览 | — |
| §2 | VAD：检测、轮次判定、Smart Turn、FireRed | `blocks.vad.settings` | 22 |
| §3 | STT：Qwen3-ASR 及 14 个可选后端 | `blocks.stt.settings` | 6（深挖）|
| §4 | LLM：chat-completions / responses-api / 本地后端 | `blocks.llm.settings` | 28 |
| §5 | TTS：Qwen3-TTS 及 11 个可选后端 | `blocks.tts.settings` | 23（深挖）|
| §6 | 平台公共：监听、并发、超时、音频、设备、鉴权、日志、环境、配置文件、容器、客户端 | `runtime.*` / `pipelines.*.options` / compose | 91 |
| §7 | 生效方式总览 + 162 个「仅重启参数」逐项改造评估 | 全量横向索引 | 170（索引，不新增） |
| §8 | 控制台自身 61 个配置项 + 5 个重启项评估 | `console_parameters` | 61（索引，不新增） |
| 附录 A | 三条端到端样例（重启 / 热更新 / 回滚） | — | — |
| 附录 B | 与 `configuration.md` 的分工 | — | — |
| 附录 C | 计数、溯源与命名对照 | — | — |

### 0.2 参数属性列语义

每章内每张表都是「一行一个参数 + 属性列」：

| 列 | 含义 |
|---|---|
| 参数 | YAML `settings` 中的字段名；`〔只读〕` 表示源码常量、不可配置 |
| 作用 | 这个参数改变的是什么行为 |
| 默认 / 范围 | 默认值 + 合法取值，两者合并显示；`固定` 表示无配置入口 |
| 来源 | 该值的优先级链，取值词汇见 §0.4 |
| 生效 | `启动` / `热更新` / `启动+热更新` / `容器` / `固定`，语义见 §0.5 |
| 暴露 | `basic` / `advanced` / `expert` / `ops`，判定见 §0.3 |
| 影响面 · 代价 | `作用域 · 改完需要付出什么`，如 `会话级 · 重启` |
| 风险 / 副作用 | 改错的直接后果；`ops` 级必须标明风险类别（安全 / 隐私 / 环境绑定）|
| 锚点 | `文件:行号` 溯源，省略目录前缀 |

### 0.3 暴露分级判定

| 级别 | 判定条件 | 含义 |
|---|---|---|
| `basic` | 无安全风险、改坏不影响启动与安全、面向业务语义 | 普通用户在默认页直接可改 |
| `advanced` | 影响延迟 / 资源 / 并发，需要理解系统 | 高级页可见，带数值建议 |
| `expert` | 设备 / 精度 / 后端选择，配错会 OOM 或启动失败 | 折叠展示 + 警告 |
| `ops` | 安全敏感或环境绑定，暴露给用户会引发事故 | 仅运维可见，必须写明风险类别 |

`ops` 级风险类别固定三选一（或组合）：**安全**（未鉴权暴露、密钥）、**隐私**（对话内容留存）、**环境绑定**（端口 / GPU / 镜像 / 路径）。

两处例外说明：

- 风险列标「环境绑定」但暴露仍为 `advanced` 的（如客户端 `input_device` / `output_device`），是「只影响单机调试、改错可自愈」的条目；`ops` 专指**暴露给普通用户会造成服务级事故**的条目。
- 只读常量（`〔只读〕`）一律归 `ops` 或 `expert`，因为它们改不了——列出来是为了让读者知道「这条别找配置项」。

### 0.4 来源优先级（全表统一）

1. 显式 YAML 字段值（最高）——写作 `YAML > env > 默认`
2. `{env: NAME}` 环境变量引用（缺失即报错，**不回退默认**）——写作 `env > 默认`
3. dataclass 默认值（最低）
4. 覆盖型开关：`device` 覆盖组件 `*_device`；`mac_optimal_settings` 提供预设，显式字段再覆盖预设
5. 运行时会话：`session.update` 覆盖已解析的会话字段（真正生效的只有 4 组：`instructions`；`turn_detection` 的 `threshold` / `silence_duration_ms` / `create_response` / `interrupt_response`；转录语言；`extensions`——另有 `audio.output.voice` 条件生效；详见附录 A.2）
6. `固定`：源码常量或编排文件写死，平台不可配置

### 0.5 生效方式取值

| 取值 | 含义 |
|---|---|
| `启动` | 进程启动时 argparse / dataclass 固化，只能重启 |
| `热更新` | 仅经 `session.update` 在会话内可改 |
| `启动+热更新` | 启动值作默认，会话可覆盖（会话结束后恢复启动值）|
| `容器` | 需重建容器 |
| `固定` | 无入口 |

---

## 1. 当前栈与可选项

> 速查汇总（STT / LLM / TTS 三组件横评，明细见 §1.3–§1.5 与 §3–§5，数据以 `parameter-catalog.yaml` 为准）：
>
> | 维度 | STT | LLM | TTS |
> |---|---|---|---|
> | 注册后端数 | 15（含 `none` 直通） | 4 | 12 |
> | 当前生产 | `qwen3-asr` 0.6B（`cuda` / `bfloat16` / `zh` / `gen_max_new_tokens=128`） | `chat-completions` → GPUStack `Qwen3-8B` | `qwen3` 1.7B-CustomVoice（`backend=torch` / `cuda` / 句内流式） |
> | 本清单深挖参数 | 6（§3.2） | 28（§4.2–§4.4） | 23（§5.2） |
> | 其余后端字段 | 专属字段见 §3.3 | 远端 §4.3 + 本地 §4.4 | 专属字段见 §5.3 |
> | 密钥字段 | `openai_stt_api_key`（隐式回退 `OPENAI_API_KEY`） | `responses_api_api_key`（只写不读，回显 `***`） | `openai_tts_api_key` / `drama3_api_key` / `minimax_tts_api_key`（同回退） |
> | 会话可热更新项 | 转录语言（`qwen3_asr_language` 启动值 + `session.update` 覆盖） | `instructions` | `speaker` / `voice`（仅 `qwen3` 命中支持列表与 `kitten` 生效，见 §5.4） |
> | 未注册陷阱 | `sensevoice`（应为 `sense-voice`）、`openai_compatible`（应为 `openai`） | — | `cosyvoice`（改走 `openai` 接远端服务） |

### 1.1 当前生产栈（`config/prod.yaml` + compose）

| stage | 后端 | 权重 / 服务 | 关键设置 | 备注 |
|---|---|---|---|---|
| VAD | `silero` | `silero-vad` 6.2.3 JIT（随仓库内置，本地 `torch.hub` 加载） | `thresh=0.6`（默认）、`min_silence_ms=450`、`smart_turn=false` | 判停靠纯静音；Smart Turn 权重仍预置但未启用 |
| STT | `qwen3-asr` | `cache/qwen3-asr-0.6b-hf`（Qwen3-ASR 0.6B） | `cuda` / `bfloat16` / `language=zh` / `gen_max_new_tokens=128` | 1.7B 曾实测 RTF 0.57，故降到 0.6B |
| LLM | `chat-completions` | GPUStack 上的 `Qwen3-8B` | `responses_api_stream=true`、`reasoning_effort=""`、`stream_batch_sentences=1` | 远端 OpenAI 兼容网关，非本地权重 |
| TTS | `qwen3` | `cache/qwen3-tts-model`（Qwen3-TTS-12Hz-1.7B-CustomVoice） | `backend=torch`、`cuda`、`non_streaming_mode=false`、`streaming_chunk_size=4` | 句内流式，压低首音延迟 |
| 判停增强 | Smart Turn v3.2（可选） | `pipecat-ai/smart-turn-v3` CPU ONNX | `smart_turn=false` | 关闭后不再走 ONNX 推理 |

> `config/prod.yaml` 是本地 Windows 运行版本（模型路径指向仓库 `cache/`）；容器部署走 `docker-compose.*.yml` 的 CLI 旗标，不读这个文件。

### 1.2 VAD 可选项

本仓 `--vad` 只有两个合法取值（`vad_arguments.py:9`），其余为生态候选、需自行适配。

| 组件 | 类型 | 本项目状态 | 资源 | 适用 |
|---|---|---|---|---|
| `silero`（Silero VAD） | JIT / ONNX，流式，~260K 参数 | **当前在用** | CPU，单线程 30ms 块 <1ms | 通用、离线、极低占用 |
| `firered`（FireRedVAD Stream-VAD） | DFSMN，流式，10 ms 帧，~0.57M 参数（fp32 ≈2.2 MB） | 已接入，未启用（缺 `fireredvad` 包 + Stream-VAD 权重） | CPU（2.2 MB 权重，单帧 <1 ms）或 GPU | 多语种 + 歌声/音乐场景，误警 2.69% 明显低于 Silero |
| Silero v6 ONNX / sequence ONNX / half | 同族变体 | 未使用（仓库内已带权重） | CPU | 换加载方式即可切换，见 §2.1 |
| TEN-VAD | 轻量 C++/ONNX | 未接入 | CPU | 低延迟边缘端 |
| FunASR FSMN-VAD | 中文优化 | 未接入 | CPU | 中文会议；漏检低但误警率偏高 |
| WebRTC VAD | GMM，零依赖 | 未接入 | CPU 极低 | 仅作粗门控，不适合判停 |
| Picovoice Cobra | 商用授权 | 未接入 | CPU | 需商业授权 |

生态 VAD 横向指标（FireRedASR2S 论文，FLEURS-VAD-102，9,443 条人工标注）：

| 指标 | FireRedVAD | Silero-VAD | TEN-VAD | FunASR-VAD | WebRTC-VAD |
|---|---|---|---|---|---|
| AUC-ROC ↑ | 99.60 | 97.99 | 97.81 | — | — |
| F1 ↑ | 97.57 | 95.95 | 95.19 | 90.91 | 52.30 |
| 误警率 ↓ | 2.69 | 9.41 | 15.47 | 44.03 | 2.83 |
| 漏检率 ↓ | 3.62 | 3.95 | 2.95 | 0.42 | 64.15 |

> 换 VAD 会改变判停手感与延迟构成，平台侧应把 `vad` 归 `expert` 而不是 `basic`：`firered` 需要额外依赖与权重目录，缺省会直接启动失败。

`firered` 的落地三件套缺一不可（安装命令、权重清单与目录布局见 §2.5.1）：

| 前置条件 | 内容 | 缺失后果 |
|---|---|---|
| Python 包 | `fireredvad` 0.0.2，连带 `kaldi-native-fbank` / `kaldiio` / `textgrid` | `ImportError: FireRedVAD is not installed`（`firered_vad_iterator.py:255-261`）|
| 权重目录 | `Stream-VAD/` 下的 `cmvn.ark` + `model.pth.tar` | `from_pretrained` 失败，启动即崩 |
| 配置项 | `backend: firered` + `vad_firered_model_dir` | `ValueError: --vad firered requires --vad_firered_model_dir` |

### 1.3 STT 可选项（`STT_BACKENDS`，16 个）

| 后端名 | 实现 | 前缀 / 关键字段 | 额外依赖 | 选型要点 |
|---|---|---|---|---|
| `qwen3-asr` | Qwen3-ASR | `qwen3_asr_*` | 内置 | **当前在用**；0.6B 低延迟、多语种、可强制语言 |
| `parakeet-tdt` | NeMo Parakeet TDT 0.6B v3 | `parakeet_tdt_*` | 内置 | CLI 默认；`enable_live_transcription` 推荐搭配 |
| `parakeet-unified` | NeMo 另一 checkpoint | `parakeet_unified_*` | `nemo` | 与 `parakeet-tdt` 权重/前缀都不同 |
| `nemotron-streaming` | NeMo 流式家族 | `nemotron_streaming_*` | `nemo` | 真流式；与 diarization 同源 |
| `orukeet` | NeMo checkpoint 三件套 | `orukeet_*` | `nemo` | 需 checkpoint 文件名 + revision |
| `whisper` | HF Whisper | `stt_*`（注意前缀是 `stt`） | 内置 | 支持 beam / timestamps，延迟高于 parakeet |
| `whisper-mlx` | mlx-whisper | `stt_*` | `whisper-mlx` | 仅 Apple Silicon |
| `mlx-audio-whisper` | mlx-audio | `mlx_audio_whisper_*` | 内置 | 仅 Apple Silicon，另一套 MLX 实现 |
| `faster-whisper` | CTranslate2 | `faster_whisper_stt_*` | `faster-whisper` | CPU 友好，可调 `compute_type` |
| `paraformer` | ModelScope Paraformer | `paraformer_stt_*` | `paraformer` | 中文专用，无语言参数 |
| `sense-voice` | SenseVoiceSmall | `sense_voice_stt_*` | `sensevoice` | 多语种 + 情感/事件标签 |
| `openai` | 远端 `/audio/transcriptions` | `openai_stt_*` | 内置 | 托管服务；支持切窗 |
| `openai-realtime` | Realtime 协议 | `openai_realtime_stt_*` | 内置 | 流式音频块（`streams_audio_chunks`） |
| `vllm-realtime` | vLLM Realtime | `vllm_realtime_stt_*` | 内置 | 同上，面向自建 vLLM |
| `none` | 直通 | — | — | 跳过转写，音频直送支持音频输入的 LLM |
| `zerogpu` | ZeroGPU 托管 | `zerogpu_*` | `zerogpu` | Hugging Face Space 运行时的远端占位后端 |

### 1.4 LLM 可选项（`LLM_BACKENDS`，5 个）

| 后端名 | 接口 | 能力标记 | 额外依赖 | 选型要点 |
|---|---|---|---|---|
| `chat-completions` | OpenAI Chat Completions | `supports_audio_input`、`supports_llm_proxy` | 内置 | **当前在用**；本仓 compose 用它打 GPUStack |
| `responses-api` | OpenAI Responses | `supports_llm_proxy` | 内置 | 官方 Responses 语义，无音频输入标记 |
| `transformers` | 本地 HF 权重 | — | 内置 | 可 8bit / 4bit 量化，显存可控 |
| `mlx-lm` | 本地 MLX | — | `mlx-lm` | macOS 默认；Linux 上会加载失败 |
| `zerogpu` | ZeroGPU 托管 | `supports_llm_proxy` | `zerogpu` | Hugging Face Space 运行时的远端占位后端 |

可挂接的外部模型（通过 `model_name` 透传，名称须与网关注册名完全一致）：`Qwen3-8B`（当前）、`Qwen/Qwen3.5-4B`（本地默认）、`gpt-5.6-terra`（兼容后端默认，**不支持音频输入**）。

### 1.5 TTS 可选项（`TTS_BACKENDS`，15 个）

| 后端名 | 类型 | 前缀 / 关键字段 | 额外依赖 | 选型要点 |
|---|---|---|---|---|
| `qwen3` | Qwen3-TTS（ggml / torch / MLX） | `qwen3_tts_*` | 内置 | **当前在用**；CustomVoice / VoiceDesign / Base 三类权重 |
| `openai` | 远端 OpenAI 兼容 | `openai_tts_*` | 内置 | 支持 vLLM-Omni 流式扩展 |
| `kokoro` | 轻量本地 | `kokoro_*` | `kokoro` | 音色多、CPU 可跑 |
| `kitten` | 轻量本地 | `kitten_*` | `kitten` | 参数极少，支持会话改音色 |
| `pocket` | 轻量本地 | `pocket_tts_*` | `pocket` | 有 temperature / eos 阈值 |
| `supertonic` | 轻量本地 | `supertonic_tts_*` | `supertonic` | 4 参数，语言码驱动音色 |
| `phonon` | 本地预览 | `phonon_tts_*` | `phonon` | 量化 + 线程数，语言加载时固定 |
| `chatTTS` | 对话式 | `chat_tts_*` | `chattts` | 参数极少，会话式韵律 |
| `facebookMMS` | 多语种 MMS | `facebook_mms_*` + `tts_language` | 内置 | 语言码决定音色 |
| `omnivoice` | 零样本克隆 | `omnivoice_*` | `omnivoice` | 参考音频路径属 `_PATH_FIELDS` |
| `drama3` | 云端 API | `drama3_*` | 内置 | 需密钥，含采样参数 |
| `minimax` | 云端 API | `minimax_tts_*` | 内置 | 需密钥，含 vol / pitch |
| `cosyvoice2` | 零样本克隆 | `cosyvoice2_*` | `cosyvoice` | 需参考音频；路径 L 的可选替代 |
| `voxcpm` | VoxCPM2 2B / VoxCPM1.5 / 0.5B | `voxcpm_tts_*` | `voxcpm` | 原生 48/44.1/16 kHz，统一重采样到 16 kHz；30 语言自动识别；`voxcpm` 仅支持 Python < 3.13 |
| `zerogpu` | ZeroGPU 托管 | `zerogpu_*` | `zerogpu` | Hugging Face Space 运行时的远端占位后端 |

### 1.6 注册表偏差（有代码但**不可选**）

以下实现存在于源码，但**未注册进 `backend_registry`**，写成 `backend:` 会被配置校验直接拒绝。平台的可选清单不得包含它们：

| 残留实现 | 文件 | 正确替代 |
|---|---|---|
| `cosyvoice` | `TTS/cosyvoice_handler.py`、`cosyvoice_tts_arguments.py` | 用 `openai` 接远端 CosyVoice2 服务 |
| `sensevoice`（无连字符） | `STT/sensevoice_handler.py`、`sensevoice_stt_arguments.py` | 用已注册的 `sense-voice` |
| `openai_compatible`（旧名） | — | STT 用 `openai`，TTS 用 `openai` |

---

## 2. VAD 参数

### 2.1 当前组件与模型档案（Silero VAD）

| 项 | 值 | 来源 |
|---|---|---|
| 包 / 仓版本 | `silero-vad` 6.2.3（v6 权重） | `silero-vad/pyproject.toml:6` |
| 模型体量 | `silero_vad`，约 260K 参数，流式 | 官方 Wiki「Available models」|
| 采样率 | 8000 / 16000 Hz（16000 的整数倍会被降采样到 16k） | 官方 README + `utils_vad.py:378` |
| 推理窗口 | 16k → 512 samples（32ms）；8k → 256 samples | `utils_vad.py:381` |
| 单块耗时 | 30+ms 音频块在单 CPU 线程 <1ms（ONNX 可再快 4–5 倍） | 官方 README 性能段 |
| 权重格式 | JIT（`silero_vad.jit`，默认）+ ONNX（`silero_vad.onnx`，opset 16） | `hubconf.py:26-49`、`src/silero_vad/data/` |
| 仓库内其他权重 | `silero_vad_16k_op15.onnx`、`silero_vad_half.onnx`、`silero_vad_16k_sequence.onnx`、`silero_vad_op18_ifless.onnx`、`silero_vad_openvino_16k.onnx`、`silero_vad_16k.safetensors` | 同上（`hubconf` 只接 JIT 与 opset 15/16 两个 ONNX，其余需改 `vad_handler.py`）|
| 加载方式 | `torch.hub.load(repo, "silero_vad", source="local")`：优先 `SILERO_VAD_REPO_PATH` → `/opt/silero-vad`（容器只读卷）→ 仓库内 `silero-vad/` | `VAD/vad_handler.py:152-178` |
| 判定迟滞 | 退出阈值 = `threshold - 0.15`（本项目 iterator 内写死，官方为 `max(threshold-0.15, 0.01)`） | `VAD/vad_iterator.py:149,162,168` |
| 空闲复位 | 连续 500ms 低于退出阈值即 `model.reset_states()`，避免把噪声带进下一句 | `VAD/vad_iterator.py:6,151` |

> `vad_handler` 不做重采样：`sample_rate` 必须与上游音频流一致，否则判停直接失准。

### 2.2 检测核心参数

| 参数 | 作用 | 默认 / 范围 | 来源 | 生效 | 暴露 | 影响面 · 代价 | 风险 / 副作用 | 锚点 |
|---|---|---|---|---|---|---|---|---|
| `vad` | VAD 后端选择器 | `silero`；`silero` / `firered` | `YAML > 默认` | 启动 | expert | 管线级 · 重启 | `firered` 需可选依赖 + 权重目录，缺省启动失败 | `vad_arguments.py:6` |
| `thresh` | 语音活动判定阈值 | `0.6`；0–1 浮点 | `YAML > env > 默认` | 启动+热更新 | advanced | 管线级 · 重启 / 会话内即时 | 过高漏检句首，过低误触噪音；直接影响断句 | `vad_arguments.py:22` |
| `sample_rate` | VAD 采样率 | `16000`；8000 / 16000（模型硬约束） | `YAML > env > 默认` | 启动 | advanced | 管线级 · 重启 | 超出 8000/16000 直接抛 `ValueError`；**`firered` 只接受 16000**，8000 也在构造期抛错；与音频流不一致会判停失准 | `vad_arguments.py:28` |
| `min_silence_ms` | 判定句末所需的最短静音 | `64`（本仓生产 `450`）；非负整数 ms | `YAML > env > 默认` | 启动+热更新 | basic | 会话级 · 重启 / 会话内即时 | 过小频繁断句（慢语速被切碎），过大迟钝；每轮都摊进响应延迟 | `vad_arguments.py:34` |
| `min_speech_ms` | 有效语音段最短长度 | `384`；非负整数 ms | `YAML > env > 默认` | 启动 | basic | 会话级 · 重启 | 过大会吞掉「嗯」「好」这类短应答 | `vad_arguments.py:40` |
| `min_speech_continuation_ms` | 续说轮重开的语音时长（滞回） | `192`；钳制到 `[100, min_speech_ms]`，`0` 关闭 | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 与 `min_speech_ms` 配合；过大导致续说被当成新一轮 | `vad_arguments.py:46` |
| `max_speech_ms` | 连续语音强制切分上限 | `inf`（YAML `null` 等价）；正数 ms 或 `inf` | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 过小会把长段落硬切断；默认不切 | `vad_arguments.py:52` |
| `speech_pad_ms` | 触发前保留并回补的音频窗口 | `500`；非负整数 ms | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 过小切掉首字（尤其爆破音），过大引入额外静音延迟 | `vad_arguments.py:58` |
| `audio_enhancement` | 启用降噪 / 均衡（DeepFilterNet） | `false`；布尔 | `YAML > env > 默认` | 启动 | advanced | 管线级 · 重启 | 未装 `df` 包时只记错误日志并自动关闭；开启后增加 CPU | `vad_arguments.py:64` |

### 2.3 轮次判定与渐进转写

| 参数 | 作用 | 默认 / 范围 | 来源 | 生效 | 暴露 | 影响面 · 代价 | 风险 / 副作用 | 锚点 |
|---|---|---|---|---|---|---|---|---|
| `speculative_reopen_ms` | 软结束轮保留可重开窗口 | `800`；非负 ms，`0` 关闭 | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 过大会重复转写、重复气泡；本仓生产设 `0` 规避 | `vad_arguments.py:80` |
| `unanswered_reopen_ms` | 未被回答的软结束轮重开上限 | `7000`；非负 ms | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 实际值 = `max(speculative_reopen_ms, unanswered_reopen_ms, smart_turn_max_wait_ms)`，过大拖慢提交 | `vad_arguments.py:86` |
| `short_segment_merge_ms` | 短片段拼留时长 | `0`；非负 ms，`0` 关闭 | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | **必须 `>= min_silence_ms`**，否则 hold 会先于相邻片段到期而拼接失效（`docker-compose.local.yml:70,78`）；开启会增加起播前的拼接等待 | `vad_arguments.py:92` |
| `enable_realtime_transcription` | 说话中渐进释放音频做实时转写 | `false`；布尔 | `YAML > pipleline.options > 默认` | 启动 | advanced | 管线级 · 重启 | 产生大量 partial 事件与重复风险，弱网抬高带宽 | `vad_arguments.py:70` |
| `realtime_processing_pause` | 渐进音频分块间隔 | `0.5`；正浮点（秒） | `YAML > env > 默认` | 启动 | advanced | 管线级 · 重启 | 间隔过小抬高算力与事件量 | `vad_arguments.py:74` |

### 2.4 Smart Turn v3.2（语义判停增强）

模型档案：`pipecat-ai/smart-turn-v3`，`smart-turn-v3.2-cpu.onnx`，16 kHz，最多 8 秒音频，ONNX CPU 推理，使用 Whisper feature extractor；只在 VAD（`silero` 或 `firered`）判出语音→静音边界后调用，因此不给每块音频加负载，也不区分 VAD 后端（`VAD/smart_turn.py:20-24,37`）。

| 参数 | 作用 | 默认 / 范围 | 来源 | 生效 | 暴露 | 影响面 · 代价 | 风险 / 副作用 | 锚点 |
|---|---|---|---|---|---|---|---|---|
| `smart_turn` | 是否启用 Smart Turn 判停 | `true`（本仓生产 `false`）；布尔 | `YAML > env > 默认` | 启动 | basic | 会话级 · 重启 | 关闭后退回纯静音判停，交互更「硬」但更可预测 | `vad_arguments.py:98` |
| `smart_turn_model_path` | 本地 ONNX 路径 | `None`（缺省联网下载 v3.2）；路径 | `YAML > env > 默认` | 启动 | ops | 管线级 · 重启 | **环境绑定**：容器内路径；缺省会联网下载，离线环境启动卡住 | `vad_arguments.py:104` |
| `smart_turn_threshold` | 轮次完成概率阈值 | `0.5`；0–1 浮点 | `YAML > env > 默认` | 启动 | expert | 会话级 · 重启 | 越高越倾向等待，容易显得迟钝；越界直接抛异常 | `vad_arguments.py:110` |
| `smart_turn_max_wait_ms` | 不完整轮的推测重开宽限 | `2000`；正整数 ms | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 必须 `>0`，否则启动报错；过大拖慢提交 | `vad_arguments.py:116` |
| `smart_turn_incomplete_delay_ms` | 判定不完整后延迟 STT/LLM | `600`；`>=0` 整数 ms | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 必须 `>=0`；在 `max_wait` 窗口内执行，过大浪费窗口 | `vad_arguments.py:122` |
| `smart_turn_cpu_count` | ONNX 每路推理线程数 | `1`；正整数 | `YAML > env > 默认` | 启动 | advanced | 管线级 · 重启 | 线程过多与 VAD、CPU STT 抢核 | `vad_arguments.py:128` |

### 2.5 FireRed VAD（可选后端）

`--vad` 的第二个合法取值，**与 Silero 不是同一套判停机制**：Silero 每 512 samples（32 ms）一块、带 `threshold-0.15` 负阈值迟滞；FireRed 直接消费包内的流式起始/结束事件（400 samples 滑窗、160 samples 跳，即 **10 ms 帧**，前视阶 0 保证因果），本项目只负责 PCM 缓冲、前缀回补与轮次切分（`VAD/firered_vad_iterator.py:11-12,28-58`）。

#### 2.5.1 依赖与权重

| 项 | 值 | 证据 |
|---|---|---|
| Python 包 | `fireredvad` 0.0.2（可选 extra 名 `fireredvad`，与包名同名） | `pyproject.toml:75-77` |
| 传递依赖 | `kaldi-native-fbank` 1.22.4（fbank 特征，不依赖 torchaudio）、`kaldiio` 2.18.1（读 `cmvn.ark`）、`textgrid` 1.6.1（包内离线评测用，随依赖带入） | `uv.lock:1835-1849` |
| 无需重复安装 | `torch`（GPU 需 CUDA 轮子）、`numpy`、`soundfile` 已随主包安装 | — |
| 权重 | `FireRedTeam/FireRedVAD`（ModelScope 镜像 `xukaituo/FireRedVAD`）的 `Stream-VAD/`：`cmvn.ark` 1.31 kB + `model.pth.tar` 2.28 MB | HF 仓库文件列表、官方 README |
| 模型体量 | DFSMN ×8，hidden 256 / proj 128，回溯阶 20、前视阶 0，~0.57M 参数 | FireRedASR2S 论文 FireRedVAD 节 |
| 采样率 | **只支持 16000**；8000 在 iterator 构造期抛 `ValueError` | `VAD/firered_vad_iterator.py:40-41` |
| 帧结构 | 400 samples 窗 / 160 samples 跳（16 kHz 下 25 ms 窗、10 ms 帧） | `VAD/firered_vad_iterator.py:11-12` |
| 输入幅度 | 上游音频是 [-1, 1] 浮点，进模型前 `×32768` 还原成 int16 PCM 量纲（fbank 按 int16 训练） | `VAD/firered_vad_iterator.py:149-167` |
| 加载 | `FireRedStreamVad.from_pretrained(model_dir, config)` | `VAD/firered_vad_iterator.py:247-269` |

安装（容器 / 离线机需先把 wheel 装进镜像）：

```bash
pip install "speech-to-speech[fireredvad]"     # 或直接 pip install fireredvad
# 国内镜像：--index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

权重目录必须形如（`vad_firered_model_dir` 指到 `Stream-VAD` 这一层，不是它的父目录）：

```text
/root/.cache/fireredvad/Stream-VAD/
├── cmvn.ark
└── model.pth.tar
```

```bash
modelscope download --model xukaituo/FireRedVAD --local_dir ./cache/fireredvad          # 国内推荐
huggingface-cli download FireRedTeam/FireRedVAD --include "Stream-VAD/*" --local-dir ./cache/fireredvad
```

> **不要写 `pip install "fireredvad[gpu]"`**：该 extra 会把 `torch` 当依赖重新解析，可能把镜像里已锁定的 CUDA 轮子换成 CPU / PyPI 默认版本；GPU 推理只需 `vad_firered_use_gpu: true` + 现成的 CUDA torch。

#### 2.5.2 参数

| 参数 | 作用 | 默认 / 范围 | 来源 | 生效 | 暴露 | 影响面 · 代价 | 风险 / 副作用 | 锚点 |
|---|---|---|---|---|---|---|---|---|
| `vad_firered_model_dir` | Stream-VAD 权重目录（含 `cmvn.ark` 与 `model.pth.tar`） | `None`；路径（`~` 展开；**相对路径按 YAML 所在目录解析**，不是 CWD） | `YAML > env > 默认` | 启动 | ops | 管线级 · 重启 | **环境绑定**：`vad=firered` 时必填，缺失抛 `ValueError`；指到父目录或路径拼错则 `from_pretrained` 失败、启动即崩 | `vad_arguments.py:14` |
| `vad_firered_use_gpu` | FireRedVAD 是否用 GPU | `false`；布尔 | `YAML > env > 默认` | 启动 | expert | 管线级 · 重启 | 占 GPU 显存，与 STT/TTS 争抢；2.2 MB 权重在 CPU 上单帧 <1 ms，除高并发外收益有限 | `vad_arguments.py:18` |

#### 2.5.3 本项目参数 ↔ FireRed 官方参数

左列是包内 `FireRedStreamVadConfig` 的字段，右列是本项目唯一的暴露面。**两边的默认值不同，切后端后必须重新标定**：

| 官方参数 | 本项目参数 | 换算 / 透传 | 本项目生效值 | 官方 README 示例 | 差异说明 |
|---|---|---|---|---|---|
| `speech_threshold` | `thresh` | 直传；`vad_handler` 同时改写 `streamer.config` 与 `streamer.postprocessor` | `0.6` | `0.4` | 本项目更保守；FireRed 本身误警低，可回调到 0.4–0.5 换取句首召回 |
| `min_silence_frame` | `min_silence_ms` | `round(ms / 10)` | `64`（生产 `450` → 45 帧） | `20`（200 ms） | 与 Silero 同名同义，但**单位换成 10 ms 帧**，非整数毫秒会被取整 |
| `pad_start_frame` | `speech_pad_ms` | `round(ms / 10)` | `500` → 50 帧 | `5`（50 ms） | 本项目默认值对 FireRed 偏大：段首会多带最多 500 ms 静音；想贴近官方应设 50–100 |
| `use_gpu` | `vad_firered_use_gpu` | 直传 | `false` | `false` | — |
| `smooth_window_size` | 〔只读〕 | 未传，走包默认 | 包默认 | `5` | 概率平滑窗口，无配置入口 |
| `min_speech_frame` | 〔只读〕 | 未传，走包默认 | 包默认 | `8` | 有效语音最短长度由上层 `min_speech_ms`（384 ms）把关 |
| `max_speech_frame` | 〔只读〕 | 未传，走包默认 | 包默认 | `2000` | 强制切分走上层 `max_speech_ms` |
| `chunk_max_frame` | 〔只读〕 | 未传，走包默认 | 包默认 | `30000` | 离线整段处理用，流式路径不触发 |
| `detect_full` / 时间戳输出 | — | 只调 `detect_chunk` 取帧事件 | — | — | 本项目不产出 VAD 时间戳，段边界由 `VadIterator` 与 STT 缓冲决定 |

官方字段来源：`FireRedVAD` README「Streaming VAD / Python API Usage」；本项目透传点：`VAD/firered_vad_iterator.py:247-269`。

### 2.6 官方参数 ↔ 本项目参数（Silero）

Silero 官方（`VADIterator` / `get_speech_timestamps`）与本项目的对应关系；`firered` 的对照见 §2.5.3，两者坐标不同不可混用。**左列是本项目唯一暴露面，右列是官方默认，两者不总相同**：

| 官方参数 | 本项目参数 | 本项目默认 | 官方默认 | 差异说明 |
|---|---|---|---|---|
| `threshold` | `thresh` | `0.6` | `0.5` | 本项目略保守，减少噪声误触 |
| `sampling_rate` | `sample_rate` | `16000` | `16000` | 均只支持 8000 / 16000 |
| `min_silence_duration_ms` | `min_silence_ms` | `64`（生产 `450`） | `100` | 本参数是判停延迟的主来源，生产值按语速调 |
| `speech_pad_ms` | `speech_pad_ms` | `500` | `30` | 本项目语义为「触发前回补窗口」≈ OpenAI 的 `prefix_padding_ms` |
| `neg_threshold` | 〔只读〕 | `threshold-0.15` | `max(threshold-0.15, 0.01)` | 写死在 iterator 内，无配置项 |
| `window_size_samples` | 〔只读〕 | `512`（16k） | `512`（16k）/ `256`（8k） | 由采样率推导，官方已标 DEPRECATED |
| `model` | 〔只读〕 | 本地 JIT `silero_vad.jit` | JIT 或 ONNX | 换 ONNX 需改 `vad_handler.py`，不是配置项 |
| `min_speech_duration_ms` | `min_speech_ms` | `384` | `250` | 流式路径在上层实现，语义等价 |
| `max_speech_duration_s` | `max_speech_ms` | `inf` | `inf` | 单位从秒改毫秒 |
| `return_seconds` / `time_resolution` / `visualize_probs` / `progress_tracking_callback` | — | — | 官方离线接口专有 | 流式服务不产生时间戳输出，不适用 |
| `min_silence_at_max_speech` / `use_max_poss_sil_at_max_speech` | — | — | 官方离线切分策略 | 未实现；本项目在 `max_speech_ms` 处直接切 |

官方默认值来源：`silero-vad/README.md`、`src/silero_vad/utils_vad.py:281-296`（`get_speech_timestamps`）、`utils_vad.py:591-623`（`VADIterator`）、官方 Wiki「Version history and Available Models」。

### 2.7 调参矩阵

| 现象 | 先动参数 | 方向 | 连带影响 |
|---|---|---|---|
| 慢语速用户被切成两轮 | `min_silence_ms` | 调大（450 → 600–800） | 每轮响应延迟 +0.15–0.35s |
| 首字被吃掉（「八」「怕」开头） | `speech_pad_ms` | 调大（500 → 700） | 段首多带静音，STT 略慢 |
| 噪声/呼吸被判成语音 | `thresh` | 调大（0.6 → 0.65–0.7） | 轻声结尾可能漏检 |
| 短应答（「嗯」「好」）无响应 | `min_speech_ms` | 调小（384 → 250） | 噪声脉冲更容易触发 barge-in |
| 长独白不切段 | `max_speech_ms` | 设为 15000–30000 | 单段变长，STT 延迟线性上升 |
| 想压首音延迟 | `min_silence_ms` + `stream_batch_sentences` | 前者调小、后者设 1 | 断句更碎，可能误切 |
| 句尾语气词被截断 | 打开 `smart_turn` + 调 `smart_turn_threshold` | `0.5 → 0.55–0.6` | 多一次 ONNX 推理（约数十 ms CPU） |

> `firered` 下前四行的换算不同：`min_silence_ms` / `speech_pad_ms` 按 **10 ms 帧**取整（`round(ms/10)`），且 `speech_pad_ms` 同时充当包内 `pad_start_frame` 与本地前缀缓冲；官方示例值是 `speech_threshold=0.4`、`pad_start_frame=5`，与本仓 0.6 / 500 ms 差距较大。切后端后先按 §2.5.3 重新标定，再套这张表。

### 2.8 生效边界与热更新

| 场景 | 结果 | 证据 |
|---|---|---|
| `session.update` 带 `turn_detection.threshold` | 立即写入 `iterator.threshold`，下一块音频生效；`firered` 下同时改写 `streamer.config.speech_threshold` 与 `postprocessor.speech_threshold`（下一帧生效） | `VAD/vad_handler.py:249-251`、`VAD/firered_vad_iterator.py:78-84` |
| `session.update` 带 `turn_detection.silence_duration_ms` | 立即改写 `iterator.min_silence_samples`；`firered` 下换算成 `min_silence_frame = round(ms/10)` 并同步 postprocessor | `VAD/vad_handler.py:252-254`、`VAD/firered_vad_iterator.py:86-93` |
| 会话结束 | 恢复 `_configured_threshold` / `_configured_min_silence_samples`（启动值），`silero` 与 `firered` 同一套回滚路径 | `VAD/vad_handler.py:956-957` |
| 改 `min_speech_ms` / `speech_pad_ms` / Smart Turn 系列 | 只能重启，`session.update` 不认 | 无运行时写入点 |
| 改 FireRed 包内 `smooth_window_size` / `min_speech_frame` / `max_speech_frame` / `chunk_max_frame` | 只能改包默认或源码，本项目无配置入口（§2.5.3） | `VAD/firered_vad_iterator.py:262-267` |

---

## 3. STT 参数

### 3.1 当前组件档案

| 项 | 值 | 说明 |
|---|---|---|
| 后端 | `qwen3-asr` | 本地 transformers 推理，非流式（整段音频） |
| 权重 | `cache/qwen3-asr-0.6b-hf`（`Qwen/Qwen3-ASR-0.6B-hf` 的本地副本） | 容器内为 `/root/.cache/qwen3-asr-model-hf` |
| 设备 / 精度 | `cuda` / `bfloat16` | 显式写死，避免 `auto` 落到 CPU 或 fp32 |
| 语言 | `zh` | `auto` 会多花 token 做语言识别并多跑一轮 `decode(parsed)` |
| 生成长度 | `gen_max_new_tokens=128` | 默认 256 曾出现 47s / 53s 异常长尾 |
| 采样率 | 跟随 `PIPELINE_SAMPLE_RATE=16000` | 无独立采样率参数 |

### 3.2 参数表（`blocks.stt.settings`）

| 参数 | 作用 | 默认 / 范围 | 来源 | 生效 | 暴露 | 影响面 · 代价 | 风险 / 副作用 | 锚点 |
|---|---|---|---|---|---|---|---|---|
| `qwen3_asr_model_name` | 模型 ID 或本地目录 | `Qwen/Qwen3-ASR-0.6B-hf`；字符串 | `YAML > env > 默认` | 启动 | expert | 管线级 · 分钟级 | 换 checkpoint 需重下权重；容器内建议绝对路径，路径错启动失败 | `qwen3_asr_stt_arguments.py:7` |
| `qwen3_asr_device` | 运行设备 | `auto`（生产 `cuda`）；`auto` / `cuda` / `cpu` | `YAML > env > 默认` | 启动 | expert | 管线级 · 重启 | `auto` 在无 GPU 时落到 CPU，RTF 大幅上升 | `qwen3_asr_stt_arguments.py:17` |
| `qwen3_asr_torch_dtype` | 推理精度 | `auto`（生产 `bfloat16`）；`auto` / `float16` / `bfloat16` / `float32` | `YAML > env > 默认` | 启动 | expert | 管线级 · 重启 | `float32` 显存翻倍 | `qwen3_asr_stt_arguments.py:23` |
| `qwen3_asr_language` | 识别语言 | `auto`（生产 `zh`）；语言码或 `auto` | `YAML > env > 默认` | 启动+热更新 | basic | 会话级 · 重启 / 会话内即时 | `auto` 在短句上可能误判；会话内可被 `session.update` 的转录语言覆盖 | `qwen3_asr_stt_arguments.py:32` |
| `qwen3_asr_prompt` | 识别提示词（热词 / 标点） | `None`；字符串 | `YAML > env > 默认` | 启动 | advanced | 管线级 · 重启 | 提示词过长抬高每段延迟 | `qwen3_asr_stt_arguments.py:42` |
| `qwen3_asr_gen_max_new_tokens` | 单段最大生成 token | `256`（生产 `128`）；正整数 | `YAML > env > 默认` | 启动 | advanced | 管线级 · 重启 | 过小截断长句转写；过大放大失控生成长尾 | `qwen3_asr_stt_arguments.py:51` |

### 3.3 其他 STT 后端的关键字段

只列各后端**专属字段**；YAML 字段名前缀必须与其 arguments 前缀一致，混用会让配置校验报「未知字段」。

| 后端 | 专属字段（示例） | 必填 / 关键 | 备注 |
|---|---|---|---|
| `parakeet-tdt` | `parakeet_tdt_model_name`、`parakeet_tdt_device`、`parakeet_tdt_language` | 全部可选 | 无独立采样率，固定跟随 16000 |
| `parakeet-unified` | `parakeet_unified_model_name`、`parakeet_unified_device`、`parakeet_unified_language` | 模型名关键 | 与 `parakeet-tdt` 不同 checkpoint |
| `nemotron-streaming` | `nemotron_streaming_model_name`、`nemotron_streaming_device`、`nemotron_streaming_language` | 模型名关键 | 真流式，天然低延迟 |
| `orukeet` | `orukeet_model_name`、`orukeet_checkpoint_filename`、`orukeet_checkpoint_revision`、`orukeet_device`、`orukeet_language` | 三件套必填 | revision 固定可避免上游漂移 |
| `whisper` | `stt_model_name`、`stt_device`、`stt_torch_dtype`、`stt_compile_mode`、`stt_gen_num_beams`、`language` | `stt_model_name` | 前缀是 `stt`，不是 `whisper` |
| `whisper-mlx` | 同上（`stt_*`） | 同上 | 仅 Apple Silicon |
| `mlx-audio-whisper` | `mlx_audio_whisper_model_name`、`mlx_audio_whisper_gen_kwargs`、`language` | 模型名 | `gen_kwargs` 是字典，不是标量 |
| `faster-whisper` | `faster_whisper_stt_model_name`、`faster_whisper_stt_device`、`faster_whisper_stt_compute_type`、`faster_whisper_stt_gen_*` | 模型名、`compute_type` | `compute_type` 直接决定显存与速度 |
| `paraformer` | `paraformer_stt_model_name`、`paraformer_stt_device` | 模型名 | 中文专用，无语言参数 |
| `sense-voice` | `sense_voice_stt_model_name`、`sense_voice_stt_device`、`sense_voice_stt_language` | 模型名 | 与未注册的 `sensevoice` 是两个东西 |
| `openai` | `openai_stt_base_url`、`openai_stt_api_key`、`openai_stt_model`、`openai_stt_response_format`、`openai_stt_timeout`、`openai_stt_max_window_s` | `base_url` | 远端 `/audio/transcriptions`；密钥隐式回退 `OPENAI_API_KEY` |
| `openai-realtime` | `openai_realtime_stt_base_url`、`..._model`、`..._audio_sample_rate`、`..._connect_timeout`、`..._final_timeout` | `base_url`、`model` | 走 Realtime 协议；`stt_auto_reset_supported` 可能为 false |
| `vllm-realtime` | `vllm_realtime_stt_base_url`、`..._model`、`..._audio_sample_rate`、`..._connect_timeout`、`..._final_timeout` | 同上 | 面向自建 vLLM Realtime 服务 |

### 3.4 选型建议

| 目标 | 推荐 | 理由 |
|---|---|---|
| 中英混说、低延迟、可本地部署 | `qwen3-asr`（0.6B） | RTF 可控；支持强制语言减少额外解码 |
| 实时字幕（说话中就要出字） | `parakeet-tdt` + `enable_live_transcription` | 该组合是本仓实时转写的主路径 |
| 纯中文、算力紧张 | `paraformer` | 中文专用，参数量小 |
| 已有多语种 Whisper 资产 | `faster-whisper` | CPU 可跑，`compute_type` 可压显存 |
| 不想本地跑 STT | `openai` / `openai-realtime` | 托管，代价是每轮网络往返 |
| 端到端语音大模型 | `none` + 支持音频输入的 `chat-completions` | 跳过转写，但需显式换成音频模型 |

---

## 4. LLM 参数

### 4.1 当前组件档案

| 项 | 值 | 说明 |
|---|---|---|
| 后端 | `chat-completions` | 字段前缀沿用 `responses_api_*`，这是预期行为 |
| 模型 | `Qwen3-8B` | 部署在 GPUStack 网关，非本机权重 |
| 端点 | `http://192.168.40.30/v1-openai` | `responses_api_base_url` |
| 密钥 | `{env: GPUSTACK_API_KEY}` | 缺失即报错，无默认回退 |
| 延迟取舍 | `stream=true`、`stream_batch_sentences=1`、`reasoning_effort=""` | 逐句流式 + 不发推理强度 |
| 人设 | 一句话以内的短回复，跟随用户语言 | `init_chat_prompt` |

### 4.2 会话通用参数（所有 LLM 后端共享）

| 参数 | 作用 | 默认 / 范围 | 来源 | 生效 | 暴露 | 影响面 · 代价 | 风险 / 副作用 | 锚点 |
|---|---|---|---|---|---|---|---|---|
| `model_name` | 模型 ID 或本地路径 | `Qwen/Qwen3.5-4B`（`responses-api` / `chat-completions` 覆写为 `gpt-5.6-terra`） | `YAML > env > 默认` | 启动 | expert | 管线级 · 分钟级 | 模型越大显存越高；远端名称须与 provider 完全一致，否则 404 | `language_model_base_arguments.py:6` |
| `user_role` | 用户消息的角色名 | `user`；字符串 | `YAML > env > 默认` | 启动 | advanced | 管线级 · 重启 | 与 chat template 不匹配会降低指令遵循 | `language_model_base_arguments.py:10` |
| `init_chat_role` | 会话初始系统消息角色 | `system`；字符串 | `YAML > env > 默认` | 启动 | advanced | 管线级 · 重启 | 非 `system` 可能被部分 chat template 忽略 | `language_model_base_arguments.py:14` |
| `init_chat_prompt` | 系统提示词（人设） | 内置英文助手提示；建议 ≤2k 字符 | `YAML > env > 默认`，`session.update.instructions` 可覆盖 | 启动+热更新 | basic | 会话级 · 秒级 | 过长抬高首 token 延迟与 KV 显存；入库前须脱敏 | `language_model_base_arguments.py:18` |
| `chat_size` | 保留的历史交互轮数 | `30`；正整数 | `YAML > env > 默认` | 启动 | basic | 会话级 · 重启 | 过大抬上下文显存；过小丢失多轮记忆 | `language_model_base_arguments.py:22` |
| `stream_batch_sentences` | 流式每批累计句数 | `3`（生产 `1`）；正整数 | `YAML > env > 默认` | 启动 | basic | 会话级 · 重启 | 越大首音越慢；`1` 为最低延迟 | `language_model_base_arguments.py:26` |
| `enable_lang_prompt` | 在提示中追加本轮语言指令 | `false`；布尔 | `YAML > env > 默认` | 启动 | basic | 会话级 · 重启 | 每轮多几条 token，略增延迟 | `language_model_base_arguments.py:33` |
| `compact_history` | 超 `chat_size` 时后台摘要旧轮次 | `true`；布尔 | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 每轮可能多一次 LLM 调用（摘要） | `language_model_base_arguments.py:40` |

### 4.3 远端兼容后端参数（`responses-api` / `chat-completions`）

两个后端共用 `responses_api_*` 前缀；`chat-completions` 只覆写 `responses_api_reasoning_effort` 的默认值（改为不发）。

| 参数 | 作用 | 默认 / 范围 | 来源 | 生效 | 暴露 | 影响面 · 代价 | 风险 / 副作用 | 锚点 |
|---|---|---|---|---|---|---|---|---|
| `model_name` | 模型名（覆写基类默认） | `gpt-5.6-terra`；字符串 | `YAML > env > 默认` | 启动 | expert | 管线级 · 分钟级 | 默认模型**不支持音频输入**；`stt=none` 时必须显式换模型 | `responses_api_language_model_arguments.py:9` |
| `responses_api_api_key` | bearer token | `None`；字符串 | `YAML > env > 默认` | 启动 | ops | 管线级 · 重启 | **安全**：只写不读，平台回显 `***`；泄漏等于泄漏上游额度 | `:16` |
| `responses_api_base_url` | 服务地址 | `None`（回退官方 OpenAI）；URL | `YAML > env > 默认` | 启动 | advanced | 管线级 · 重启 | **环境绑定**：留空会打向公网官方 API，内网部署必须显式配置 | `:20` |
| `responses_api_stream` | 流式返回 | `true`；布尔 | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 关闭后首音延迟显著变长 | `:24` |
| `responses_api_disable_thinking` | 禁用服务端推理 | `true`；布尔 | `YAML > env > 默认` | 启动 | advanced | 管线级 · 重启 | 部分提供商忽略该字段，需配合 `reasoning_effort` | `:31` |
| `responses_api_reasoning_effort` | 推理强度 | `responses` 默认 `none`；`chat-completions` 默认 `None`（不下发）。可取 `none`/`low`/`medium`/`high`/空串 | `YAML > env > 默认` | 启动 | advanced | 管线级 · 重启 | 非 `none` 明显抬高首 token 延迟；**空串按后端不对称**：`chat-completions` 空串＝不下发（falsy 判断，回落 `disable_thinking`），`responses` 空串仍会下发 `reasoning:{effort:""}`，只有留空/`null` 才不发 | `:38`、`responses_api_language_model.py:95`、`base_openai_compatible_language_model.py:297` |
| `responses_api_audio_max_tokens` | 音频输入请求最大 token | `256`；正整数 | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 仅音频输入 LLM（`stt=none`）生效 | `:46` |
| `responses_api_audio_temperature` | 音频输入请求温度 | `0.0`；浮点 | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 同上 | `:50` |
| `responses_api_audio_content_type` | 音频内容编码方式 | `input_audio`；`input_audio`（WAV base64）/ `audio_url`（data URL） | `YAML > env > 默认` | 启动 | expert | 管线级 · 重启 | 提供商只接其中一种，选错报 400 | `:54` |
| `responses_api_audio_history_turns` | 历史中保留的音频轮数 | `1`；`0` = 全部替换为占位 | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 保留越多音频，上下文 token 越高 | `:61` |
| `responses_api_provider_unavailable_message` | 上游不可用时朗读的提示语 | `None`（通用兜底）；字符串 | `YAML > env > 默认` | 启动 | basic | 会话级 · 重启 | 只影响朗读文案；状态码与响应体始终写日志 | `:68` |

> `chat-completions` 的 `responses_api_reasoning_effort` 默认为 `None`（即不下发），此时退回 `disable_thinking` 行为（`chat_template_kwargs.enable_thinking=false`）。本仓 compose 显式传空串以覆盖默认。

### 4.4 本地后端参数（`transformers` / `mlx-lm`）

| 参数 | 作用 | 默认 / 范围 | 来源 | 生效 | 暴露 | 影响面 · 代价 | 风险 / 副作用 | 锚点 |
|---|---|---|---|---|---|---|---|---|
| `llm_device` | 推理设备 | `auto`（MLX 为 `mps`）；`auto`/`cuda`/`cpu`/`mps` | `YAML > env > 默认` | 启动 | expert | 管线级 · 重启 | 落 CPU 时首 token 延迟可达秒级 | `language_model_arguments.py:10` |
| `llm_torch_dtype` | 模型与张量精度 | `float16`；`float32`/`float16`/`bfloat16` | `YAML > env > 默认` | 启动 | expert | 管线级 · 重启 | `float32` 显存翻倍，容易 OOM | `:14` |
| `llm_load_in_8bit` | bitsandbytes 8bit 量化 | `false`；布尔 | `YAML > env > 默认` | 启动 | expert | 管线级 · 分钟级 | 需 bitsandbytes 与 CUDA 兼容；4B ≈8GB → ≈4GB | `:20` |
| `llm_load_in_4bit` | bitsandbytes 4bit（NF4） | `false`；布尔 | `YAML > env > 默认` | 启动 | expert | 管线级 · 分钟级 | 显存 ≈2.1GB，有小幅质量损失；优先级高于 8bit | `:27` |
| `llm_gen_max_new_tokens` | 单次生成最大 token | `1024`；正整数 | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 过大使长回答占满实例并抬高 KV 显存 | `:34` |
| `llm_gen_min_new_tokens` | 单次生成最小 token | `0`；非负整数 | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 非 0 会强制模型不说短句 | `:38` |
| `llm_gen_temperature` | 采样温度 | `0.0`；浮点 | `YAML > env > 默认` | 启动 | basic | 会话级 · 重启 | 与 `do_sample` 联动，采样关闭时无效 | `:42` |
| `llm_gen_do_sample` | 是否启用采样 | `false`；布尔 | `YAML > env > 默认` | 启动 | basic | 会话级 · 重启 | 开采样后同输入不再稳定复现 | `:48` |
| `llm_is_vlm` | 按视觉语言模型加载 | `false`；布尔 | `YAML > env > 默认` | 启动 | expert | 管线级 · 分钟级 | 对纯文本模型打开会加载失败 | `:52` |

### 4.5 选型建议

| 场景 | 推荐 | 说明 |
|---|---|---|
| 已有 GPUStack / vLLM 网关 | `chat-completions` | 支持音频输入与 LLM 代理，本仓生产即此形态 |
| 需要官方 Responses 语义 | `responses-api` | 无音频输入标记，`stt=none` 不适用 |
| 单机单卡、可控显存 | `transformers` + 4bit | 4B 模型 ≈2.1GB，可与 STT/TTS 共存 |
| macOS | `mlx-lm` | Linux 上会因缺少 MLX 而启动失败 |

---

## 5. TTS 参数

### 5.1 当前组件档案

| 项 | 值 | 说明 |
|---|---|---|
| 后端 | `qwen3` | faster-qwen3-tts，本仓用 `torch` 后端而非默认 `ggml` |
| 权重 | `cache/qwen3-tts-model`（Qwen3-TTS-12Hz-1.7B-**CustomVoice**） | CustomVoice 用预置音色，不需要参考音频 |
| 设备 / 后端 | `cuda` / `torch` | GGML 后端会自动选设备 |
| 流式 | `non_streaming_mode=false` + `streaming_chunk_size=4` | 句内流式，压首音延迟 |
| 音色 | `speaker` 默认 `Aiden` | 会话 `voice` 可覆盖（需是后端支持的名字）|
| 输出 | 24 kHz 裸 PCM → 管线重采样到 16 kHz | 与 `openai_tts_sample_rate=24000` 一致 |

### 5.2 参数表（`blocks.tts.settings`，`qwen3` 后端）

| 参数 | 作用 | 默认 / 范围 | 来源 | 生效 | 暴露 | 影响面 · 代价 | 风险 / 副作用 | 锚点 |
|---|---|---|---|---|---|---|---|---|
| `qwen3_tts_model_name` | 模型 ID 或本地路径 | `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`；Apple Silicon 自动映射 MLX 变体 | `YAML > env > 默认` | 启动 | expert | 管线级 · 分钟级 | CustomVoice / VoiceDesign / Base 三类字段要求不同，选错启动失败 | `qwen3_tts_arguments.py:7` |
| `qwen3_tts_device` | torch 后端设备 | `cuda`；`cuda` / `auto` | `YAML > env > 默认` | 启动 | expert | 管线级 · 重启 | `auto` 在无 CUDA 时落 CPU，延迟不可接受 | `:13` |
| `qwen3_tts_dtype` | 推理精度 | `auto`；`auto`/`float16`/`bfloat16`/`float32` | `YAML > env > 默认` | 启动 | expert | 管线级 · 重启 | `float32` 显存与带宽翻倍 | `:19` |
| `qwen3_tts_attn_implementation` | 注意力实现 | `eager`；`eager`/`flash_attention_2`/`sdpa` | `YAML > env > 默认` | 启动 | expert | 管线级 · 重启 | `flash_attention_2` 需额外依赖；Jetson 必须 `eager` | `:25` |
| `qwen3_tts_backend` | faster-qwen3-tts 后端 | `ggml`（生产 `torch`）；`ggml`/`torch` | `YAML > env > 默认` | 启动 | expert | 管线级 · 分钟级 | 两种后端权重格式不同，切换需重下；Apple Silicon 忽略此值走 mlx-audio | `:31` |
| `qwen3_tts_ggml_quantization` | GGUF 量化级别 | `BF16`；`BF16`/`Q8_0`/`Q4_K_M`/`F32` | `YAML > env > 默认` | 启动 | expert | 管线级 · 分钟级 | `Q4_K_M` 显存最低但音质下降 | `:37` |
| `qwen3_tts_gguf_talker_path` | 本地 talker GGUF 路径 | `None`；路径 | `YAML > env > 默认` | 启动 | ops | 管线级 · 重启 | **环境绑定**：须与 codec 成对且 `backend=ggml` | `:43` |
| `qwen3_tts_gguf_codec_path` | 本地 codec GGUF 路径 | `None`；路径 | `YAML > env > 默认` | 启动 | ops | 管线级 · 重启 | 同上 | `:49` |
| `qwen3_tts_ref_cache_dir` | 音色参考自动缓存目录 | `None`（用后端默认）；路径 | `YAML > env > 默认` | 启动 | ops | 管线级 · 重启 | **环境绑定**：容器不挂卷会每次重建重算音色向量 | `:55` |
| `qwen3_tts_ref_audio` | 克隆用参考音频 | `None`；路径 | `YAML > env > 默认` | 启动 | expert | 管线级 · 分钟级 | **隐私**：参考音频是生物特征，入库需授权；与 `ref_spk` 互斥 | `:61` |
| `qwen3_tts_ref_spk` | 预计算 `.spk` 说话人向量 | `None`；路径 | `YAML > env > 默认` | 启动 | expert | 管线级 · 重启 | 与 `ref_audio` 互斥，同时给会报错 | `:67` |
| `qwen3_tts_ref_rvq` | 预计算 `.rvq` 声学码 | `None`；路径 | `YAML > env > 默认` | 启动 | expert | 管线级 · 重启 | 依赖 `ref_spk` + `ref_text`，缺一报错 | `:73` |
| `qwen3_tts_ref_text` | 参考音频的转写文本 | 内置一段英文示例 | `YAML > env > 默认` | 启动 | advanced | 管线级 · 重启 | 必须逐字匹配参考音频，否则克隆失真 | `:79` |
| `qwen3_tts_speaker` | CustomVoice 音色名 | `Aiden`；后端支持的音色名 | `YAML > 默认` + `session.voice` 覆盖 | 启动+热更新 | basic | 会话级 · 秒级 | 名字不存在时后端回退第一个可用音色；会话覆盖需大小写匹配 | `:83` |
| `qwen3_tts_instruct` | VoiceDesign 指令文本 | `None`；字符串 | `YAML > env > 默认` | 启动 | basic | 管线级 · 重启 | 仅 VoiceDesign 模型生效 | `:89` |
| `qwen3_tts_xvec_only` | 仅用 x-vector 克隆 | `false`；布尔 | `YAML > env > 默认` | 启动 | advanced | 管线级 · 重启 | 起步更干净但相似度略降 | `:93` |
| `qwen3_tts_parity_mode` | 关闭 CUDA graph 流式路径 | `false`；布尔 | `YAML > env > 默认` | 启动 | expert | 管线级 · 重启 | 吞吐下降，但可规避部分卡型的流式异常 | `:99` |
| `qwen3_tts_non_streaming_mode` | 解码前预填完整文本 | `true`（生产 `false`）；布尔 | `YAML > env > 默认` | 启动 | advanced | 管线级 · 重启 | 关掉＝句内流式，降首音延迟；Apple Silicon 忽略 | `:103` |
| `qwen3_tts_mlx_quantization` | Apple Silicon MLX 量化 | `6bit`；`bf16`/`4bit`/`6bit`/`8bit` | `YAML > env > 默认` | 启动 | expert | 管线级 · 分钟级 | 仅 Apple Silicon 生效 | `:109` |
| `qwen3_tts_language` | 合成目标语言 | `auto`；语言码或 `auto` | `YAML > env > 默认` | 启动 | basic | 会话级 · 重启 | `auto` 在混合语种下会串音 | `:115` |
| `qwen3_tts_streaming_chunk_size` | 每流式块 codec 步数 | `None`（faster-qwen3-tts 为 8、mlx-audio 为 4；生产 `4`） | `YAML > env > 默认` | 启动 | advanced | 管线级 · 重启 | 过小抬高调度开销，过大抬高首音延迟 | `:119` |
| `qwen3_tts_max_new_tokens` | codec token 上限 | `1536`；正整数（≈12 token/秒音频） | `YAML > env > 默认` | 启动 | advanced | 管线级 · 重启 | 过小长句被截断 | `:125` |
| `qwen3_tts_blocksize` | 流式输出块大小 | `512`；正整数（采样点） | `YAML > env > 默认` | 启动 | expert | 管线级 · 重启 | 与下游 `CHUNK_SAMPLES=512` 对齐最佳 | `:131` |

### 5.3 其他 TTS 后端的关键字段

| 后端 | 专属字段（示例） | 必填 / 关键 | 备注 |
|---|---|---|---|
| `openai`（远端） | `openai_tts_base_url`、`openai_tts_model`、`openai_tts_voice`、`openai_tts_task_type`、`openai_tts_sample_rate`、`openai_tts_stream` | `base_url` | `pcm` 裸流必须配对 `sample_rate`；`stream` 仅 vLLM-Omni 支持 |
| `kokoro` | `kokoro_model_name`、`kokoro_device`、`kokoro_voice`、`kokoro_lang_code`、`kokoro_speed`、`kokoro_blocksize` | 音色 + `lang_code` | `lang_code` 决定可用音色集合 |
| `kitten` | `kitten_model_name`、`kitten_device`、`kitten_voice` | 音色 | 支持会话改音色 |
| `pocket` | `pocket_tts_model_name`、`pocket_tts_voice`、`pocket_tts_device`、`pocket_tts_sample_rate`、`pocket_tts_temperature`、`pocket_tts_eos_threshold` | 模型名 | 有随机性与结束阈值，语音更「活」 |
| `supertonic` | `supertonic_tts_voice`、`supertonic_tts_lang`、`supertonic_tts_speed`、`supertonic_tts_blocksize` | 语言码 | 仅 4 个字段 |
| `phonon` | `phonon_tts_model_name`、`phonon_tts_revision`、`phonon_tts_voice`、`phonon_tts_language`、`phonon_tts_quant`、`phonon_tts_num_threads` | 模型名 | 语言在加载时固化，会话改语言会被拒 |
| `chatTTS` | `chat_tts_model_name`、`chat_tts_device`、`chat_tts_stream`、`chat_tts_chunk_size` | 模型名 | 不支持会话改语言 |
| `facebookMMS` | `facebook_mms_model_name`、`tts_language`、`facebook_mms_device`、`facebook_mms_torch_dtype` | 语言码 | 字段名不是 `facebook_mms_language` |
| `omnivoice` | `omnivoice_model_name`、`omnivoice_ref_audio`、`omnivoice_ref_text`、`omnivoice_voice_clone_prompt`、`omnivoice_ref_voices_dir`、`omnivoice_num_steps` | 参考音频 | 路径字段参与 `_PATH_FIELDS` 解析 |
| `drama3` | `drama3_base_url`、`drama3_api_key`、`drama3_model`、`drama3_ref_audio`、`drama3_timeout`、`drama3_gen_temperature`、`drama3_gen_top_p` | API 密钥 | 云端 API，`ops` 级密钥 |
| `minimax` | `minimax_tts_api_key`、`minimax_tts_base_url`、`minimax_tts_model`、`minimax_tts_voice`、`minimax_tts_speed`、`minimax_tts_vol`、`minimax_tts_pitch` | API 密钥 | 云端 API，含音量/音高 |
| `voxcpm` | `voxcpm_tts_model_name`、`voxcpm_tts_device`、`voxcpm_tts_dtype`、`voxcpm_tts_cfg_value`、`voxcpm_tts_inference_timesteps`、`voxcpm_tts_normalize`、`voxcpm_tts_denoise`、`voxcpm_tts_load_denoiser`、`voxcpm_tts_seed`、`voxcpm_tts_ref_audio`、`voxcpm_tts_prompt_text`、`voxcpm_tts_streaming` | 模型名 | 输出块固定 512（模块常量，不作参数）；`voxcpm_tts_ref_audio` 参与 `_PATH_FIELDS` 解析；语言由文本自动推断，`voice` 字段只回显 |

### 5.4 音色与会话热更新

| 场景 | 结果 | 证据 |
|---|---|---|
| `session.update` 的 `voice` 命中 CustomVoice 支持列表 | 改写 `handler.speaker` 并清空克隆参考，下一句即生效 | `TTS/qwen3_tts_handler.py:553-590,893` |
| `voice` 不是支持的名字 | 只记 warning 并忽略，音色不变 | 同上 `:576-584` |
| `voice` 是音频文件路径（克隆模式） | 作为 `ref_audio` 使用 | 同上 `:592-595` |
| 其他 TTS 后端 | 除 `kitten` 外，`voice` 只回显不改变合成 | `s2s_pipeline.py:700-716` 的语言能力表 + 各 handler 无 voice 读取 |

> 把 `voice` 当「热更新音色」在 `qwen3` 之外的后端上是不成立的；平台应在音色选择器上按后端能力置灰。

---

## 6. 平台与运行时公共参数

本章是四个组件之外的公共面：它不改变「用哪个模型」，只改变「服务怎么跑」。平台若只开放 §2–§5，仍需本章作为 `ops` 面单独维护。

### 6.1 监听与并发

| 参数 | 作用 | 默认 / 范围 | 来源 | 生效 | 暴露 | 影响面 · 代价 | 风险 / 副作用 | 锚点 |
|---|---|---|---|---|---|---|---|---|
| `host` | Realtime 服务监听地址 | `127.0.0.1`；IPv4/IPv6 字符串 | `YAML > env > 默认` | 启动 | ops | 进程级 · 重启 | **安全**：`0.0.0.0` 会把**无鉴权**的 Realtime API 暴露到网络 | `realtime_server_arguments.py` |
| `port` | HTTP/WebSocket 监听端口 | `8765`；1–65535 | `YAML > env > 默认` | 启动 | ops | 进程级 · 重启 | **环境绑定**：须与 compose 映射 `PIPELINE_PORT:8765` 一致，否则外部不可达 | 同上 |
| `num_pipelines` | 管线池实例数＝最大并发会话数 | `1`；正整数，硬约束 `<= floor(可用显存×0.85 / 4.6GB)` | `YAML > env > 默认` | 启动 | advanced | 管线级 · 分钟级 | 每路独占整套 handler（实测约 4.6GB）；超配直接 OOM，降配会中断现有会话 | `module_arguments.py:num_pipelines` |
| `-np` | 端侧 llama.cpp 并行槽数 | `1`；正整数 | compose 字面值 | 容器 | ops | 容器级 · 分钟级 | **环境绑定**：与显存、`-c` 上下文耦合，调大易 OOM | `docker-compose.yml` |
| 池满拒绝 | 实例占满时新连接直接失败（无排队） | 固定行为 | — | 固定 | ops | 管线级 · 无 | 高峰期直接失败；扩容只能加 `num_pipelines` 或加实例 | `api/openai_realtime/websocket_router.py` |

### 6.2 超时与重试

| 参数 | 作用 | 默认 / 范围 | 来源 | 生效 | 暴露 | 影响面 · 代价 | 风险 / 副作用 | 锚点 |
|---|---|---|---|---|---|---|---|---|
| `llm_proxy_connect_timeout_s` | LLM 代理到上游的连接超时 | `10.0`；正浮点（秒） | `YAML > env > 默认` | 启动 | expert | 进程级 · 重启 | 只约束连接；流式读无超时，上游卡住会长期占用实例 | `module_arguments.py` |
| `openai_stt_timeout` | 远端 STT HTTP 超时 | `60.0`；正浮点 | `块 settings > env > 默认` | 启动 | expert | 管线级 · 重启 | 过小截断长语音，过大在远端故障时拖住会话 | `openai_stt_arguments.py:35` |
| `openai_tts_timeout` | 远端 TTS HTTP 超时 | `300.0`；正浮点 | `块 settings > env > 默认` | 启动 | expert | 管线级 · 重启 | 超时表现为该句静音；过小频繁丢句 | `openai_tts_arguments.py:53` |
| `connection_retry_timeout_s` | 本地音频客户端重连窗口 | `30.0`；正浮点 | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 过短会让弱网客户端频繁放弃 | 客户端 `audio_client.py` |
| `request_timeout_s`（LLM）〔只读〕 | OpenAI 兼容 LLM 读取超时，超时即结束本轮 | `20.0`；`connect=min(10.0, x)` | 构造参数写死 | 固定 | expert | 管线级 · 无 | 不可配置；20s 后强制结束，长回答会被截断 | `LLM/base_openai_compatible_language_model.py:196` |
| 重试策略〔只读〕 | LLM/STT/TTS 请求均单次尝试 | 固定（无重试） | — | 固定 | ops | 管线级 · 无 | 无指数退避，瞬时抖动即失败；需靠健康检查与重启兜底 | 同上 |

### 6.3 音频格式与采样率

`sample_rate`（VAD 采样率）已在 §2.2，本节不重复登记。

| 参数 | 作用 | 默认 / 范围 | 来源 | 生效 | 暴露 | 影响面 · 代价 | 风险 / 副作用 | 锚点 |
|---|---|---|---|---|---|---|---|---|
| `PIPELINE_SAMPLE_RATE`〔只读〕 | 管线内部固定采样率 | `16000` | 源码常量 | 固定 | ops | 管线级 · 无 | 改它需改源码与全部后端适配 | `api/openai_realtime/service.py:110` |
| `CHUNK_SAMPLES`〔只读〕 | 服务端音频分块常量 | `512` | 源码常量 | 固定 | ops | 管线级 · 无 | 改动影响全部下游分块假设 | `service.py:111` |
| `send_rate` | 客户端上行采样率 | `16000`；正整数 | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 与设备能力不符会多一次重采样 | 客户端配置 |
| `recv_rate` | 客户端下行采样率 | `16000`；正整数 | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 与服务端输出不符会变调 | 客户端配置 |
| `chunk_size` | 客户端收发块大小 | `1024`；正整数（采样点） | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 过小抬高回调频率，过大抬高延迟 | 客户端配置 |
| `playback_buffer_ms` | 播放前缓冲 | `0.0`；有限非负（ms） | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 过小 underrun 爆音，过大首音迟 | 客户端配置 |
| `openai_tts_sample_rate` | 远端 TTS 裸 PCM 采样率 | `24000`；正整数（Qwen3-TTS 为 24000） | `块 settings > env > 默认` | 启动 | expert | 管线级 · 重启 | 配错会变调/变速；仅对返回裸 PCM 的服务生效 | `openai_tts_arguments.py:41` |

### 6.4 设备、线程与说话人分离

| 参数 | 作用 | 默认 / 范围 | 来源 | 生效 | 暴露 | 影响面 · 代价 | 风险 / 副作用 | 锚点 |
|---|---|---|---|---|---|---|---|---|
| `device` | 全局设备覆盖 | `None`；`auto`/`cuda`/`mps`/`cpu`/`npu` | `YAML > env > 默认` | 启动 | ops | 进程级 · 重启 | **环境绑定**：击穿各组件 `*_device` 意图，可能 OOM 或落 CPU 使延迟翻倍 | `module_arguments.py:device` |
| `mac_optimal_settings` | macOS 预设包（Parakeet + MLX LM + Qwen3-TTS + MPS） | `false`；布尔，显式字段覆盖预设 | `YAML > env > 默认` | 启动 | expert | 进程级 · 重启 | 仅 macOS 成立；Linux 打开会加载 MLX 失败 | `module_arguments.py` |
| `torch_num_threads` | 进程级 PyTorch intra-op 线程数 | `None`（Silero 加载时设为 1）；正整数 | `YAML > env > 默认` | 启动 | advanced | 进程级 · 重启 | Silero 与 CPU STT 共用；调大加速 STT 但拖慢 Silero | `module_arguments.py` |
| `diarization` | 启用说话人分离（Nemotron 3 Diarization） | `false`；布尔 | `YAML > env > 默认` | 启动 | advanced | 管线级 · 分钟级 | 额外显存；分离出错会把同一人拆成多说话人 | `module_arguments.py` |
| `diarization_model_name` | 流式分离 checkpoint | `None`；Hub ID 或本地路径 | `YAML > env > 默认` | 启动 | expert | 管线级 · 分钟级 | 开启 `diarization` 但未配置则启动失败 | 同上 |
| `diarization_revision` | 分离模型 revision | `None`；字符串 | `YAML > env > 默认` | 启动 | expert | 管线级 · 分钟级 | 不固定会随上游更新行为漂移 | 同上 |
| `diarization_device` | 分离模型设备（受 `device` 覆盖） | `auto`；`auto`/`cuda`/`mps`/`cpu` | `YAML > env > 默认` | 启动 | expert | 管线级 · 重启 | 与 STT/TTS 争显存 | 同上 |
| `diarization_dtype` | 分离模型精度 | `float32`；`float32`/`float16`/`bfloat16` | `YAML > env > 默认` | 启动 | expert | 管线级 · 重启 | `float16` 在部分算子下精度下降，可能误判 | 同上 |
| `diarization_streaming_mode` | 流式模式 | `low_latency`；`low_latency`/`very_low_latency`/`ultra_low_latency` | `YAML > env > 默认` | 启动 | expert | 管线级 · 重启 | 越低延迟越易把一句切成多段 | 同上 |
| `diarization_threshold` | 说话人活动概率阈值 | `0.5`；（0,1）浮点 | `YAML > env > 默认` | 启动 | expert | 管线级 · 重启 | 过低把噪声当人，过高漏掉轻声轮次；越界校验失败 | 同上 |
| `detect_llm_output_language` | 逐块检测助手输出语言并传给 TTS | `false`；布尔，启动时预热检测器 | `YAML > env > 默认` | 启动 | advanced | 管线级 · 重启 | 首块过短时不下发语言码；多一次本地推理 | 同上 |

### 6.5 鉴权与安全

| 参数 | 作用 | 默认 / 范围 | 来源 | 生效 | 暴露 | 影响面 · 代价 | 风险 / 副作用 | 锚点 |
|---|---|---|---|---|---|---|---|---|
| `enable_llm_proxy` | 暴露 OpenAI 兼容 LLM 代理端点 | `false`；仅 `supports_llm_proxy` 后端可用 | `YAML > 默认` | 启动 | ops | 进程级 · 重启 | **安全**：服务自身不做鉴权，开启即把 LLM 额度暴露给任意可达客户端 | `module_arguments.py` |
| `openai_stt_api_key` | 远端 STT bearer token | `None`；回退 `OPENAI_API_KEY` | `块 settings > env > 默认` | 启动 | ops | 管线级 · 重启 | **安全**：隐式回退会让「未配置」看似「已配置」 | `openai_stt_arguments.py:13` |
| `openai_tts_api_key` | 远端 TTS bearer token | `None`；回退 `OPENAI_API_KEY` | `块 settings > env > 默认` | 启动 | ops | 管线级 · 重启 | **安全**：同上 | `openai_tts_arguments.py:13` |
| `USAGE_HASH_SECRET` | 用量库用户标识 HMAC 密钥 | 每次启动随机生成 | 环境变量 | 启动 | ops | 进程级 · 重启 | **安全**：不显式设置则重启换钥，历史 `user_key` 全部失配 | `archive/demo/limiter.py:50` |
| `UNLIMITED_ORGS` | 不计配额的 HF 组织白名单 | `cerebras,huggingfacem4,smolagents,pollen-robotics` | 环境变量 | 启动 | ops | 进程级 · 重启 | **安全**：白名单组织绕开全部配额 | `archive/demo/auth.py:47` |
| `AUTH_DEBUG` | 鉴权调试日志 | `false`；非空即开启 | 环境变量 | 启动 | ops | 进程级 · 重启 | **隐私**：调试日志可能落盘身份信息 | `archive/demo/auth.py:89` |
| `S2S_ADMIN_TOKEN` | 保护 `POST /admin/sessions/update` 与 `DELETE /v1/realtime/calls/{id}` | 空（**未设则路由直接 `503 admin_disabled`**）；Bearer token | 环境变量 | 启动 | ops | 进程级 · 重启 | **安全**：fail-closed——未配token 含义是「热更新不可用」，不是「无需鉴权」；泄得即可改所有在线会话 | `websocket_router.py:809-814,1004-1007` |
| `S2S_INTERNAL_TOKEN` | 保护控制台侧 `POST /internal/sessions/update` | 空（未设则 `503 internal_token_missing`） | 环境变量 | 启动 | ops | 进程级 · 重启 | **安全**：同一个推送能力在 loopback 上也必须带 token，防半面部署时变成无鉴权写入口 | `websocket_router.py:735-739` |
| CORS 策略〔只读〕 | 演示服务未装 `CORSMiddleware` | 固定（无 CORS 头） | — | 固定 | ops | 进程级 · 无 | 跨域前端需同源部署或由反代补 CORS 头 | `archive/demo/server.py` |
| Realtime API 鉴权〔只读〕 | `/v1/realtime`、`/v1/pool`、`/v1/usage`、`POST /v1/realtime/calls` 均不校验凭据 | 固定（无鉴权） | — | 固定 | ops | 进程级 · 无 | **安全**：任何拿到 `host:port` 的人都能开会话；只有 `/admin/*` 与挂断调用检查 token（见上两行），平台须在反代层加 token 与网络隔离 | `websocket_router.py` |

### 6.6 日志与监控

| 参数 | 作用 | 默认 / 范围 | 来源 | 生效 | 暴露 | 影响面 · 代价 | 风险 / 副作用 | 锚点 |
|---|---|---|---|---|---|---|---|---|
| `log_level` | 应用日志级别 | `info`；logging 级别 | `YAML > env > 默认` | 启动 | advanced | 进程级 · 重启 | `debug` 显著抬高 I/O 与日志体积 | `module_arguments.py` |
| `log_transcripts` | 把完整对话转写写入日志 | `false`；布尔 | `YAML > env > 默认` | 启动 | ops | 进程级 · 重启 | **隐私**：日志常被容器与聚合器长期保留，对话会比会话活得更久 | `module_arguments.py` |
| `enable_live_transcription` | 说话中实时显示转写 | `true`（本仓生产 `false`）；布尔 | `pipelines.<n>.options` | 启动 | basic | 管线级 · 重启 | 产生大量 partial 事件，弱网抬高带宽 | `module_arguments.py` |
| `live_transcription_update_interval` | 实时转写刷新间隔 | `0.5`；正浮点（秒） | `YAML > env > 默认` | 启动 | advanced | 管线级 · 重启 | 过小抬高 CPU 与事件量 | `module_arguments.py` |
| `MODEL_METRICS_LOG` | 模型指标 JSONL 路径 | `model_metrics.log`；路径 | 环境变量 | 启动 | ops | 进程级 · 重启 | **环境绑定**：容器内相对路径，未挂卷则随容器销毁丢失 | `utils/model_monitor.py:50` |
| `MODEL_METRICS_LOG_MAX_BYTES` | 指标日志单文件上限 | `20971520`（20 MiB） | 环境变量 | 启动 | ops | 进程级 · 重启 | 过小高频滚动，过大占满磁盘 | `model_monitor.py:51` |
| `MODEL_METRICS_LOG_BACKUPS` | 指标日志滚动份数 | `5`；非负整数 | 环境变量 | 启动 | ops | 进程级 · 重启 | 份数 × 单文件上限＝磁盘占用上限 | `model_monitor.py:52` |
| 监控端点〔只读〕 | `GET /v1/pool` 返回 `{size, in_use, units}`；`GET /v1/usage` 返回用量 | 固定可用 | — | 固定 | advanced | 进程级 · 无 | 平台健康检查与回滚判定依赖这两个端点；`stuck` 单元可识别卡死管线 | `websocket_router.py` |

### 6.7 环境变量

| 变量 | 作用 | 默认 / 范围 | 来源 | 生效 | 暴露 | 影响面 · 代价 | 风险 / 副作用 | 锚点 |
|---|---|---|---|---|---|---|---|---|
| `HF_HUB_OFFLINE` | 强制 Hub 完全离线 | `1`（本仓 compose 已设） | 环境变量 | 启动 | ops | 容器级 · 分钟级 | **环境绑定**：缓存不全时报 `LocalEntryNotFound` | `docker-compose.yml` |
| `TRANSFORMERS_OFFLINE` | 强制 transformers 不联网 | `1` | 环境变量 | 启动 | ops | 容器级 · 分钟级 | 同上 | 同上 |
| `TOKENIZERS_PARALLELISM` | 关闭 tokenizer 并行 fork | `false` | 环境变量 | 启动 | ops | 容器级 · 分钟级 | 仅影响警告与 fork 行为 | 同上 |
| `HF_ENDPOINT` | Hub 镜像源 | `https://hf-mirror.com` | 环境变量 | 启动 | ops | 容器级 · 分钟级 | **环境绑定**：镜像不可达时下载卡住 | `docker-compose.gpustack.yml` |
| `HF_HUB_ENABLE_PROGRESS_BARS` | 关闭下载进度条 | `false` | 环境变量 | 启动 | ops | 容器级 · 分钟级 | 纯日志噪声控制 | 同上 |
| `MODELSCOPE_ENDPOINT` | ModelScope 镜像源 | `https://modelscope.cn` | 环境变量 | 启动 | ops | 容器级 · 分钟级 | 仅影响 ModelScope 拉取 | 同上 |
| `GPUSTACK_BASE_URL` | GPUStack 网关地址 | `http://192.168.40.30/v1-openai` | `.env` / shell | 启动 | ops | 管线级 · 重启 | **环境绑定**：错地址则首轮回复直接报错 | `.env.gpustack.example` |
| `GPUSTACK_MODEL` | GPUStack 上的模型名 | `Qwen3-8B`（生产即此值） | `.env` / shell | 启动 | expert | 管线级 · 重启 | 与网关注册名不匹配会 404 | 同上 |
| `GPUSTACK_API_KEY` | 网关密钥 | `not-needed`（示例） | `.env` / shell | 启动 | ops | 管线级 · 重启 | **安全**：写入 `.env` 后须限制权限，不得入仓 | 同上 |
| `SERPER_API_KEY` | 演示服务搜索工具密钥 | `None`（未设则工具不可用） | 环境变量 | 启动 | ops | 进程级 · 重启 | **安全**：泄漏等于泄漏搜索额度 | `archive/demo/server.py` |
| `RTC_ICE_SERVERS` | 浏览器 WebRTC ICE 配置 | `None`（仅 STUN） | 环境变量 | 启动 | ops | 进程级 · 重启 | **环境绑定**：NAT 下需自建 TURN | 同上 |
| `OPENAI_API_KEY` | 远端 STT/TTS 密钥隐式回退 | `None` | 环境变量 | 启动 | ops | 管线级 · 重启 | **安全**：全局变量会隐式影响多个后端，建议改用显式 `*_api_key` | STT/TTS 兼容 handler |
| `SILERO_VAD_REPO_PATH` | Silero VAD 本地仓库路径 | 未设时 `/opt/silero-vad` → 仓库内 `silero-vad/` | 环境变量 | 启动 | ops | 管线级 · 重启 | **环境绑定**：路径不含 `hubconf.py` 时 `torch.hub.load` 直接失败 | `VAD/vad_handler.py:159-163` |

### 6.8 配置文件约束

| 项 | 作用 | 默认 / 范围 | 来源 | 生效 | 暴露 | 影响面 · 代价 | 风险 / 副作用 | 锚点 |
|---|---|---|---|---|---|---|---|---|
| `schema_version` | YAML 版本号 | 必须为 `1` | 文件顶层 | 启动 | ops | 容器级 · 分钟级 | 写错直接拒启 | `config.py:375` |
| 顶层结构 | 只允许 `schema_version`/`runtime`/`blocks`/`pipelines` | 映射；未知键报错 | 文件结构 | 启动 | ops | 容器级 · 分钟级 | 多余键被拒（无向前兼容） | `config.py:374` |
| `{env: NAME}` 引用 | 标量位置插入环境变量 | 仅标量；缺失即报错不回退 | 低于显式值、高于默认 | 启动 | advanced | 容器级 · 重启 | 是「密钥不进仓」的主要手段，也是常见启动失败原因 | `config.py:190` |
| 路径字段解析 | `_PATH_FIELDS` 做 `~` 展开与「相对 YAML 目录」解析 | 路径字符串 | 解析阶段 | 启动 | advanced | 容器级 · 重启 | 容器内应写绝对路径，相对路径易错 | `config.py:_PATH_FIELDS` |
| 文件体积上限〔只读〕 | 单文件最大字节 | `1048576`（1 MiB） | 硬编码 | 固定 | ops | 容器级 · 无 | 超过直接拒读 | `_config_yaml.py:13` |
| 嵌套深度上限〔只读〕 | 容器最大嵌套层数 | `32` | 硬编码 | 固定 | ops | 容器级 · 无 | 超限拒绝；生成器不应产生深嵌套 | `_config_yaml.py:14` |

> anchors / aliases / merge keys / explicit tags 全部禁用，YAML 必须展开书写；详见 [`configuration.md`](./configuration.md)。

### 6.9 容器化部署

| 项 | 作用 | 默认 / 范围 | 来源 | 生效 | 暴露 | 影响面 · 代价 | 风险 / 副作用 | 锚点 |
|---|---|---|---|---|---|---|---|---|
| `DOCKERFILE`（build arg） | 选择镜像变体 | `Dockerfile`；`Dockerfile.cu130` / `.baked` 等 | `.env > 默认` | 容器 | ops | 容器级 · 分钟级 | **环境绑定**：变体自带不同 CUDA 基线，选错驱动不匹配 | `docker-compose.yml` |
| `BASE_IMAGE`（build arg） | 基础镜像 | `python-torch:cu128` | 构建参数 | 容器 | ops | 容器级 · 分钟级 | **环境绑定**：cu128 需驱动 <13.0，cu130 需 >=580 | `Dockerfile` |
| `PIPELINE_PORT`（host 侧） | 宿主端口映射 | `8765`；1–65535 | `.env > 默认` | 容器 | ops | 容器级 · 分钟级 | **环境绑定**：只改宿主侧，容器内仍固定 8765 | `docker-compose.gpustack.yml` |
| `PIPELINE_GPU_ID`（host 侧） | 绑定 GPU 序号 | `1`（gpustack 变体；主 compose 写死 `0`） | `.env > 默认` | 容器 | ops | 容器级 · 分钟级 | **环境绑定**：改错用错卡；与 `num_pipelines` 显存预算共同决定上限 | 同上 |
| GPU 能力声明〔只读〕 | `capabilities: [gpu]` | 固定声明 | — | 固定 | ops | 容器级 · 无 | 无预留时 pipeline 退 CPU，实时性不保 | `docker-compose.yml` |
| 权重/缓存卷〔只读〕 | `./cache/` → `/root/.cache/` | 固定挂载 | — | 固定 | ops | 容器级 · 无 | **环境绑定**：不挂卷则每次重建重下权重 | 同上 |
| Silero VAD 卷〔只读〕 | `silero-vad-master` → `/opt/silero-vad`（只读） | 固定挂载 | — | 固定 | ops | 容器级 · 无 | **环境绑定**：缺该卷会回退联网下载，离线环境启动挂掉 | 同上 |
| 重启策略 | 异常退出自动拉起 | `unless-stopped` | 编排文件 | 容器 | ops | 容器级 · 分钟级 | 与平台回滚存在竞争；平台接管后建议固定 `no` | `docker-compose.gpustack.yml` |
| 健康检查〔只读〕 | 主 `docker-compose.yml` 定义了 `healthcheck`（15 s 间隔 / 5 s 超时 / 3 次 / `start_period` 120 s），但**只探 console** `:8000/api/v1/health`；其余 6 个 compose 变体全无 | 无（不可配） | — | 固定 | advanced | 容器级 · 无 | 该检查**覆盖不到 pipeline**，`:8765` 就绪仍须平台自己探 `/v1/pool`；`start_period` 120 s 是留给权重加载与 warmup 的 | `docker-compose.yml:67-72` |

### 6.10 客户端

| 参数 | 作用 | 默认 / 范围 | 来源 | 生效 | 暴露 | 影响面 · 代价 | 风险 / 副作用 | 锚点 |
|---|---|---|---|---|---|---|---|---|
| `url` | Realtime WebSocket 地址 | `ws://127.0.0.1:8765/v1/realtime` | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 与 `host`/映射不匹配会一直连不上；公网需 `wss://` | `audio_client.py` |
| `model` | 会话模型名（`session.update`） | `local`；可被后端忽略 | `YAML > env > 默认` | 启动+热更新 | basic | 会话级 · 秒级 | 本地后端基本忽略此值 | 同上 |
| `api_key` | 连接凭据 | `None` | `YAML > env > 默认` | 启动 | ops | 会话级 · 重启 | **安全**：明文存于配置 / 进程表 | 同上 |
| `send_rate` / `recv_rate` | 上下行采样率 | `16000` | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 详见 §6.3 | 同上 |
| `playback_buffer_ms` | 播放前启动缓冲 | `0.0`；有限非负 | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 过小 underrun，过大首音迟 | 同上 |
| `chunk_size` | 收发块大小 | `1024` | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 过小抬高回调频率，过大抬高延迟 | 同上 |
| `input_device` / `output_device` | 声卡设备索引 | `None`（系统默认）；整数 | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | **环境绑定**：索引随主机变化，容器内通常不可用 | 同上 |
| `instructions` | 首帧系统提示词 | `None`（用服务端默认） | `YAML > env > 默认` | 热更新 | basic | 会话级 · 秒级 | 覆盖服务端 `init_chat_prompt`；过长抬高首 token 延迟 | 同上 |
| `voice` | 会话音色 | `None`（用服务端默认） | `YAML > env > 默认` | 热更新 | basic | 会话级 · 秒级 | 仅 `qwen3`（命中支持列表）与 `kitten` 真正生效，见 §5.4 | 同上 |
| `print_json` | 打印原始 Realtime 事件 | `false` | `YAML > env > 默认` | 启动 | expert | 会话级 · 重启 | 大量打印会拖慢终端 | 同上 |
| `block_mic_during_playback` | 播放时暂停麦克风 | `false` | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 打开会失去 barge-in | 同上 |
| `log_transcripts` | 客户端侧转写日志 | `false` | `YAML > env > 默认` | 启动 | ops | 会话级 · 重启 | **隐私**：客户端也会留存对话文本 | 同上 |
| `connection_retry_timeout_s` | 断线重连窗口 | `30.0` | `YAML > env > 默认` | 启动 | advanced | 会话级 · 重启 | 过短在弱网下直接放弃 | 同上 |
| `tools` | 可调用工具声明 | `[]`；JSON Schema 数组 | 代码传入 | 启动 | expert | 会话级 · 重启 | 工具描述错误会导致模型乱调或拒调 | 同上 |
| `tool_executor` | 工具执行回调 | `None`；可调用对象 | 代码传入 | 启动 | ops | 会话级 · 重启 | 执行任意本地逻辑，不应接受用户提交可执行回调 | 同上 |
| `tool_response_create` | 工具结果是否触发新一轮回复 | `true` | 代码传入 | 启动 | advanced | 会话级 · 重启 | 关掉后模型看不到执行结果 | 同上 |

---

## 7. 生效方式总览与「仅重启参数」改造评估

> 本章是 §2–§6 全部参数行的**横向索引**，不新增参数、不改变 §0.5 的语义。
> 原文每张参数表已有「生效」列；本章把 170 行按「运行时 / 重启」重新切分，并对 162 个仅重启参数**逐行给出可行性判断与改造建议**，供平台排期使用。

### 7.1 判定口径

| 归类 | 对应 `生效` 取值 | 含义 |
|---|---|---|
| 运行时可改 | `热更新`、`启动+热更新` | 无需重启进程；但 `热更新` 只作用于已连接会话、不持久化，新连接仍读 YAML 种子（见 A.2） |
| 必须重启 | `启动`、`容器`、`固定` | `启动`＝改 YAML/env 后重建进程；`容器`＝改 compose/build arg 后重建容器；`固定`＝无配置入口，需改源码才能实现 |

> 已有热更新链路的三条限制必须同时说明：① 只影响活跃连接（空闲 unit 与新连接读启动值）；② 不持久化，重启回退到 YAML；③ 受 `S2S_ADMIN_TOKEN` / `S2S_INTERNAL_TOKEN` fail-closed 保护（未配置即不可用）。

### 7.2 生效方式分布（全量 170 行）

| 章节 | 总行数 | 运行时可改 | 必须重启 | 其中 `容器` | 其中 `固定` |
|---|---:|---:|---:|---:|---:|
| 2. VAD 参数 | 22 | 2 | 20 | 0 | 0 |
| 3. STT 参数 | 6 | 1 | 5 | 0 | 0 |
| 4. LLM 参数 | 28 | 1 | 27 | 0 | 0 |
| 5. TTS 参数 | 23 | 1 | 22 | 0 | 0 |
| 6. 平台与运行时公共参数 | 91 | 3 | 88 | 6 | 14 |
| **合计** | **170** | **8** | **162** | **6** | **14** |

### 7.3 可行性分级定义

| 级别 | 定义 | 典型改造路径 | 建议优先级 |
|---|---|---|---|
| 高 | 已有运行时写入路径，或值在每次调用处读取并与对象生命周期无关 | 扩白名单 + 逐次读取，改动 1–2 个文件 | P0：一个迭代内可做 |
| 中 | 值已逐请求读取但未入 schema；或需重建轻量客户端 | 扩 `RuntimeConfig.session` + 客户端原子换入 | P1：需回归测试与灰度 |
| 低 | 需重建 handler / 模型 / 池，牵涉显存与在途会话 | 双实例蓝绿切换 + 优雅 drain | P2：按业务需求立项 |
| 不可行 | 进程级绑定、导入期读取、安全凭据或源码常量 | 保持重启，靠上层蓝绿部署 | 不改造 |

> 表中「可行性」只回答**技术上能否动态生效**，不等于「现在就该改」。安全敏感项即使技术上可做，也因 fail-closed 语义判为不可行。

### 7.4 逐参数评估（162 个仅重启参数）

> 表内「§原行」为 §2–§6 中的原编号，便于回查。已可运行时生效的 8 项见 7.5，不再重复。

#### 7.4.1 VAD 参数

| §原行 | 参数 | 当前生效 | 可行性 | 判断依据 | 改造建议 |
|---:|---|---|---|---|---|
| 1 | `vad` | 启动 | **低** | 后端选择决定 handler 类型与模型加载方式，不是单个可变字段 | 走蓝绿实例切换：先以新 `vad` 后端起一组 pipeline 并预热，探活通过后切流量；需同时满足新后端的依赖与权重前置条件 |
| 3 | `sample_rate` | 启动 | **低** | VAD 采样率与上游音频流、`CHUNK_SAMPLES` 强绑定，运行中改值会让所有分块判停失准 | 不建议单独动态化；如确需多采样率，应作为新 pipeline 实例的一等配置并整体切换 |
| 5 | `min_speech_ms` | 启动 | **高** | 数值/开关在每次判定或每轮调用处读取，`vad_handler` 已存在同类的运行时写入路径（`thresh` / `min_silence_ms`） | 扩展 `session.update` 白名单：在 `config_sync.py` 的 `HOT_SESSION_FIELDS` 与 `hot_update_service.py` 树形剪枝中登记，写入点复用 handler 的可变字段；会话结束恢复启动值 |
| 6 | `min_speech_continuation_ms` | 启动 | **高** | 数值/开关在每次判定或每轮调用处读取，`vad_handler` 已存在同类的运行时写入路径（`thresh` / `min_silence_ms`） | 扩展 `session.update` 白名单：在 `config_sync.py` 的 `HOT_SESSION_FIELDS` 与 `hot_update_service.py` 树形剪枝中登记，写入点复用 handler 的可变字段；会话结束恢复启动值 |
| 7 | `max_speech_ms` | 启动 | **高** | 数值/开关在每次判定或每轮调用处读取，`vad_handler` 已存在同类的运行时写入路径（`thresh` / `min_silence_ms`） | 扩展 `session.update` 白名单：在 `config_sync.py` 的 `HOT_SESSION_FIELDS` 与 `hot_update_service.py` 树形剪枝中登记，写入点复用 handler 的可变字段；会话结束恢复启动值 |
| 8 | `speech_pad_ms` | 启动 | **高** | 数值/开关在每次判定或每轮调用处读取，`vad_handler` 已存在同类的运行时写入路径（`thresh` / `min_silence_ms`） | 扩展 `session.update` 白名单：在 `config_sync.py` 的 `HOT_SESSION_FIELDS` 与 `hot_update_service.py` 树形剪枝中登记，写入点复用 handler 的可变字段；会话结束恢复启动值 |
| 9 | `audio_enhancement` | 启动 | **低** | 需加载 DeepFilterNet 模型并挂进音频前处理链，不是简单布尔开关 | 可预加载增强器再用标志位旁路，此时可降为「中」；若按需加载则必须重建 handler |
| 10 | `speculative_reopen_ms` | 启动 | **高** | 数值/开关在每次判定或每轮调用处读取，`vad_handler` 已存在同类的运行时写入路径（`thresh` / `min_silence_ms`） | 扩展 `session.update` 白名单：在 `config_sync.py` 的 `HOT_SESSION_FIELDS` 与 `hot_update_service.py` 树形剪枝中登记，写入点复用 handler 的可变字段；会话结束恢复启动值 |
| 11 | `unanswered_reopen_ms` | 启动 | **高** | 数值/开关在每次判定或每轮调用处读取，`vad_handler` 已存在同类的运行时写入路径（`thresh` / `min_silence_ms`） | 扩展 `session.update` 白名单：在 `config_sync.py` 的 `HOT_SESSION_FIELDS` 与 `hot_update_service.py` 树形剪枝中登记，写入点复用 handler 的可变字段；会话结束恢复启动值 |
| 12 | `short_segment_merge_ms` | 启动 | **高** | 迭代器内为普通时间阈值，但存在硬约束 `>= min_silence_ms` | 加入热更新白名单时必须成对校验 `min_silence_ms` 的新值，违反约束整批拒绝而非逐个拒绝 |
| 13 | `enable_realtime_transcription` | 启动 | **中** | 打开/关闭会改变 partial 事件流的产生与订阅，涉及已推送事件的收尾 | 改为逐会话标志并在关闭时发最后一次 final 事件；客户端需容忍事件流突然停止 |
| 14 | `realtime_processing_pause` | 启动 | **高** | 数值/开关在每次判定或每轮调用处读取，`vad_handler` 已存在同类的运行时写入路径（`thresh` / `min_silence_ms`） | 扩展 `session.update` 白名单：在 `config_sync.py` 的 `HOT_SESSION_FIELDS` 与 `hot_update_service.py` 树形剪枝中登记，写入点复用 handler 的可变字段；会话结束恢复启动值 |
| 15 | `smart_turn` | 启动 | **高** | ONNX 模型可常驻内存，只在 VAD 语音→静音边界用一个布尔判定是否调用 | 把 `smart_turn` 提升为 `RuntimeConfig.session` 字段，判停处读取；关闭后不卸载模型，避免反复加载 |
| 16 | `smart_turn_model_path` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 17 | `smart_turn_threshold` | 启动 | **高** | 数值/开关在每次判定或每轮调用处读取，`vad_handler` 已存在同类的运行时写入路径（`thresh` / `min_silence_ms`） | 扩展 `session.update` 白名单：在 `config_sync.py` 的 `HOT_SESSION_FIELDS` 与 `hot_update_service.py` 树形剪枝中登记，写入点复用 handler 的可变字段；会话结束恢复启动值 |
| 18 | `smart_turn_max_wait_ms` | 启动 | **高** | 数值/开关在每次判定或每轮调用处读取，`vad_handler` 已存在同类的运行时写入路径（`thresh` / `min_silence_ms`） | 扩展 `session.update` 白名单：在 `config_sync.py` 的 `HOT_SESSION_FIELDS` 与 `hot_update_service.py` 树形剪枝中登记，写入点复用 handler 的可变字段；会话结束恢复启动值 |
| 19 | `smart_turn_incomplete_delay_ms` | 启动 | **高** | 数值/开关在每次判定或每轮调用处读取，`vad_handler` 已存在同类的运行时写入路径（`thresh` / `min_silence_ms`） | 扩展 `session.update` 白名单：在 `config_sync.py` 的 `HOT_SESSION_FIELDS` 与 `hot_update_service.py` 树形剪枝中登记，写入点复用 handler 的可变字段；会话结束恢复启动值 |
| 20 | `smart_turn_cpu_count` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 21 | `vad_firered_model_dir` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 22 | `vad_firered_use_gpu` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
#### 7.4.2 STT 参数

| §原行 | 参数 | 当前生效 | 可行性 | 判断依据 | 改造建议 |
|---:|---|---|---|---|---|
| 23 | `qwen3_asr_model_name` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 24 | `qwen3_asr_device` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 25 | `qwen3_asr_torch_dtype` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 27 | `qwen3_asr_prompt` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 28 | `qwen3_asr_gen_max_new_tokens` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
#### 7.4.3 LLM 参数

| §原行 | 参数 | 当前生效 | 可行性 | 判断依据 | 改造建议 |
|---:|---|---|---|---|---|
| 29 | `model_name` | 启动 | **低** | 远端模型名决定 provider 路由与音频输入能力，换名等价于换后端 | 模型名调整仍走发布重建；如需无损切换需 provider 侧支持并行注册名 |
| 30 | `user_role` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 31 | `init_chat_role` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 33 | `chat_size` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 34 | `stream_batch_sentences` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 35 | `enable_lang_prompt` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 36 | `compact_history` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 37 | `model_name` | 启动 | **低** | `chat-completions` 覆写的模型名默认，运行时改会改变音频输入能力判断 | 同 §4.2 的 `model_name`，维持启动固化 |
| 38 | `responses_api_api_key` | 启动 | **中** | 技术上可随 HTTP client 一起换入，但属于额度凭据，不应走 session 通道 | 仅允许管理员端点触发客户端重建；密钥仍由 `{env:}` 注入，不进 `RuntimeConfig.session`、不回显 |
| 39 | `responses_api_base_url` | 启动 | **中** | 凭据 / 端点由 HTTP 客户端对象在构造时持有，改值需换客户端而非换参数 | 把客户端改为可替换的懒加载缓存，配置变更时以新 client 原子换入，在途请求继续用旧实例；密钥仍只从 `{env:}` 注入，不落 session |
| 40 | `responses_api_stream` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 41 | `responses_api_disable_thinking` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 42 | `responses_api_reasoning_effort` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 43 | `responses_api_audio_max_tokens` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 44 | `responses_api_audio_temperature` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 45 | `responses_api_audio_content_type` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 46 | `responses_api_audio_history_turns` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 47 | `responses_api_provider_unavailable_message` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 48 | `llm_device` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 49 | `llm_torch_dtype` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 50 | `llm_load_in_8bit` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 51 | `llm_load_in_4bit` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 52 | `llm_gen_max_new_tokens` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 53 | `llm_gen_min_new_tokens` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 54 | `llm_gen_temperature` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 55 | `llm_gen_do_sample` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 56 | `llm_is_vlm` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
#### 7.4.4 TTS 参数

| §原行 | 参数 | 当前生效 | 可行性 | 判断依据 | 改造建议 |
|---:|---|---|---|---|---|
| 57 | `qwen3_tts_model_name` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 58 | `qwen3_tts_device` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 59 | `qwen3_tts_dtype` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 60 | `qwen3_tts_attn_implementation` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 61 | `qwen3_tts_backend` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 62 | `qwen3_tts_ggml_quantization` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 63 | `qwen3_tts_gguf_talker_path` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 64 | `qwen3_tts_gguf_codec_path` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 65 | `qwen3_tts_ref_cache_dir` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 66 | `qwen3_tts_ref_audio` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 67 | `qwen3_tts_ref_spk` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 68 | `qwen3_tts_ref_rvq` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 69 | `qwen3_tts_ref_text` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 71 | `qwen3_tts_instruct` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 72 | `qwen3_tts_xvec_only` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 73 | `qwen3_tts_parity_mode` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 74 | `qwen3_tts_non_streaming_mode` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 75 | `qwen3_tts_mlx_quantization` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 76 | `qwen3_tts_language` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 77 | `qwen3_tts_streaming_chunk_size` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 78 | `qwen3_tts_max_new_tokens` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 79 | `qwen3_tts_blocksize` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
#### 7.4.5 平台与运行时公共参数

| §原行 | 参数 | 当前生效 | 可行性 | 判断依据 | 改造建议 |
|---:|---|---|---|---|---|
| 80 | `host` | 启动 | **不可行** | socket 绑定在进程启动时完成，运行中无法改监听地址 | 保持重启；用上层蓝绿部署实现无损迁移 |
| 81 | `port` | 启动 | **不可行** | 同 `host`，端口由已监听的 socket 持有 | 保持重启；同时需同步 compose 映射与探活配置 |
| 82 | `num_pipelines` | 启动 | **低** | 池在 `s2s_pipeline.py` 按 `range(num_pipelines)` 一次性创建，`/v1/pool` 目前只读 | 需新增扩缩容 API + drain + 新实例预热；扩缩容期间总显存预算需按峰值计算 |
| 83 | `-np` | 容器 | **不可行** | 进程级 socket / 构建参数 / 第三方库导入期读取，运行期改值无法回溯到已绑定的资源 | 保持重启；无损切换只能靠上层蓝绿部署 + 流量切换，不建议在进程内做「假热更新」 |
| 84 | 池满拒绝 | 固定 | **不可行** | 固定行为由路由代码决定，不是可配置值 | 无改造必要；如需排队能力须新增队列实现，属新功能而非配置热更新 |
| 85 | `llm_proxy_connect_timeout_s` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 86 | `openai_stt_timeout` | 启动 | **中** | 凭据 / 端点由 HTTP 客户端对象在构造时持有，改值需换客户端而非换参数 | 把客户端改为可替换的懒加载缓存，配置变更时以新 client 原子换入，在途请求继续用旧实例；密钥仍只从 `{env:}` 注入，不落 session |
| 87 | `openai_tts_timeout` | 启动 | **中** | 凭据 / 端点由 HTTP 客户端对象在构造时持有，改值需换客户端而非换参数 | 把客户端改为可替换的懒加载缓存，配置变更时以新 client 原子换入，在途请求继续用旧实例；密钥仍只从 `{env:}` 注入，不落 session |
| 88 | `connection_retry_timeout_s` | 启动 | **中** | 客户端参数只在建连 / 重连时使用，会话中途改值不影响已打开的音频流 | 客户端侧改为可热替换的连接参数，标记「下次重连生效」并显式提示用户；服务端不参与 |
| 89 | `request_timeout_s`（LLM）〔只读〕 | 固定 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 90 | 重试策略〔只读〕 | 固定 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 91 | `PIPELINE_SAMPLE_RATE`〔只读〕 | 固定 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 92 | `CHUNK_SAMPLES`〔只读〕 | 固定 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 93 | `send_rate` | 启动 | **中** | 客户端参数只在建连 / 重连时使用，会话中途改值不影响已打开的音频流 | 客户端侧改为可热替换的连接参数，标记「下次重连生效」并显式提示用户；服务端不参与 |
| 94 | `recv_rate` | 启动 | **中** | 客户端参数只在建连 / 重连时使用，会话中途改值不影响已打开的音频流 | 客户端侧改为可热替换的连接参数，标记「下次重连生效」并显式提示用户；服务端不参与 |
| 95 | `chunk_size` | 启动 | **中** | 客户端参数只在建连 / 重连时使用，会话中途改值不影响已打开的音频流 | 客户端侧改为可热替换的连接参数，标记「下次重连生效」并显式提示用户；服务端不参与 |
| 96 | `playback_buffer_ms` | 启动 | **中** | 客户端参数只在建连 / 重连时使用，会话中途改值不影响已打开的音频流 | 客户端侧改为可热替换的连接参数，标记「下次重连生效」并显式提示用户；服务端不参与 |
| 97 | `openai_tts_sample_rate` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 98 | `device` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 99 | `mac_optimal_settings` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 100 | `torch_num_threads` | 启动 | **低** | `torch.set_num_threads` 是进程全局状态，但对已创建的算子线程池不一定生效 | 可尝试运行时调用并实测；无法保证生效时按「不可行」处理，维持启动固化 |
| 101 | `diarization` | 启动 | **低** | 开启需加载分离模型并改变转写链路拓扑 | 以整组 pipeline 蓝绿切换；不建议逐会话开关 |
| 102 | `diarization_model_name` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 103 | `diarization_revision` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 104 | `diarization_device` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 105 | `diarization_dtype` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 106 | `diarization_streaming_mode` | 启动 | **中** | 生成类参数虽在请求构造处读取，但未进入 session schema，需同时改白名单与读取回退链 | 在 `RuntimeConfig.session` 增字段并放行白名单，读取点改为 `session → 启动默认` 回退；注意 `max_tokens` 与流式批次的联动需回归测试 |
| 107 | `diarization_threshold` | 启动 | **高** | 若分离模型常驻，阈值只是推理后处理参数 | 提升为逐会话阈值并沿用现有 VAD 的白名单扩展方式 |
| 108 | `detect_llm_output_language` | 启动 | **高** | 检测器已在启动时预热，运行中只需决定是否调用 | 提升为逐会话布尔标志，在输出语言探测处读取；无需重建检测器 |
| 109 | `enable_llm_proxy` | 启动 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 110 | `openai_stt_api_key` | 启动 | **中** | 同上：客户端可原子换入，但密钥不可经会话下发 | 管理员端点 + secrets manager；`OPENAI_API_KEY` 隐式回退链应一并清理 |
| 111 | `openai_tts_api_key` | 启动 | **中** | 同上：客户端可原子换入，但密钥不可经会话下发 | 管理员端点 + secrets manager；`OPENAI_API_KEY` 隐式回退链应一并清理 |
| 112 | `USAGE_HASH_SECRET` | 启动 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 113 | `UNLIMITED_ORGS` | 启动 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 114 | `AUTH_DEBUG` | 启动 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 115 | `S2S_ADMIN_TOKEN` | 启动 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 116 | `S2S_INTERNAL_TOKEN` | 启动 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 117 | CORS 策略〔只读〕 | 固定 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 118 | Realtime API 鉴权〔只读〕 | 固定 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 119 | `log_level` | 启动 | **高** | Python `logging` 原生支持运行时改级别 | 控制台下发后调用 `logging.getLogger().setLevel()`；无需重启也无会话边界 |
| 120 | `log_transcripts` | 启动 | **高** | 仅控制写日志前的分支判断 | 改为逐条日志读取标志位；注意该开关是隐私项，变更必须写审计日志 |
| 121 | `enable_live_transcription` | 启动 | **高** | 纯日志 / 开关类标志，标准库可运行时调整或无状态依赖 | 改为 `logger.setLevel()` 与逐次读取的标志位，接入 `config_sync.py` 的 hot 链路即可 |
| 122 | `live_transcription_update_interval` | 启动 | **高** | 仅控制 partial 事件节流间隔，无状态依赖 | 改为每次事件调度时读取当前值，定时器按新间隔重排 |
| 123 | `MODEL_METRICS_LOG` | 启动 | **中** | `RotatingFileHandler` 可在运行时新建，但旧 handler 需要正确关闭 | 配置变更时创建新 handler 并原子替换，保留旧 handler 排空在途写入 |
| 124 | `MODEL_METRICS_LOG_MAX_BYTES` | 启动 | **高** | 仅影响下一轮滚动判定 | 更新 handler 的 `maxBytes` 属性即可 |
| 125 | `MODEL_METRICS_LOG_BACKUPS` | 启动 | **高** | 仅影响下一轮滚动保留份数 | 更新 handler 的 `backupCount` 属性即可 |
| 126 | 监控端点〔只读〕 | 固定 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 127 | `HF_HUB_OFFLINE` | 启动 | **不可行** | 进程级 socket / 构建参数 / 第三方库导入期读取，运行期改值无法回溯到已绑定的资源 | 保持重启；无损切换只能靠上层蓝绿部署 + 流量切换，不建议在进程内做「假热更新」 |
| 128 | `TRANSFORMERS_OFFLINE` | 启动 | **不可行** | 进程级 socket / 构建参数 / 第三方库导入期读取，运行期改值无法回溯到已绑定的资源 | 保持重启；无损切换只能靠上层蓝绿部署 + 流量切换，不建议在进程内做「假热更新」 |
| 129 | `TOKENIZERS_PARALLELISM` | 启动 | **不可行** | 进程级 socket / 构建参数 / 第三方库导入期读取，运行期改值无法回溯到已绑定的资源 | 保持重启；无损切换只能靠上层蓝绿部署 + 流量切换，不建议在进程内做「假热更新」 |
| 130 | `HF_ENDPOINT` | 启动 | **不可行** | 进程级 socket / 构建参数 / 第三方库导入期读取，运行期改值无法回溯到已绑定的资源 | 保持重启；无损切换只能靠上层蓝绿部署 + 流量切换，不建议在进程内做「假热更新」 |
| 131 | `HF_HUB_ENABLE_PROGRESS_BARS` | 启动 | **不可行** | 进程级 socket / 构建参数 / 第三方库导入期读取，运行期改值无法回溯到已绑定的资源 | 保持重启；无损切换只能靠上层蓝绿部署 + 流量切换，不建议在进程内做「假热更新」 |
| 132 | `MODELSCOPE_ENDPOINT` | 启动 | **不可行** | 进程级 socket / 构建参数 / 第三方库导入期读取，运行期改值无法回溯到已绑定的资源 | 保持重启；无损切换只能靠上层蓝绿部署 + 流量切换，不建议在进程内做「假热更新」 |
| 133 | `GPUSTACK_BASE_URL` | 启动 | **中** | 远端网关地址由 OpenAI 兼容 client 持有，换址需重建 client | 懒加载 client + 原子换入；在途流式请求保留旧 client，新请求用新地址 |
| 134 | `GPUSTACK_MODEL` | 启动 | **中** | 远端模型名是请求体字段，可逐请求替换，但会改变音频输入能力 | 提升为运行时字段前必须重新校验能力位；`stt=none` 时禁止切换到不支持音频的模型 |
| 135 | `GPUSTACK_API_KEY` | 启动 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 136 | `SERPER_API_KEY` | 启动 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 137 | `RTC_ICE_SERVERS` | 启动 | **中** | 客户端参数只在建连 / 重连时使用，会话中途改值不影响已打开的音频流 | 客户端侧改为可热替换的连接参数，标记「下次重连生效」并显式提示用户；服务端不参与 |
| 138 | `OPENAI_API_KEY` | 启动 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 139 | `SILERO_VAD_REPO_PATH` | 启动 | **低** | 模型 / 权重 / 设备 / 精度在 `setup()` 中一次性加载并缓存，无法原地换参 | 需双实例蓝绿切换（新旧 handler 并存 → 预热 → 原子换流量 → 释放旧实例），显存预算需 ×2；仅在确有灰度切换需求时立项 |
| 140 | `schema_version` | 启动 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 141 | 顶层结构 | 启动 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 142 | `{env: NAME}` 引用 | 启动 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 143 | 路径字段解析 | 启动 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 144 | 文件体积上限〔只读〕 | 固定 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 145 | 嵌套深度上限〔只读〕 | 固定 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 146 | `DOCKERFILE`（build arg） | 容器 | **不可行** | 进程级 socket / 构建参数 / 第三方库导入期读取，运行期改值无法回溯到已绑定的资源 | 保持重启；无损切换只能靠上层蓝绿部署 + 流量切换，不建议在进程内做「假热更新」 |
| 147 | `BASE_IMAGE`（build arg） | 容器 | **不可行** | 进程级 socket / 构建参数 / 第三方库导入期读取，运行期改值无法回溯到已绑定的资源 | 保持重启；无损切换只能靠上层蓝绿部署 + 流量切换，不建议在进程内做「假热更新」 |
| 148 | `PIPELINE_PORT`（host 侧） | 容器 | **不可行** | 进程级 socket / 构建参数 / 第三方库导入期读取，运行期改值无法回溯到已绑定的资源 | 保持重启；无损切换只能靠上层蓝绿部署 + 流量切换，不建议在进程内做「假热更新」 |
| 149 | `PIPELINE_GPU_ID`（host 侧） | 容器 | **不可行** | 进程级 socket / 构建参数 / 第三方库导入期读取，运行期改值无法回溯到已绑定的资源 | 保持重启；无损切换只能靠上层蓝绿部署 + 流量切换，不建议在进程内做「假热更新」 |
| 150 | GPU 能力声明〔只读〕 | 固定 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 151 | 权重/缓存卷〔只读〕 | 固定 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 152 | Silero VAD 卷〔只读〕 | 固定 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 153 | 重启策略 | 容器 | **不可行** | 进程级 socket / 构建参数 / 第三方库导入期读取，运行期改值无法回溯到已绑定的资源 | 保持重启；无损切换只能靠上层蓝绿部署 + 流量切换，不建议在进程内做「假热更新」 |
| 154 | 健康检查〔只读〕 | 固定 | **不可行** | 安全敏感、fail-closed 凭据或源码常量；运行时改写会破坏安全语义或须改源码 | 不建议动态化；维持启动固化，密钥轮换走重建 + 审计 |
| 155 | `url` | 启动 | **中** | 客户端参数只在建连 / 重连时使用，会话中途改值不影响已打开的音频流 | 客户端侧改为可热替换的连接参数，标记「下次重连生效」并显式提示用户；服务端不参与 |
| 157 | `api_key` | 启动 | **中** | 客户端连接凭据，仅建连时读取 | 仅允许客户端侧下次重连生效，禁止经 session.update 下发 |
| 158 | `send_rate` / `recv_rate` | 启动 | **中** | 客户端参数只在建连 / 重连时使用，会话中途改值不影响已打开的音频流 | 客户端侧改为可热替换的连接参数，标记「下次重连生效」并显式提示用户；服务端不参与 |
| 159 | `playback_buffer_ms` | 启动 | **中** | 客户端参数只在建连 / 重连时使用，会话中途改值不影响已打开的音频流 | 客户端侧改为可热替换的连接参数，标记「下次重连生效」并显式提示用户；服务端不参与 |
| 160 | `chunk_size` | 启动 | **中** | 客户端参数只在建连 / 重连时使用，会话中途改值不影响已打开的音频流 | 客户端侧改为可热替换的连接参数，标记「下次重连生效」并显式提示用户；服务端不参与 |
| 161 | `input_device` / `output_device` | 启动 | **中** | 客户端参数只在建连 / 重连时使用，会话中途改值不影响已打开的音频流 | 客户端侧改为可热替换的连接参数，标记「下次重连生效」并显式提示用户；服务端不参与 |
| 164 | `print_json` | 启动 | **高** | 纯日志 / 开关类标志，标准库可运行时调整或无状态依赖 | 改为 `logger.setLevel()` 与逐次读取的标志位，接入 `config_sync.py` 的 hot 链路即可 |
| 165 | `block_mic_during_playback` | 启动 | **中** | 客户端参数只在建连 / 重连时使用，会话中途改值不影响已打开的音频流 | 客户端侧改为可热替换的连接参数，标记「下次重连生效」并显式提示用户；服务端不参与 |
| 166 | `log_transcripts` | 启动 | **高** | 仅控制写日志前的分支判断 | 改为逐条日志读取标志位；注意该开关是隐私项，变更必须写审计日志 |
| 167 | `connection_retry_timeout_s` | 启动 | **中** | 客户端参数只在建连 / 重连时使用，会话中途改值不影响已打开的音频流 | 客户端侧改为可热替换的连接参数，标记「下次重连生效」并显式提示用户；服务端不参与 |
| 168 | `tools` | 启动 | **中** | 工具声明是每轮请求体的一部分，技术上可逐会话替换 | 需防提示词注入：工具 schema 必须由服务端白名单提供，不接受客户端提交的任意 schema |
| 169 | `tool_executor` | 启动 | **不可行** | 可执行回调无法跨配置序列化，且让配置拥有任意代码执行能力是重大安全面 | 维持代码内注册；只对工具「开关/参数」做动态化，执行器本体固定 |
| 170 | `tool_response_create` | 启动 | **中** | 工具结果是否触发新一轮回复是服务端编排开关，不是客户端连接参数 | 提升为服务端 session 字段，由服务端控制；不接受客户端提交该值，避免绕过轮次判定 |

> 共评估 162 行。§原行 29/37 的 `model_name` 是两处不同语义的覆写，§原行 93/158 的 `send_rate` 与 95/160 的 `chunk_size` 是服务端客户端同名参数，均按各自作用域分别判断。

### 7.5 已支持运行时生效的 8 项（无需改造，但需知道边界）

| §原行 | 参数 | 生效 | 通道 | 边界 |
|---:|---|---|---|---|
| 2 | `thresh` | 启动+热更新 | `session.update.audio.input.turn_detection.threshold` → `iterator.threshold` | 会话结束恢复启动值；`firered` 下同步改写包内阈值 |
| 4 | `min_silence_ms` | 启动+热更新 | `session.update.audio.input.turn_detection.silence_duration_ms` → `iterator.min_silence_samples` | 会话结束恢复启动值；`firered` 下按 10 ms 帧取整 |
| 26 | `qwen3_asr_language` | 启动+热更新 | `session.update.audio.input.transcription.language` → STT 每请求读取 | 需通过后端语言能力校验；会话结束恢复启动值 |
| 32 | `init_chat_prompt` | 启动+热更新 | `session.update.instructions` → LLM 每轮生成时读取 | 只作用于当前连接，覆盖服务端默认人设 |
| 70 | `qwen3_tts_speaker` | 启动+热更新 | `session.update.audio.output.voice` → `handler.speaker` | 仅 `qwen3` 命中支持列表时生效，其他后端只回显（§5.4） |
| 156 | `model` | 启动+热更新 | `session.update.model` | 只记日志，本地后端忽略该值（实际不生效） |
| 162 | `instructions` | 热更新 | 客户端首帧 `session.update.instructions` | 覆盖服务端 `init_chat_prompt`；过长抬高首 token 延迟 |
| 163 | `voice` | 热更新 | 客户端首帧 `session.update.audio.output.voice` | 仅 `qwen3`（支持列表内）与 `kitten` 真正生效（§5.4） |

### 7.6 建议改造路线

> 分级统计：高 22 项 / 中 54 项 / 低 44 项 / 不可行 42 项（合计 162）。

| 阶段 | 改造项 | 做法 | 收益 / 风险 |
|---|---|---|---|
| P0（高可行性） | VAD 9 个数值/开关、日志 8 项、Smart Turn 开关、实时转写开关、语言检测开关 | 复用 `config_sync.py` hot 链路：`HOT_SESSION_FIELDS` + `hot_update_service.py` 白名单扩项；日志项直接用 `logger.setLevel` | 无需重建实例；风险是新增字段需补校验与会话回滚 |
| P1（中可行性） | LLM 生成类 17 项、TTS 生成类 7 项、STT 提示词/生成长度、3 个超时、远端 base_url | 扩 `RuntimeConfig.session`，读取点统一改为 `session → 启动默认`；HTTP client 改懒加载原子换入 | 覆盖大部分「调prompt/调温度/调音色」运营场景；需防止在途请求参数半新半旧 |
| P2（低可行性） | 模型名、设备、精度、量化、后端、`num_pipelines`、diarization、参考音频 | 蓝绿 handler + `/v1/pool` 扩缩容 API + 优雅 drain | 显存需 ×2，改造周期长；仅在有多版本灰度诉求时立项 |
| 不改造 | host/port、导入期环境变量、密钥/令牌、源码常量、compose/build arg | 维持重启；用上层蓝绿部署与流量切换实现无损升级 | 强行动态化会破坏 fail-closed 与可审计性 |

### 7.7 落地时的三个必检点

1. **白名单两处必须同步**：`console/backend/app/services/hot_update_service.py` 的树形剪枝（Chain B）与 `src/speech_to_speech/agent/config_sync.py` 的 `HOT_SESSION_FIELDS`（Chain A 落地侧）。只改一处会出现「控制台显示已生效、agent 推送被忽略」。
2. **目录标注必须同步**：`docs/parameter-catalog.yaml` 对应条目的 `effect: hot` / `startup` 驱动 `console/backend/app/config/_schema.py` 的 `ConfigItem.hot`；改完运行 `console/backend/scripts/validate_catalog_schema.py` 校验双向一致。
3. **会话回滚必须补齐**：仿照 `vad_handler.py` 的 `_configured_threshold` / `_configured_min_silence_samples`，为每个新增热字段保存启动值并在会话结束时恢复；否则长连接会永久带上一次热更新值。

---

## 8. 控制台自身配置项（61 项）

> §2–§7 覆盖 pipeline 与客户端；本章补齐 `parameter-catalog.yaml` 的 `console_parameters` 段，它与 `console/backend/app/config/_schema.py` 登记表双向一致（由 `console/backend/scripts/validate_catalog_schema.py` 把关）。
> **控制台配置不走 pipeline 的发布链路**：库 `param_config` 优先于 env，`_store.py` 有 2 s TTL 缓存并在 `set()` 后立即失效；`PUT /api/v1/config` 返回 `restartRequired` 汇总，标 `hot` 的项秒级生效。

### 8.1 生效方式分布

| stage | 条数 | `hot`（运行时生效） | `startup`（需重启控制台） |
|---|---:|---:|---:|
| `allocator` | 12 | 9 | 3 |
| `app` | 4 | 4 | 0 |
| `bootstrap` | 2 | 0 | 2 |
| `console` | 37 | 37 | 0 |
| `demo` | 6 | 6 | 0 |
| **合计** | **61** | **56** | **5** |

### 8.2 五个需重启项的逐项评估

| 参数 | 环境变量 | 作用 | 可行性 | 判断依据 | 改造建议 |
|---|---|---|---|---|---|
| `mode` | `ALLOCATOR_MODE` | 本地分配器模式：off 为单实例直连，local 为注册表选台 | **中** | 分配器实例在 FastAPI lifespan 中按模式构建，切换 `off ↔ local` 会改变选台拓扑与注册中心的交互方式 | 把选台策略抽成可替换对象，经管理员端点原子换入并 drain 在途会话；切换前必须先校验注册表可用性，否则应拒绝而非半切换 |
| `seed_path` | `INSTANCES_SEED_PATH` | 声明式实例 seed 文件路径；留空则以数据库为唯一来源 | **中** | seed 文件只在启动时读取并灌入实例表，运行中改路径不会自动重新对账 | 新增管理员端点触发「重新读取 seed + 幂等 upsert」，与数据库现状做差异预览后再应用；不建议自动监听文件变化 |
| `webrtc_hangup_enabled` | `INSTANCE_WEBRTC_HANGUP_ENABLED` | 是否注册跨机挂断代理路由 | **低** | 该开关决定是否在 app 启动时注册跨机挂断代理路由；FastAPI 路由表在运行期不可安全增删 | 改为「路由无条件注册 + handler 内读标志位」：这样开关本身可降为 hot，且失败时只返回明确的 disabled 响应而不是 404 |
| `default_admin_role` | `DEFAULT_ADMIN_ROLE` | 首次启动管理员角色 | **不可行** | 仅首次启动创建管理员时使用，运行中修改不构成对现有管理员的变更，反而制造权限认知偏差 | 维持启动固化；需要改管理员权限应走既有用户/角色管理 API，而不是 bootstrap 参数 |
| `default_admin_username` | `DEFAULT_ADMIN_USERNAME` | 首次启动创建的管理员用户名 | **不可行** | 同上，且属于 bootstrap 身份凭据，运行时改写会破坏审计链的连续性 | 维持启动固化；管理员变更走用户管理 API + 审计 |

> 这 5 项全部是 `ops` 暴露级别。即使技术上可改造，也必须保留管理员端点鉴权与审计留痕，不能下放到普通配置页任意切换。

### 8.3 已支持运行时生效的 56 项（索引）

> 这些项的 `effect: hot` 已驱动 `_schema.py` 的 `ConfigItem.hot = True`，经 `PUT /api/v1/config` 写库后由 `_store.invalidate()` 秒级生效；无需改造。下表按 stage 列出，完整字段定义以 `parameter-catalog.yaml` 的 `console_parameters` 段为准。

**`allocator`（9 项）**：`console_id` / `CONSOLE_ID`、`fail_threshold` / `INSTANCE_FAIL_THRESHOLD`、`grant_ttl_s` / `INSTANCE_GRANT_TTL_S`、`metric_retention_days` / `INSTANCE_METRIC_RETENTION_DAYS`、`probe_interval_s` / `INSTANCE_PROBE_INTERVAL_S`、`probe_timeout_s` / `INSTANCE_PROBE_TIMEOUT_S`、`queue_enabled` / `INSTANCE_QUEUE_ENABLED`、`recover_threshold` / `INSTANCE_RECOVER_THRESHOLD`、`usage_interval_s` / `INSTANCE_USAGE_INTERVAL_S`

**`app`（4 项）**：`cors_origins` / `CORS_ORIGINS`、`env` / `ENV`、`log_level` / `LOG_LEVEL`、`max_body_bytes` / `MAX_BODY_BYTES`

**`console`（37 项）**：`data_dir` / `DATA_DIR`、`lb_asr_timeout_s` / `LB_ASR_TIMEOUT_S`、`lb_audio_max_bytes` / `LB_AUDIO_MAX_BYTES`、`lb_capability_interval_s` / `LB_CAPABILITY_INTERVAL_S`、`lb_capability_probe_timeout_s` / `LB_CAPABILITY_PROBE_TIMEOUT_S`、`lb_emotion_timeout_s` / `LB_EMOTION_TIMEOUT_S`、`lb_failover_attempts` / `LB_FAILOVER_ATTEMPTS`、`lb_mode` / `CONSOLE_LB_MODE`、`lb_stateless_max_inflight` / `LB_STATELESS_MAX_INFLIGHT`、`lb_tts_timeout_s` / `LB_TTS_TIMEOUT_S`、`lb_upstream_ready_timeout_s` / `LB_UPSTREAM_READY_TIMEOUT_S`、`lb_voiceprint_timeout_s` / `LB_VOICEPRINT_TIMEOUT_S`、`log_dir` / `LOG_DIR`、`model_metrics_log` / `MODEL_METRICS_LOG`、`param_catalog_path` / `PARAM_CATALOG_PATH`、`param_config_dir` / `PARAM_CONFIG_DIR`、`pipeline_base_url` / `PIPELINE_BASE_URL`、`pipeline_container` / `PIPELINE_CONTAINER`、`pipeline_timeout_s` / `PIPELINE_TIMEOUT_S`、`restart_mode` / `RESTART_MODE`、`session_audio_max_bytes` / `SESSION_AUDIO_MAX_BYTES`、`session_audio_max_seconds` / `SESSION_AUDIO_MAX_SECONDS`、`session_data_dir` / `SESSION_DATA_DIR`、`session_record_enabled` / `SESSION_RECORD_ENABLED`、`session_retention_days` / `SESSION_RETENTION_DAYS`、`session_retention_max_days` / `SESSION_RETENTION_MAX_DAYS`、`static_dir` / `STATIC_DIR`、`supervisor_program` / `SUPERVISOR_PROGRAM`、`supervisor_socket` / `SUPERVISOR_SOCKET`、`verifier_mode` / `VERIFIER_MODE`、`voice_data_dir` / `VOICE_DATA_DIR`、`voice_max_bytes` / `VOICE_MAX_BYTES`、`voice_max_seconds` / `VOICE_MAX_SECONDS`、`voice_min_seconds` / `VOICE_MIN_SECONDS`、`voice_precompute_concurrency` / `VOICE_PRECOMPUTE_CONCURRENCY`、`voice_precompute_timeout_s` / `VOICE_PRECOMPUTE_TIMEOUT_S`、`voice_retention_max_days` / `VOICE_RETENTION_MAX_DAYS`

**`demo`（6 项）**：`load_balancer_url` / `LOAD_BALANCER_URL`、`oauth_client_id` / `OAUTH_CLIENT_ID`、`rtc_ice_servers` / `RTC_ICE_SERVERS`、`space_id` / `SPACE_ID`、`speech_to_speech_url` / `SPEECH_TO_SPEECH_URL`、`startup_greeting` / `STARTUP_GREETING`

### 8.4 控制台与 pipeline 热更新链的分工

| 链路 | 入口 | 作用范围 | 持久化 | 关键约束 |
|---|---|---|---|---|
| 控制台配置（本章 hot 项） | `PUT /api/v1/config` → `param_config` → `_store.invalidate()` | 控制台自身（探针节奏、摘除阈值、上限等） | 是，写库 | 库值优先于 env；2 s 缓存 |
| Chain A：agent 拉取 | `GET /api/v1/agent/config` → `config_sync.py` 原子替换 YAML → `effects` 分流 | pipeline 启动默认值 | 是（YAML 文件） | `hot`→会话更新、`start`→supervisor 重启、`container`→只记声明 |
| Chain B：会话热更新 | `/api/v1/sessions/update` → `/internal/sessions/update` → `/admin/sessions/update` | 已连接会话 | 否，会话结束恢复启动值 | token fail-closed；只放行白名单字段 |

> 三条链不要混用：改控制台探针频率是 Chain 0；改「下次会话的默认系统提示词」要 Chain A；改「当前所有在线会话的提示词」才是 Chain B。若只做 Chain B，新连接仍读旧 YAML。

---

## 附录 A：三条端到端样例

### A.1 重启链路（调并发 + 判停 + 系统提示）

场景：并发 1 → 2，判停从 450ms 回到 700ms 纯静音，并把回复限短。全部参数 `生效=启动`，必须重建容器。

```yaml
# config/prod.yaml —— 重启链路样例
schema_version: 1

runtime:
  log_level: info
  log_transcripts: false          # 隐私开关：保持关闭
  server:
    host: 0.0.0.0                 # 容器内必须 0.0.0.0
    port: 8765                    # 需与端口映射一致

blocks:
  vad:
    kind: vad
    backend: silero
    settings:
      thresh: 0.6
      min_silence_ms: 700         # 纯静音判停
      min_speech_ms: 384
      speech_pad_ms: 500
      speculative_reopen_ms: 0    # 规避重复转写
      unanswered_reopen_ms: 0
      smart_turn: false
  stt:
    kind: stt
    backend: qwen3-asr
    settings:
      qwen3_asr_model_name: /root/.cache/qwen3-asr-model-hf
      qwen3_asr_device: cuda
      qwen3_asr_torch_dtype: bfloat16
      qwen3_asr_language: zh
      qwen3_asr_gen_max_new_tokens: 128
  llm:
    kind: llm
    backend: chat-completions
    settings:
      model_name: Qwen3-8B
      responses_api_base_url: http://192.168.40.30/v1-openai
      responses_api_api_key: {env: GPUSTACK_API_KEY}   # 密钥不进库；{env:} 是映射，不能加引号
      responses_api_stream: true
      responses_api_reasoning_effort: ""
      stream_batch_sentences: 1
      init_chat_role: system
      init_chat_prompt: "You are a helpful voice assistant. Keep every reply very short."
  tts:
    kind: tts
    backend: qwen3
    settings:
      qwen3_tts_model_name: /root/.cache/qwen3-tts-model
      qwen3_tts_backend: torch
      qwen3_tts_device: cuda
      qwen3_tts_non_streaming_mode: false
      qwen3_tts_streaming_chunk_size: 4

pipelines:
  prod:
    num_pipelines: 2              # 需 <= floor(可用显存×0.85 / 4.6GB)
    stages: {vad: vad, stt: stt, llm: llm, tts: tts}
```

| 步骤 | 动作 | 失败处理 |
|---|---|---|
| 1 | `validator` 调 `load_config` + `validate_config` | 字段错误退回 draft，标出 `file:symbol` 与期望类型 |
| 2 | `renderer` 写 `config/prod.yaml`，旧版备份为 `prod.yaml.bak.<version>` | 写失败保留旧文件并告警 |
| 3 | 同步写 `.env`（只含 `GPUSTACK_API_KEY` 等 `ops` 字段） | `.env` 权限固定 0600 |
| 4 | `docker compose up -d --force-recreate pipeline` | 失败读 `docker logs --tail 200`，进步骤 7 |
| 5 | 轮询 `GET /v1/pool` 直到 `size == 2` | 超时 180s 视为失败 |
| 6 | 发一次真实 WebSocket 会话探活（可选） | 失败进步骤 7 |
| 7 | 恢复备份 + 重建 + 再探 `/v1/pool` | 再失败则告警人工介入 |

> **YAML 如何进容器**：文件模式只接受 `-f/--file` 与 `--name`（`cli.py:_run_file_command`），其余参数必须写进 YAML。compose 的 `command` 需改为 `speech-to-speech serve -f /app/config/prod.yaml --name prod`，并把 `config/` 以只读卷挂到 `/app/config`。

### A.2 热更新链路（不动容器改会话行为）

真正能改的只有 4 类字段（见 §0.4 第 5 条）。VAD 的 `threshold` 与 `silence_duration_ms` **属于可热更新**，这是本次修订新增的结论。

```http
POST /admin/sessions/update
Authorization: Bearer <ADMIN_TOKEN>
Content-Type: application/json

{
  "session": {
    "instructions": "你是简洁的语音助手，每次回复不超过两句话，跟随用户语言。",
    "audio": {
      "input": {
        "turn_detection": { "threshold": 0.65, "silence_duration_ms": 600 }
      }
    }
  },
  "scope": "all"
}
```

| 字段 | 真实生效 | 说明 / 证据 |
|---|---|---|
| `instructions` | 是 | `response.instructions or runtime_config.session.instructions` |
| `audio.input.turn_detection.threshold` | 是 | 直接写 `iterator.threshold`（`vad_handler.py:249`）|
| `audio.input.turn_detection.silence_duration_ms` | 是 | 直接写 `iterator.min_silence_samples`（`vad_handler.py:252`）|
| `audio.input.turn_detection.create_response` / `interrupt_response` | 是 | `runtime_config.py:59-88` |
| `audio.input.transcription.language` | 是 | 需通过后端语言能力校验（`handlers/session.py:42-64`）|
| `audio.output.voice` | 条件生效 | `qwen3` 命中支持列表时改音色；其他后端只回显（§5.4）|
| `model` | **否** | 只记日志（`handlers/session.py:66-68`）|

| 场景 | 结果 |
|---|---|
| 已连接会话 | 立刻写入 `RuntimeConfig`，下一次 VAD 判定 / LLM / TTS 调用即读到新值 |
| 会话结束 | VAD 恢复启动值（`_configured_threshold` / `_configured_min_silence_samples`）|
| 新连接 | 仍读 YAML 种子；要改默认必须走 A.1 |
| 字段与 Realtime schema 不匹配 | `400 invalid_request_error`，附字段错误计数（不是默默丢弃）|
| 语言不被当前 STT/TTS 支持 | `invalid_request_error`（`handlers/session.py:55-63`）|
| 目标会话已释放 | `failed: [{session_id, error: "session_gone"}]`，其余会话照常生效 |

> **访问前提**：`/admin/sessions/update` **已在源码实现**（`websocket_router.py:796-871`），但受 `S2S_ADMIN_TOKEN` 保护且 **fail-closed**：未配置该变量时路由返回 `503 admin_disabled`，只留下重启链路；token 不匹配返回 `401`。控制台侧走 `/internal/sessions/update` + `S2S_INTERNAL_TOKEN`。`scope` 支持 `all` / `pipeline`（需整数 `target`）/ `session`（需 session id）。**热更新不持久**：新连接仍读 YAML 种子，要存活于重启的修改必须走 A.1 发布。

### A.3 回滚链路（健康检查失败自动回退）

场景：A.1 发布 `num_pipelines=2` 后 OOM，容器反复重启，`/v1/pool` 起不来。

| 步骤 | 动作 | 证据 |
|---|---|---|
| 1 | 发布 v8（`num_pipelines: 2`） | 记录内容哈希与操作人 |
| 2 | 180s 内 `/v1/pool` 未返回 200 | 记录状态码与耗时 |
| 3 | 抓取 OOM / 启动失败堆栈 | 写入 v8 审计附言 |
| 4 | 恢复 `prod.yaml.bak.v7` | SHA-256 与 v7 记录一致 |
| 5 | `docker compose up -d --force-recreate pipeline` | 返回码为 0 |
| 6 | 再探 `/v1/pool`，要求 `size == 1` 且 `in_use == 0` | 通过则标记回滚完成 |
| 7 | 仍失败 → 回滚到 v6 并告警 | 连续两次失败视为需要人工介入 |

**回滚边界**：只回滚文件与容器，已建立连接全部断开（固有代价）；`ops` 字段（密钥、GPU ID、端口）不归平台版本管；版本不可变，回滚产生新版本号。

---

## 附录 B：与 `docs/configuration.md` 的分工

| 主题 | 本文 | `configuration.md` |
|---|---|---|
| YAML 语法、`{env:}` 展开、路径解析 | 只给结论 | **权威来源** |
| 每个参数的值、范围、风险与暴露级别 | **权威来源** | 不重复 |
| 校验命令与错误信息 | 不重复 | **权威来源** |
| 组件选型与生态候选 | **权威来源** | 无 |
| 平台 API 契约 | 见 spec 附录 A | 无 |

---

## 附录 C：计数与溯源

### C.1 人读版计数

| 章 | 条数 | 其中 `ops` |
|---|---|---|
| §2 VAD | 22 | 2（`smart_turn_model_path`、`vad_firered_model_dir`）|
| §3 STT（Qwen3-ASR 深挖）| 6 | 0 |
| §4 LLM | 28（27 个唯一名，`model_name` 有基类与覆写两行）| 1 |
| §5 TTS（Qwen3-TTS 深挖）| 23 | 3 |
| §6.1 监听与并发 | 5 | 4 |
| §6.2 超时与重试 | 6 | 1 |
| §6.3 音频与采样率 | 7 | 2 |
| §6.4 设备与说话人分离 | 11 | 1 |
| §6.5 鉴权与安全 | 10 | 10 |
| §6.6 日志与监控 | 8 | 4 |
| §6.7 环境变量 | 13 | 12 |
| §6.8 配置文件约束 | 6 | 4 |
| §6.9 容器化 | 9 | 8 |
| §6.10 客户端 | 16 | 3 |
| **§6 小计** | **91** | **49** |
| **合计** | **170** | **55** |

> §1 的组件清单（16 STT / 5 LLM / 15 TTS / 7 VAD 候选）是选型索引，不重复计入参数量；其专属字段见 §3.3 与 §5.3。

### C.2 人读版 ↔ 机器版映射

`parameter-catalog.yaml` 按 `stage` 分桶，本文按组件分章，映射关系固定如下：

| 本文章节 | yaml `stage` | 说明 |
|---|---|---|
| §2 | `vad` | 一一对应 |
| §3 | `stt` | 一一对应（本文只深挖当前后端，其余见 §3.3）|
| §4 | `llm` | 一一对应 |
| §5 | `tts` | 一一对应 |
| §6.1、§6.3、§6.6 | `server` / `runtime` | 进程级参数 |
| §6.2 | `runtime` + `stt` / `tts` | 超时字段按后端拆到对应 stage |
| §6.5、§6.7 | `env` | 环境变量统一入 `env` |
| §6.8、§6.9 | `deploy` | 构建与编排 |
| §6.10 | `client` | 客户端 |

> 本文与 yaml 出现计数差异属正常：人读版为了让每章自包含，允许同一字段在不同章节重复出现（如超时、采样率）；机器版按 `(stage, backend, name)` 唯一去重。**平台以 yaml 为唯一数据源。**

### C.3 本次修订校正的事实

| 旧写法 | 现状 | 影响 |
|---|---|---|
| STT 后端名 `openai_compatible` | 注册名为 `openai` | 旧清单无法直接落 YAML |
| TTS 后端名 `openai_compatible` | 注册名为 `openai` | 同上 |
| 可选后端含 `cosyvoice` | **未注册**，配置校验会拒 | 平台清单必须移除 |
| 可选后端含 `sensevoice` | 未注册；已注册的是 `sense-voice` | 两者字段前缀不同 |
| 缺 `phonon` / `whisper-mlx` / `parakeet-unified` / `openai-realtime` 等 | 均在注册表内 | 旧清单不完整 |
| `thresh` / `min_silence_ms` 仅「启动」 | 可被 `session.update` 覆盖 | 平台可做会话级灵敏度调节 |
| `voice` 完全不生效 | `qwen3` / `kitten` 真正生效 | 音色选择器可按后端启用 |
| VAD 参数只列项目字段 | 补充 Silero 官方 8k/16k、512/256 窗口、opset 15/16、`neg_threshold` 等约束 | 避免配出模型不支持的组合 |
| `/admin/sessions/update` 「未实现、返回 501」 | **已实现**，由 `S2S_ADMIN_TOKEN` 保护且 fail-closed（未配 → `503`） | 会话级热更新不需改源码，但必须先配 token |
| 错误码 `unsupported_field` / `unsupported_language` | 实际为 `invalid_request_error` / `invalid_session_type` / `session_gone` | 平台按真实错误码做分支 |

