# ASR + LLM + TTS 模型组合方案与硬件配置矩阵

> 整理时间：2026-11-10
> 范围：`speech-to-speech-src`（HF speech-to-speech 本体）+ 本仓库外层 Node 网关（`qwen-audio-agent`）的语音前台 Provider
> 数据来源优先级：**代码注册表 > `docs/hardware/*` 实测/采购文档 > `docs/models.md` 选型文档 > 外部经验值（已逐条标注）**

---

## 0. 开篇必读：三个需要先纠正的前提

| 编号 | 结论 | 证据 |
|---|---|---|
| C1 | **本仓库不存在 "Breeze TTS"**。全工作区（`d:\work\qwen-audio-agent`）对 `breeze` 的 grep 命中数为 **0**。若要接入，只有两条合规路径：① 自建 OpenAI 兼容 `/v1/audio/speech` 服务后用 `--tts openai`；② 用端到端 Realtime 前台（见 §5），代价是放弃 s2s 流水线的可插拔 STT/TTS。 | 全仓 grep |
| C2 | **MiniCPM 系列不在 s2s 流水线的后端注册表里**。`STT_BACKENDS`(15) / `LLM_BACKENDS`(4) / `TTS_BACKENDS`(12) 中均无 `minicpm`。**MiniCPM-o 4.5 只作为外层网关的端到端语音前台 Provider**（`ws://127.0.0.1:8006/v1/realtime?mode=audio`），Gateway 不安装模型、不管理推理进程，模型需用户自行按官方 Demo 部署。 | `backend_registry.py:351-707`；`shared/realtime-provider-definitions.mjs:153-164`；`docs/voice-frontends/minicpm-o.zh.md` |
| C3 | **CLI 参数名不是 `--stt_backend` / `--tts_backend`**：实际是 `--stt` / `--llm_backend` / `--tts`；唯一带 `_backend` 的是 TTS 内部的 `--qwen3_tts_backend`（`ggml｜torch`）。YAML 配置对应 `blocks.stt.backend` / `blocks.llm.backend` / `blocks.tts.backend`。 | `arguments_classes/module_arguments.py:62-85`；`config.py:401-411` |

> 另：`LLM_BACKENDS` 与 `TTS_BACKENDS` **没有 `none` 后端**（只有 `STT_BACKENDS` 有），因此**无法起纯 ASR 进程**，ASR/TTS 独立接口只能做成同一进程多端点（与生产一致，零额外显存）。见 `docs/local-thirdparty-deployment-CN.md:44-48`。

---

## 1. 组件显存基线（所有组合方案的算量底座）

单路管线（`num_pipelines=1`）的固定开销，`docs/hardware/performance-assumptions.md` §3.1 + `docs/hardware/README.md`：

| 组件 | 模型 / 后端 | 权重规模 | 显存（FP16） | 设备 | 备注 |
|---|---|---|---|---|---|
| VAD | Silero VAD v5（ONNX/JIT） | ~260K 参数 | ~0.03 GB（~30 MB） | **CPU** | 仓库内置权重，免联网；`--vad silero`（默认）/ `--vad firered`（需额外权重） |
| STT | Qwen3-ASR-1.7B-hf（`qwen3-asr`） | 1.7B | ~1.8 GB（INT8 0.6–1.0 GB） | GPU | 代码注释另标 "1.7B 约需 4 GB VRAM"，与实测口径不一致，**以 4.6 GB/路管线实测为准**；默认模型是 `Qwen/Qwen3-ASR-0.6B-hf` |
| TTS | Qwen3-TTS-12Hz-1.7B-CustomVoice（`qwen3`） | 1.7B | ~3.4 GB（INT8 ~2.0 GB） | GPU | torch/CUDA 后端，句内流式 `streaming_chunk_size=4` |
| **管线合计** | — | — | **实测 ≈4.6 GB（4633 MiB）**；理论算术和 ~5.2 GB | GPU | 2026-10-22 实测；单路并发上限公式 `floor(可用显存GB × 0.85 ÷ 4.6)` |

**关键含义**：STT+TTS 恒占 ~5.2 GB，**是管线的不可压缩底座**——换更小的 LLM 也压不到 5 GB 以下，这是"边缘盒至少要 8 GB 内存"的根本原因（`docs/hardware/plan-6-qwen3.5-0.8b.md`）。

