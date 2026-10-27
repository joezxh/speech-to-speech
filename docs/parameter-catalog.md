# S2S 部署参数清单（按 VAD / STT / LLM / TTS 分组）

> 本文件是「S2S 部署参数配置平台」参数单一事实来源的**人读版**；机器可读镜像见
> [`parameter-catalog.yaml`](./parameter-catalog.yaml)，平台设计见
> [`superpowers/specs/2026-10-23-s2s-deployment-parameter-platform-design.md`](./superpowers/specs/2026-10-23-s2s-deployment-parameter-platform-design.md)。
> YAML 语法与校验语义以 [`configuration.md`](./configuration.md) 为准，本文不复制其内容。
> 按**实际环境与现象**组织的参数组合手册（GPU 档位、边缘盒、噪声环境、弱网等）见
> [`deployment-tuning-playbook.md`](./deployment-tuning-playbook.md)；单旋钮怎么改仍见 [`model-pipeline.md`](./model-pipeline.md) §6。

- 目录版本：`s2s-parameter-catalog-v1` / 人读版结构 `catalog-md-v2`
- 覆盖范围：`speech-to-speech-src` 启动参数通道 + 会话运行时通道 + 容器编排 + 客户端
- 取值基线：源码 `src/speech_to_speech/**` + 实际生效配置 [`config/prod.yaml`](../config/prod.yaml) + `silero-vad` 6.2.3 官方资料 + `fireredvad` 0.0.2 / `FireRedTeam/FireRedVAD` 官方资料
- 本次变化：**取消 A 层通用 / B 层后端的两段式结构**，改为 `VAD → STT → LLM → TTS → 平台公共` 的组件分组；暴露分级、来源优先级、生效方式、影响面、变更代价等元数据从「表 B」降级为参数行内的属性列；同时按注册表校正了后端名与控制台可选清单。
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

### 1.3 STT 可选项（`STT_BACKENDS`，15 个）

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

### 1.4 LLM 可选项（`LLM_BACKENDS`，4 个）

| 后端名 | 接口 | 能力标记 | 额外依赖 | 选型要点 |
|---|---|---|---|---|
| `chat-completions` | OpenAI Chat Completions | `supports_audio_input`、`supports_llm_proxy` | 内置 | **当前在用**；本仓 compose 用它打 GPUStack |
| `responses-api` | OpenAI Responses | `supports_llm_proxy` | 内置 | 官方 Responses 语义，无音频输入标记 |
| `transformers` | 本地 HF 权重 | — | 内置 | 可 8bit / 4bit 量化，显存可控 |
| `mlx-lm` | 本地 MLX | — | `mlx-lm` | macOS 默认；Linux 上会加载失败 |

可挂接的外部模型（通过 `model_name` 透传，名称须与网关注册名完全一致）：`Qwen3-8B`（当前）、`Qwen/Qwen3.5-4B`（本地默认）、`gpt-5.6-terra`（兼容后端默认，**不支持音频输入**）。

### 1.5 TTS 可选项（`TTS_BACKENDS`，12 个）

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

> §1 的组件清单（15 STT / 4 LLM / 12 TTS / 7 VAD 候选）是选型索引，不重复计入参数量；其专属字段见 §3.3 与 §5.3。

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