**本机实测锚点（RTX 5070 Ti 12GB Laptop）**：总显存 12227 MiB；S2S 单独 4633 MiB；S2S + 本地 Qwen3.5-4B Q4 同卡 11878 MiB（**仅余 ~67 MiB**）。

---

## 2. LLM 侧：自部署 vs 第三方

### 2.1 自部署（本地推理）

| 形态 | 后端 / 接入方式 | 模型标识 | 显存占用 | 解码速度 | 适用场景 |
|---|---|---|---|---|---|
| 进程内（内置） | `--llm_backend transformers` | 默认 `Qwen/Qwen3.5-4B`；支持任意 HF CausalLM/VLM | FP16 ~8 GB / 8bit ~4 GB / 4bit(NF4) ~2.1 GB | 4B Q4 约 120–150 tok/s | 单机一体机、离线部署、显存紧但要能调工具 |
| 进程内（Apple Silicon） | `--llm_backend mlx-lm` | 默认 `mlx-community/Qwen3.5-4B-4bit` | 走统一内存 | — | Mac 本地；Linux 上会因缺 MLX 加载失败 |
| 外部服务 | llama.cpp `llama-server` + `--llm_backend chat-completions`（`--responses_api_base_url http://127.0.0.1:8080/v1`） | `Qwen/Qwen3-8B-Instruct-GGUF` / `unsloth/Qwen3.5-{4B,2B,0.8B}-GGUF` | Qwen3-8B：Q4 ~5.0 GB / Q8 ~8.5 GB；Qwen3.5-9B：Q4 ~5.7 / Q8 ~9.8 / FP16 ~18 GB；4B：2.6 / 4.5 / 8；2B：1.3 / 2.2 / 4.0；0.8B：0.6 / 0.9 / 1.6 GB（+KV 8K q8：0.2–0.7 GB） | 8B Q4 ~70–90 tok/s；9B Q4 ~55–70；4B ~120–150；2B ~150–250；0.8B ~300–500（5070/4090 级） | **生产主形态**：LLM 盒与管线盒解耦，横向扩容 |
| 外部服务 | vLLM OpenAI 兼容服务器 + 同上后端 | 任意 | 由 vLLM 决定 | 高 | 已有 vLLM 集群、需批处理/高吞吐 |
| 外部服务 | Ollama | — | — | — | **不推荐**：依赖独立 mmproj 权重，`plan-5` 明确排除 |

> KV cache 口径：上表为 `-c 8192`、q8_0 量化；`-c 32768` 时 KV 约为 4 倍（2B ≈1.2 GB、0.8B ≈0.8 GB）。

### 2.2 第三方 / 远程部署（本地零推理显存）

统一通过 `--llm_backend chat-completions` 或 `responses-api` + `--responses_api_base_url` / `--responses_api_api_key` 接入任何 OpenAI 兼容端点。

| 服务 | Base URL | 代表模型 | 本地显存 | 网络/延迟代价 | 备注 |
|---|---|---|---|---|---|
| GPUStack（内网） | `http://192.168.40.30/v1-openai` | Qwen3-8B | **0** | RTT 10–80 ms；排队 0–300 ms；TTFT 100–400 ms | 本仓生产基线（`docs/model-pipeline.md:46`） |
| 百炼 DashScope | `https://dashscope.aliyuncs.com/compatible-mode/v1` | qwen-plus / qwen3-omni 等 | **0** | 公网 RTT + 平台排队 | 本地 thirdparty 部署已实测跑通（`docs/local-thirdparty-deployment-CN.md`）；需 `enable_thinking=false` |
| OpenAI 兼容第三方（DeepSeek / 硅基流动 / OpenRouter / HF Inference Providers 等） | 各自 `/v1` | 各自 | **0** | 视服务而定 | 同一组 `--responses_api_*` 标志 |
| OpenAI / Gemini / 豆包 / StepFun Realtime | 见 §5 | 端到端语音模型 | **0**（但本地无 STT/TTS 可控性） | 由云端承担全链路 | 走网关 Provider，不进 s2s 流水线 |

### 2.3 LLM 选型对比（自部署量化档）

| 模型 | Q4 权重 | Q8 权重 | FP16 | KV(8K) | 同机管线小计(Q4) | 建议卡 | 12 GB 卡同机路数 | 24 GB 卡同机路数 | 质量定位 |
|---|---|---|---|---|---|---|---|---|---|
| Qwen3-8B | ~5.0 GB | ~8.5 GB | ~16 GB | ~0.6 GB | ~11 GB | 16 GB(Q4 紧)/24 GB(Q8) | 1（实测会超） | 3 | 中文/工具调用均衡，中文客服主力 |
| Qwen3.5-9B | ~5.7 GB | ~9.8 GB | ~18 GB | ~0.7 GB | ~11.6 GB | 24 GB(Q4)/32 GB+(FP16) | **0（装不下）** | 3 | 质量最高，最吃显存 |
| Qwen3.5-4B | ~2.6 GB | ~4.5 GB | ~8 GB | ~0.4 GB | ~8.2 GB | 12 GB(Q4 够)/16 GB(Q8) | 1 | 3 | 并发与延迟最佳平衡（本仓已跑通 `docker-compose.llm-bundled.yml`） |
| Qwen3.5-2B | ~1.3 GB | ~2.2 GB | ~4.0 GB | ~0.3 GB | ~6.8 GB | 8 GB 紧/12 GB 稳 | 1 | 3 | 最低成本可用档，工具调用弱 |
| Qwen3.5-0.8B | ~0.6 GB | ~0.9 GB | ~1.6 GB | ~0.2 GB | ~6.0 GB | 8 GB 可跑/12 GB 舒适 | 1 | **4** | 兜底/边缘/单轮；多轮指代与工具调用不可用 |

> 路数计算式：`可用 = 标称显存 − LLM 权重 − KV(8K) − 0.8 GB 余量`；`路数 = floor(可用 × 0.85 ÷ 4.6)`。数值全部来自 `docs/hardware/plan-2..6` 与 `performance-assumptions.md` §3.2。
> **结论**：换更小 LLM 换延迟已到尽头（0.8B 比 2B 的 TTFA 仅快 10–20 ms）；换小模型只在 **8–24 GB 显存区间**换得到路数。

---

## 3. TTS 后端横向对比（12 个，代码为准）

| 后端（`--tts`） | 模型标识 | 权重规模 | 设备 | 显存 | 流式 | 许可 | 适用场景 |
|---|---|---|---|---|---|---|---|
| `qwen3`（默认） | `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` / `-VoiceDesign` / `-Base`；Apple Silicon 自动映射 `mlx-community/...-CustomVoice-6bit` | 1.7B | CUDA / MPS | ~3.4 GB (FP16) | ✅ 句内流式（chunk 4） | 受限 | **中文实时首选**：支持预设音色、3s 克隆、语音设计；本项目生产在用（RTF 0.41–0.69） |
| `openai` | 客户端默认 `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`；示例 `gpt-4o-mini-tts` | 服务端决定 | 服务端 | 本地 0 | ✅（`--openai_tts_stream`，vLLM-Omni 扩展） | 服务端 | 接远端 TTS（CosyVoice2 / Breeze-TTS 自建服务均走此路）；local 客户端默认加 196 ms 播放缓冲 |
| `kokoro` | `hexgrad/Kokoro-82M` / `mlx-community/Kokoro-82M-bf16` | 82M | auto，**CPU 可跑** | <0.5 GB | ✅ | Apache-2.0 | 极轻量英文/多语 TTS，可与 STT 同机挤在 CPU |
| `kitten` | `KittenML/kitten-tts-mini-0.8` | 80M | **仅 CPU**（ONNX） | <0.5 GB | ❌（整段合成后分块） | — | 英文 CPU 兜底 |
| `pocket` | kyutai Pocket TTS；波斯语 `mehdi-hf/pocket-tts-farsi-v2` | 小 | 默认 **CPU**，可 cuda/npu/xpu/mps | ~1 GB 级 | ✅（每句 max_tokens=50） | 开源 | 低算力本地、多音色预设（alba/marius/javert…） |
| `phonon` | `gradium/phonon-31m-en`（Apache-2.0）；`phonon-40m-en` 为 gated + CC BY-NC | 31M / 40M | **仅 CPU**（`ptts==0.4.0`） | <0.5 GB | ✅ 原生流式 | Apache-2.0 / NC | 英语流式 CPU TTS；`--phonon_tts_quant q8` 默认 |
| `chatTTS` | ChatTTS（会话式韵律） | 中 | auto（CUDA/NPU→CPU） | ~1–2 GB | ✅（`--chat_tts_chunk_size 512`） | AGPL | 韵律/口语化对话风格 |
| `facebookMMS` | `facebook/mms-tts-{eng,fra,spa,...}` | 小 | 默认 cuda | ~1 GB 级 | ✅ | CC-BY-NC | 多语种覆盖，按语言码切音色（切语言即重载） |
| `omnivoice` | `k2-fsa/OmniVoice` | 中 | cuda/mps/xpu/cpu | ~1–2 GB | ❌ **阻塞式**（首音=整句耗时） | 代码 Apache-2.0 / **权重 CC-BY-NC** | 语音克隆；上游 RTF 可低至 0.025，但**商用受限** |
| `supertonic` | Supertonic ONNX（自动下载到 `~/.cache/supertonic3/`） | 小 | CPU 为主 | <1 GB | ✅（44.1 kHz→16 kHz） | — | CPU 侧多音色（M1–M5 / F1–F5） |
| `drama3` | `fishaudio/drama-3`（SGLang Omni） | 服务端 | **远端 GPU** | 本地 0 | ✅ | 服务端 | 接自建 SGLang Omni 集群（默认 `http://localhost:8000/v1`，需 `DRAMA3_API_KEY`） |
| `minimax` | `speech-2.8-hd`（默认）/ `speech-2.8-turbo` | 服务端 | 托管服务 | 本地 0 | ✅ | 服务端 | 商用级音质；**必须** `MINIMAX_API_KEY`；`https://api.minimax.io`（大陆 `api.minimaxi.com`） |

**Qwen3-TTS 三态说明**（`TTS/qwen3_tts_handler.py:204-296`）：
- `--qwen3_tts_backend ggml`（默认）：qwentts.cpp GGML，量化 `BF16|Q8_0|Q4_K_M|F32`；**GGML 后端自选设备**，历史实测 CPU 兜底时 RTF 可达 3.7（不可用于生产）。
- `--qwen3_tts_backend torch`：CUDA-graphs 流式，`--qwen3_tts_device cuda`；需 transformers 5.x 兼容补丁（MimiConfig 无 `rope_theta`）。
- macOS 自动切 `mlx-audio`（`--qwen3_tts_backend` 被忽略），默认 6bit。
- `--qwen3_tts_non_streaming_mode` 默认 `true`（先预填全文再解码，**首音更慢**）；生产改 `false` 做句内流式。

---

## 4. STT 后端横向对比（15 个，摘要）

| 后端（`--stt`） | 默认模型 | 设备 | 流式 | 备注 |
|---|---|---|---|---|
| `none` | — | — | ✅ | 唯一 `none`；音频直通给支持音频输入的 LLM |
| `qwen3-asr` | `Qwen/Qwen3-ASR-0.6B-hf`（`1.7B-hf` 更准，代码标 ~4 GB VRAM） | auto（CUDA/NPU/XPU/MPS/CPU） | ❌（VAD 终段整段） | 30 语种；中文主力；本项目生产在用 |
| `parakeet-tdt`（CLI 默认） | `nvidia/parakeet-tdt-0.6b-v3` | GPU/CPU/MPS | ✅ | 英文/通用强；曾实测 RTF 0.57 |
| `parakeet-unified` | `nvidia/parakeet-unified-en-0.6b` | auto | ✅ | 多语统一模型 |
| `nemotron-streaming` | `nvidia/nemotron-speech-streaming-en-0.6b` / `nemotron-3.5-asr-streaming-0.6b` | auto | ✅ | 逐句检测、多语 |
| `orukeet` | 仓库 `oruk/orukeet` + `orukeet-v0.1.0.nemo` | auto | ✅ | 固定 revision，需 `nemo` extra |
| `paraformer` | `paraformer-zh`（ModelScope/FunASR） | 默认 cuda | ✅ | 中文+标点最强，需 `paraformer` extra |
| `sense-voice` | `FunAudioLLM/SenseVoiceSmall` | 默认 cuda | ✅ | 中文+情绪标签，需 `sensevoice` extra |
| `whisper` | `distil-whisper/distil-large-v3` | cuda/auto/… | ✅（附加 speculative turns） | 生态最广 |
| `whisper-mlx` / `mlx-audio-whisper` | `mlx-community/whisper-large-v3-turbo` | 仅 Apple Silicon | ✅ | Mac 专用 |
| `faster-whisper` | `tiny.en`（可选到 large-v3 / distil-*） | auto，**CPU 可跑** | ✅ | `compute_type=int8` 可省内存 |
| `openai` | 客户端默认 `nvidia/parakeet-tdt-0.6b-v3`；可用 `Qwen/Qwen3-ASR-1.7B`(vLLM) / `gpt-transcribe` | 服务端 | ✅ | OpenAI 兼容 `POST /v1/audio/transcriptions` |
| `openai-realtime` | `gpt-live-transcribe` | 服务端 | ✅ | 远程 WS `wss://api.openai.com/v1` |
| `vllm-realtime` | `Qwen/Qwen3-ASR-1.7B` / `mistralai/Voxtral-Mini-4B-Realtime-2602` | 服务端 | ✅ | 远程 WS `ws://localhost:8000/v1` |

> 未注册但代码存在（写进 YAML 会被校验拒绝）：`sensevoice`（无连字符）、`cosyvoice`。CosyVoice 的官方替代路径是"用 `openai` 后端接远端 CosyVoice2 服务"（`docs/parameter-catalog.md:200`）。

---

## 5. 端到端语音模型（不经 s2s 流水线，走网关 Realtime Provider）

这些方案**没有本地 STT/TTS/LLM 可分拆**，GPU/显存全部在云端或你自己部署的模型进程上，Gateway 只做协议适配（16-bit PCM ↔ 16 kHz float32）。

| Provider（网关键） | 模型 | 端点 | 本地资源需求 | 能力边界 | 适用场景 |
|---|---|---|---|---|---|
| `dashscope`（默认） | `qwen-audio-3.0-realtime-plus` / `-flash`；`qwen3.8-omni-flash-realtime` / `qwen3.5-omni-flash|plus-realtime` | `wss://dashscope.aliyuncs.com/api-ws/v1/realtime` | **0 显存**；仅网络与 API Key | audio family：文本/音频输入 + 音频输出 + function calling；omni family 额外支持图像/视频 | 阿里云生态、需要工具调用与视觉 |
| `minicpm-o`（面壁智能） | **MiniCPM-o 4.5** | `ws://127.0.0.1:8006/v1/realtime?mode=audio`（可切 `?mode=video` 走视觉全双工） | 本地 GPU 需求**由用户自建 MiniCPM-o-Demo 服务决定**，Gateway 不装模型；仓库内无显存数字 → **待实测/待查官方部署文档** | **受限**：无对话项、无结构化 Function Call、无客户端触发回复、无输入转写事件 → 文字输入/历史恢复/主动播报/记忆写入/后台工具在此 Provider 下不可用 | 本地/私有化端到端语音、离线优先场景（功能面窄） |
| `stepfun` | `stepaudio-3-realtime-preview` | `wss://api.stepfun.com/v1/realtime` | 0 | 文本/音频 I/O + function calling | 国产托管端到端替代 |
| `doubao-seeduplex` | 豆包实时语音 3.0（`1.2.6.1`） | `wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue` | 0 | 全双工，legacy 能力集 | 火山引擎生态 |
| `gpt-live` | `gpt-realtime-2.1` | `wss://api.openai.com/v1/realtime` | 0 | legacy 能力集 | OpenAI 生态 |
| `google-live` | `gemini-3.8-live` | Google BidiGenerateContent WS | 0 | **omni 能力集**（含图像/视频输入） | 多模态实时对话 |
| `pipecat` | 本地 pipecat 服务 | `ws://127.0.0.1:8766/v1/realtime` | 由 pipecat 部署决定 | OpenAI Realtime 兼容 | 自建编排层 |
| `speech-to-speech` | 本仓库 s2s 流水线 | `ws://127.0.0.1:8765/v1/realtime` | 见 §1–§4 | 本仓全链路可控（STT/TTS/LLM 全部可插拔） | 需要本地可控、可定制、离线 |

---

## 6. 组合方案矩阵（核心交付）

### 6.1 A 类：本地 STT/TTS（s2s 流水线）+ LLM 部署形态

| # | 组合 | STT | TTS | LLM | 本地显存需求 | 系统内存(RAM) | 磁盘 | 端到端 TTFA | 单卡并发 | 适用场景 |
|---|---|---|---|---|---|---|---|---|---|---|
| **A1** | 本地 STT/TTS + **第三方 LLM**（生产基线） | Qwen3-ASR-1.7B | Qwen3-TTS-1.7B (torch/cuda) | GPUStack Qwen3-8B / 百炼 qwen-plus | **4.6 GB**（实测/路） | 建议 16 GB | 模型 8.6 GB + 镜像 | ≈1.0–1.5 s（700 ms 判停 + STT 150–300 + 远程 TTFT 100–400 + TTS 100–200） | 12 GB→2，16 GB→2，24 GB→4，48 GB→8 | **当前部署形态**：数据不落本地模型、数据出域可控、上线最快；瓶颈转移到远程配额与排队 |
| **A2** | 全本地一体机（4B） | Qwen3-ASR-1.7B | Qwen3-TTS-1.7B | 本地 llama.cpp Qwen3.5-4B Q4 | **8.2 GB**（同机小计） | 建议 32 GB | 模型 11.3 GB + 镜像 | ≈0.9–1.3 s | 12 GB→1，16 GB→2，24 GB→3，32 GB→5 | **离线/内网闭环**、断网可用、单盒高性价比（本仓已跑通） |
| **A3** | 全本地一体机（8B，质量档） | 同上 | 同上 | Qwen3-8B Q4 / Q8 | 11 GB(Q4) / 14.3 GB(Q8) | 建议 32 GB | +8B GGUF ~5.5 GB | ≈1.0–1.5 s | 16 GB→1，24 GB→3，32 GB→4 | 中文客服/调解主力，工具调用优先 |
| **A4** | 全本地一体机（9B，质量最高档） | 同上 | 同上 | Qwen3.5-9B Q4 / Q8 / FP16 | 11.6 / 15.7 / 23.9 GB | 建议 32–64 GB | +9B GGUF ~6 GB | ≈1.1–1.6 s | 16 GB→1，24 GB→3，48 GB→7 | 复杂纠纷研判、长指令理解；**12 GB 卡装不下** |
| **A5** | 全本地轻量档 | 同上 | 同上 | Qwen3.5-2B Q4 | ≈6.8 GB | 建议 16 GB | +2.7 GB | ≈1.03–1.38 s | 12 GB→1，16 GB→2 | 边缘/低功耗、固定话术；工具调用弱 |
| **A6** | 全本地兜底档 | 同上 | 同上 | Qwen3.5-0.8B Q4 | ≈6.0 GB | 建议 16 GB | +0.7 GB | ≈1.02–1.36 s | 12 GB→1，**24 GB→4** | 单轮事实问答、固定导览；多轮指代/工具调用不可用 |
| **A7** | 轻量 TTS 替换（降显存） | Qwen3-ASR-1.7B | **Kokoro-82M / Pocket / Phonon(CPU)** | Qwen3.5-4B Q4 | ≈7.4 GB（STT 1.8 + TTS <0.5 + LLM 2.6 + KV 0.4 + 余量） | 建议 16–32 GB | 减少 ~3 GB | TTS 首包更快（CPU 合成 <100 ms 级） | 12 GB→1，24 GB→4+ | 显存极限 12 GB、英文为主；代价是中文自然度/克隆能力下降 |
| **A8** | 多盒解耦（LLM 盒 + N 管线盒） | 同上 | 同上 | LLM 盒：Qwen3.5-4B/8B 或 9B | LLM 盒 8.2–11.6 GB；**管线盒 4.6 GB/路** | LLM 盒 32 GB；管线盒 16 GB | 同上 | LLM 盒加 RTT 10–80 ms | 管线盒 12 GB→2、16 GB→2、24 GB→4 | 高并发（8–20 路）、LLM 盒永不成为瓶颈、横向扩容 |

> **TTFA 口径红线**：真实 TTFA = `Latency after speech end + min_silence_ms/1000`。`min_silence_ms=700` 时日志显示 0.45 s 实际 ≈1.15 s，只报日志值视为无效证据（`docs/hardware/acceptance-test-plan.md`）。
> **验收线**：STT/TTS RTF 均 < 1.0；TTFA P95 ≤1.0 s 舒适 / ≤2.0 s 可用 / >2.0 s 退货；显存实测峰值 ≤ 承诺值 1.15 倍。

### 6.2 B 类：端到端语音模型（本地零推理资源）

| # | 组合 | 模型 | 本地 GPU 显存 | RAM | 网络要求 | 适用场景 |
|---|---|---|---|---|---|---|
| **B1** | 百炼 Qwen Realtime | `qwen-audio-3.0-realtime-plus` / `qwen3.5-omni-flash-realtime` | **0** | 1–2 GB（网关进程） | 公网 + API Key | 快速上线、阿里云生态、需要 function calling / 视觉 |
| **B2** | 本地 MiniCPM-o 4.5 | MiniCPM-o 4.5 | **待定**：由自建 MiniCPM-o-Demo 服务决定，仓库无数据 | 自建服务决定 | 本机回环（或 TLS） | 私有化端到端、离线优先；**功能面窄**（无 FC/无转写/无主动播报） |
| **B3** | 豆包 Seeduplex 3.0 | `1.2.6.1` | 0 | 1–2 GB | 公网 + API Key | 火山引擎生态、全双工 |
| **B4** | StepAudio 3 | `stepaudio-3-realtime-preview` | 0 | 1–2 GB | 公网 + API Key | 国产托管替代 |
| **B5** | Gemini 3.8 Live | `gemini-3.8-live` | 0 | 1–2 GB | 公网 + API Key | 多模态（含图像/视频输入）实时对话 |
| **B6** | GPT Realtime 2.1 | `gpt-realtime-2.1` | 0 | 1–2 GB | 公网 + API Key | OpenAI 生态 |

---

## 7. 按硬件档位的落地推荐

| 硬件 | 推荐组合 | 显存占用 | 路数 | RAM | 备注 |
|---|---|---|---|---|---|
| 8 GB（边缘起步） | A5（2B Q4）或 A6（0.8B Q4） | 6.0–6.8 GB | 1 | 16 GB | 24 GB 卡上 0.8B 比 2B 多 1 路，8–24 GB 区间才值得换小模型 |
| 12 GB（RTX 3060/4060Ti/5070） | A2（4B Q4） | 8.2 GB | 1 | 16 GB | 本机 5070 Ti 实测仅余 67 MiB；余量吃紧，**推荐远程 LLM(A1) 换 2 路** |
| 16 GB（4060Ti 16G / 5070 Ti 16G） | A3（8B Q4） | 11 GB | 1 | 32 GB | Q8 与多路二选一；A2 可上 2 路 |
| 24 GB（RTX 4090 / 5880 Ada） | A4（9B Q4/Q8） | 11.6–15.7 GB | 3 | 32–64 GB | 质量最高档主力卡；A2/A3 同为 3 路 |
| 48 GB（L20 / RTX 5880 Ada 48G） | A4（9B FP16）+ 多路 | 23.9 GB | 7 | 64 GB | 需服务器/机柜（被动散热）；L20 需 ECC + 服务器，整机预算 +0.8–1.5 万元 |
| 无 GPU（CPU-only） | STT `faster-whisper`(int8) + TTS `phonon`/`kitten`/`kokoro` + LLM 走远程 | ~0 | 1（受 CPU 限制） | 16–32 GB | LLM 必须远程；CPU 上 0.8B 仅 20–40 tok/s、2B 15–30 tok/s |
| 边缘盒（Orin NX 16G / AGX Orin 64G） | A1（远程 LLM）+ 本地 1.7B STT/TTS | 16 GB 共享内存 → 可用约 12 GB | 2（Orin NX）/ 9–11（AGX） | 共享内存 | **无一款达到"已证实"**：缺 1.7B+FP16+transformers 实测；RTF 极可能 >1 |

---

## 8. 边缘与特殊形态补充

| 形态 | 关键约束 | 结论 |
|---|---|---|
| CPU-only x86（Ultra 9 285H） | G1 通过（x86_64 可直跑原样权重） | 文档判定"待验证但**不推荐**"：CPU 跑 1.7B 双模型 RTF 大概率 >1 |
| RK3588 / 昇腾 310 / RDK X5 | 需转 RKNN/RKLLM/OM/.hbm → 违反"不改 `src/`"原则 | **不合格**（G1 不通过）；TTS 无 RK 适配 |
| AMD Ryzen AI Max+ 395（128 GB 统一内存） | 同款 Qwen3-TTS-12Hz-1.7B 在 PyTorch+ROCm 7.2 下 **RTF 2.25–3.00**（首轮 4.20 为冷启动） | **高风险**：TTS 慢于实时，舒适档不成立 |
| Orin NX 16G | 102 GB/s 带宽，AGX Orin 64G 为 204.8 GB/s | 待验证；带宽约为桌面 GDDR7 的 1/5～1/10 |
| DGX Spark 128 GB | 273 GB/s，槽位上限 20–22 路 | 带宽是真正瓶颈，**槽位 ≠ 可交付路数** |
| 边缘盒定性 | 算力密度低于二手 RTX 3060 12G | **边缘盒是省电/省空间方案，不是省钱方案** |

---

## 9. 部署形态与端点速查

| 形态 | 命令要点 | 端点 | 备注 |
|---|---|---|---|
| 全本地一体机 | `--stt qwen3-asr --llm_backend chat-completions --responses_api_base_url http://127.0.0.1:8080/v1 --tts qwen3 --qwen3_tts_backend torch` | `ws://127.0.0.1:8765/v1/realtime` | llama.cpp 另起容器/进程 |
| 本地 STT/TTS + 远程 LLM | `--llm_backend chat-completions --responses_api_base_url https://dashscope.aliyuncs.com/compatible-mode/v1 --model_name qwen-plus` | 同上 | 百炼需 `enable_thinking=false` |
| 同进程多端点 REST | 构建期注入 `scripts/patch_pipeline_rest.py`（`Dockerfile.local.rest` / `Dockerfile.ttsfix`） | `POST /v1/audio/transcriptions`（ASR）、`POST /v1/audio/speech`（TTS，仅 wav），同在 8765 | 复用已加载模型，**额外调用不增加显存** |
| macOS 最优 | `--mac-optimal-settings`（Parakeet TDT + MLX LM + Qwen3-TTS + MPS） | 同上 | 统一内存 |
| 离线运行 | 先在线缓存权重一次，再 `HF_HUB_OFFLINE=1` | — | 权重缓存：`cache/qwen3-asr-model-hf`（**必须 `-hf` 版**）、`cache/qwen3-tts-model`、`~/.cache/faster-qwen3-tts/qwentts_refs`、Silero 权重目录（`SILERO_VAD_REPO_PATH` → `/opt/silero-vad`） |

**客户端坑（生产必读）**：客户端**不要**再发 `input_audio_buffer.commit`——服务端 VAD 会自动提交，双提交会产生 `conversation_already_has_active_response`（良性）。服务端无 `/health` 端点（404），健康检查用 WS 升级握手（101）或 `/v1/pool`、`/v1/usage`。

---

## 10. 待验证 / 缺口清单（不要当成已确认数据）

1. **RAM 与磁盘下限**：`docs/hardware/procurement-list.md` 对所有桌面卡条目只写"自配/需服务器/需整机"，**未给出 RAM/CPU/SSD 下限**。本文件表格中的 RAM 为工程建议值，需实测确认。
2. **LLM 权重与 KV 为推导值**（Q4≈0.55 GB/B、Q8≈1.1 GB/B、FP16≈2.0 GB/B），待 T4/T6 实测替换，验收容差 ±20%。
3. **除 D-E09（Ryzen AI Max+ 395）外，所有边缘盒的 STT/TTS RTF 均无实测**，Orin NX 的 "RTF 可能 >1" 属推测。
4. **MiniCPM-o 4.5 的本地显存/内存需求在仓库内无任何记录**，需查官方 `MiniCPM-o-Demo` 部署说明并实测。
5. **Breeze TTS 完全无实现**，接入需自建 OpenAI 兼容 `/v1/audio/speech` 服务（可复用本仓 `scripts/patch_pipeline_rest.py` 的注入思路）。
6. 所有 tok/s 与 TTFA 均为**预算/推导值**，仓内无任一档的端到端 TTFA 实测记录。
