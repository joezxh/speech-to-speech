# 模型链路与配置（本地部署）

本文整理 `docker-compose.local.yml` 下的语音对话（speech-to-speech）模型链路、各模型的
能力与调用参数、提示词结构，并给出**最常见调整场景对应的 compose 参数片段**。

> 权威配置来源：`docker-compose.local.yml`（本地 GPU + docker，复用已构建镜像
> `speech-to-speech-pipeline:latest`，不在此 build）。
> 启动命令：
> ```bash
> docker compose -f docker-compose.local.yml --env-file .env.local up -d
> ```
> 所有模型参数以 `pipeline` 服务 `command:` 下的命令行标志传入；模型权重 bind 到
> `./cache → /root/.cache`，Silero VAD 挂载到 `./silero-vad → /opt/silero-vad`。

---

## 1. 模型链路总览

音频数据流是一条串行流水线，由 `src/speech_to_speech/s2s_pipeline.py:_build_handlers`
装配（`VAD → STT → LM → TTS`）：

```
麦克风音频
  → [VAD]  Silero VAD                 （句末静音判停，Smart Turn 关闭）
  → [STT]  Qwen3-ASR-1.7B             （本地 /root/.cache/qwen3-asr-model-hf，自动语种）
  → [LLM]  Qwen3-8B @ GPUStack        （远程 OpenAI 兼容 chat-completions，流式）
  → [TTS]  Qwen3-TTS-CustomVoice      （本地 /root/.cache/qwen3-tts-model，torch/cuda，句内流式）
  → 扬声器音频
```

对外通过 **OpenAI-Realtime 协议**暴露：`ws://127.0.0.1:8765/v1/realtime`（默认端口
`8765`）。后端网关（`qwen-audio-agent`）连接该端点，浏览器/前端经网关接入。

单实例部署：`num_pipelines=1`，一个 uvicorn 监听端口，把每个新连接路由到一个空闲
pipeline；连接数超过 `num_pipelines` 会被拒绝（这也是此前 “all 1 pipeline slots in
use” 的根因）。

---

## 2. 当前部署参数速查（来自 docker-compose.local.yml）

| 阶段 | 后端 / 模型 | 关键参数 |
|---|---|---|
| VAD | `silero` | `min_silence_ms=700`、`--no_smart_turn`、`speculative_reopen_ms=0`、`unanswered_reopen_ms=0`、`smart_turn_model_path=/root/.cache/smart-turn-v3.2-cpu.onnx` |
| STT | `qwen3-asr` | `qwen3_asr_model_name=/root/.cache/qwen3-asr-model-hf`、`qwen3_asr_device=auto`、`qwen3_asr_language=auto` |
| LLM | `chat-completions` | `model_name=Qwen3-8B`、`responses_api_base_url=http://192.168.40.30/v1-openai`、`responses_api_api_key=not-needed`、`responses_api_stream`、`responses_api_reasoning_effort=""`、`stream_batch_sentences=1` |
| TTS | `qwen3` | `qwen3_tts_model_name=/root/.cache/qwen3-tts-model`、`qwen3_tts_backend=torch`、`qwen3_tts_device=cuda`、`qwen3_tts_non_streaming_mode=False`、`qwen3_tts_streaming_chunk_size=4` |
| 全局 | — | `--no_enable_live_transcription`（关实时字幕）、`init_chat_role=system`、`init_chat_prompt="You are a helpful voice assistant..."` |

---

## 3. 各模型详情

### 3.1 VAD — Silero（`arguments_classes/vad_arguments.py`）

- **当前配置**：`min_silence_ms=700`（句末静音判停）、`--no_smart_turn`（纯静音判停，
  关闭 Smart Turn）、`speculative_reopen_ms=0`、`unanswered_reopen_ms=0`、`sample_rate=16000`。
- **可调参数**：`vad`（`silero`/`firered`）、`thresh`（0.6）、`min_speech_ms`（384）、
  `min_speech_continuation_ms`（192）、`max_speech_ms`（∞）、`speech_pad_ms`（500）、
  `audio_enhancement`、`enable_realtime_transcription`（关）、`realtime_processing_pause`（0.5s）、
  `short_segment_merge_ms`（0）。
- **Smart Turn 相关**（当前禁用，模型已挂载）：`smart_turn`、`smart_turn_model_path`、
  `smart_turn_threshold`（0.5）、`smart_turn_max_wait_ms`（2000）、
  `smart_turn_incomplete_delay_ms`（600）、`smart_turn_cpu_count`（1）。
- **能力**：基于 Silero 的语音活动检测做端点切分；Smart Turn v3.2（ONNX，CPU）可在
  Silero 终段后进一步判断“用户是否真的说完”，从而降低误打断 / 漏接。

### 3.2 STT — Qwen3-ASR（`STT/qwen3_asr_handler.py` + `qwen3_asr_stt_arguments.py`）

- **当前配置**：本地 `/root/.cache/qwen3-asr-model-hf`（注释为 1.7B 变体，约 4GB 显存）、
  `device=auto`（容器有 GPU → CUDA）、`language=auto`（每句自动识别并下传给 LLM/TTS）。
- **可调参数**：`qwen3_asr_model_name`、`qwen3_asr_device`、`qwen3_asr_torch_dtype`
  （auto/float16/bfloat16/float32）、`qwen3_asr_language`、`qwen3_asr_prompt`
  （热词/上下文偏置，如 `"Vocabulary: Quilter, apostle."`）、`qwen3_asr_gen_max_new_tokens`（256）。
- **能力**：`SUPPORTED_LANGUAGES = list(LANGUAGE_CODE_TO_NAME)`（Qwen3-ASR 处理器全量
  语言表，覆盖中/英/日/韩/法/德/西/俄/葡/意/阿等主流语言），自动语种识别；不支持指定
  热词时（transformers 版本过低）自动跳过并告警。

### 3.3 LLM — Qwen3-8B via GPUStack（`LLM/chat_completions_language_model.py`）

- **当前配置**：`model_name=Qwen3-8B`、`base_url=http://192.168.40.30/v1-openai`、
  `api_key=not-needed`、`stream`（流式）、`responses_api_reasoning_effort=""`（实际等效关闭
  推理/思考，走 `enable_thinking=false`）、`stream_batch_sentences=1`（逐句流式，尽快触发 TTS）。
- **调用参数（代码内）**：流式 `stream=True`；音频输入路径 `audio_max_tokens=256` /
  `audio_temperature=0.0`；`extra_body` 携带 `reasoning_effort`；
  `stream_options.include_usage=True`（用量统计）。
- **上下文**：`chat_size`（默认保留约 30 轮 user/assistant）、`compact_history=True`
  （超长后后台摘要，见 §4）、`enable_lang_prompt=False`（默认不在每轮追加语种指令）。
- **能力**：标准 chat-completions + 流式 tool calling（本部署未启用 `enable_llm_proxy`）；
  `--stt none` 时还支持音频直输（音频 LLM），但当前未用。

### 3.4 TTS — Qwen3-TTS-CustomVoice（`TTS/qwen3_tts_handler.py` + `qwen3_tts_arguments.py`）

- **当前配置**：本地 `/root/.cache/qwen3-tts-model`（默认即 `Qwen3-TTS-12Hz-1.7B-CustomVoice`）、
  `backend=torch`、`device=cuda`、`non_streaming_mode=False`（流式）、`streaming_chunk_size=4`、
  `language=auto`、speaker 默认 `Aiden`。
- **可调参数**：`qwen3_tts_model_name`、`qwen3_tts_device`、`qwen3_tts_dtype`（auto/float16/
  bfloat16/float32）、`qwen3_tts_attn_implementation`（eager/flash_attention_2/sdpa）、
  `qwen3_tts_backend`（ggml/torch）、`qwen3_tts_ggml_quantization`（BF16/Q8_0/Q4_K_M/F32，
  torch 后端忽略）、`qwen3_tts_speaker`（预设音色）、`qwen3_tts_instruct`（VoiceDesign）、
  声音克隆 `qwen3_tts_ref_audio`/`qwen3_tts_ref_spk`/`qwen3_tts_ref_rvq`/`qwen3_tts_ref_text`/
  `qwen3_tts_xvec_only`、`qwen3_tts_non_streaming_mode`、`qwen3_tts_streaming_chunk_size`、
  `qwen3_tts_max_new_tokens`（1536）、`qwen3_tts_blocksize`（512）。
- **能力**：`QWEN3_LANGUAGE_ALIASES` 支持 zh/en/ja/ko/de/fr/ru/pt/es/it 等（2 字母码
  → 语言名，如 `zh→chinese`、`ja→japanese`）；三种生成模式——**预设音色（CustomVoice）/
  声音克隆 / 音色设计**；支持句内流式（`streaming_chunk_size`）。

---

## 4. 提示词

系统提示由 `LLM/voice_prompt.py:build_voice_system_prompt(session_prompt, tool_section,
language_name)` 拼装，顺序为：

```
{VOICE_SYSTEM_PROMPT_LEAD}
Session Prompt:
{init_chat_prompt}{可选 tools 块}{可选 language 指令}
{VOICE_SYSTEM_PROMPT_TAIL}
```

- **LEAD**：`You are in a spoken conversation...`（定义语音对话场景，channel rules 只管
  口语输出与工具行为）。
- **Session Prompt（`--init_chat_prompt`，即当前实际系统人设）**：
  > `You are a helpful voice assistant. Keep every reply very short: one or two spoken
  > sentences unless the user asks for detail. Reply in the user's language.`
- **TAIL（Voice Rules）**：口语规则——默认简短（一两句）、不用 markdown/列表/动作描写、
  把转写当噪声（只在必要时纠正误听）、默认用语音、用工具时不提工具名、信息类工具立即
  执行而非只提议、表情/背景类工具先说话等。
- **可选 language 指令**（`LLM/utils.py:format_language_instruction`）：开启
  `enable_lang_prompt` 或 `detect_llm_output_language` 时追加“请用 X 语言回复”。
- **历史压缩提示**（`LLM/compaction_prompt.py`）：`COMPACTION_SYSTEM_PROMPT` 把超长历史
  压缩为 `user_summary` / `assistant_summary` 的 JSON（信息密度优先，保留名字/数字/路径/
  错误），`compact_history=True` 时后台调用 LLM 做摘要以保上下文不溢出。
- **文本通道提示**（`LLM/text_prompt.py`）：`build_text_system_prompt`（书面场景，允许
  markdown），语音链路默认不走这条。
- **工具提示**（`LLM/tool_call/tool_prompt.py`）：把工具描述格式化为可选的 tools 块注入
  系统提示。

---

## 5. 全局 / 服务参数（`arguments_classes/module_arguments.py`）

| 参数 | 默认值 | 说明 |
|---|---|---|
| `num_pipelines` | 1 | 隔离的 pipeline 实例数；最大并发 = 该值，超出拒绝 |
| `enable_live_transcription` | True | 实时字幕（本部署 `--no_enable_live_transcription` 关闭） |
| `live_transcription_update_interval` | 0.5s | 字幕刷新间隔 |
| `log_level` | info | 日志级别（debug 排查用） |
| `log_transcripts` | False | 是否把对话文本写进应用日志（默认关，避免隐私外泄） |
| `torch_num_threads` | None | 全局 PyTorch CPU 线程数（影响 Silero / CPU STT） |
| `device` | None | 全局设备覆盖，会覆盖各 handler 的 device |
| `diarization` | False | 说话人分离（Nemotron 3 Diarization） |
| `detect_llm_output_language` | False | 按 LLM 输出语种检测后传给 TTS |
| `enable_llm_proxy` | False | 把支持代理的 LLM 后端暴露为 OpenAI 兼容 HTTP 端点 |

---

## 6. 常见调整场景与 compose 参数

下面每个场景给出**在 `pipeline` 服务 `command:` 列表中追加 / 修改的片段**。compose 中
布尔开关默认 True 时以 `--no_<flag>` 关闭（同现有 `--no_smart_turn` /
`--no_enable_live_transcription`）；数值 / 字符串参数用「`- 标志` / `- 值`」两行。
`...` 表示保留现有其它行。

### 6.1 改 TTS 音色

```yaml
    command:
      ...
      # 预设音色（CustomVoice）；默认 Aiden，可用音色取决于具体 CustomVoice 模型
      - --qwen3_tts_speaker
      - "Aiden"          # 换成模型支持的其它预设名
```

> 列出某模型支持的预设音色：运行 `model.get_supported_speakers()`，或参考该 CustomVoice
> 模型文档。

### 6.2 声音克隆（用参考音频定制音色）

```yaml
    command:
      ...
      - --qwen3_tts_ref_audio
      - /root/.cache/ref_voice.wav        # 容器内路径（需 bind 挂载该文件）
      - --qwen3_tts_ref_text
      - "I'm confused why some people have super short timelines..."
      # 可选：用 x-vector only 模式，语言切换更干净
      - --qwen3_tts_xvec_only
```
如使用预计算嵌入（GGML 后端）：`- --qwen3_tts_ref_spk /root/.cache/voice.spk`
（配合 `- --qwen3_tts_ref_rvq /root/.cache/voice.rvq` 与 `--qwen3_tts_ref_text`）。

### 6.3 音色设计（VoiceDesign 模型）

```yaml
    command:
      ...
      - --qwen3_tts_instruct
      - "A calm male narrator with a warm, deep voice."
```
（仅当模型为 VoiceDesign 类时需要 `instruct`；CustomVoice 用 `--qwen3_tts_speaker`。）

### 6.4 改 TTS 语种

```yaml
    command:
      ...
      - --qwen3_tts_language
      - "chinese"        # 或 "english" / "japanese" / "korean" / "french" ...
                         # 也接受 2 字母码：zh / en / ja / ko / de / fr / ru / pt / es / it
```
`QWEN3_LANGUAGE_ALIASES` 会把 `zh→chinese`、`ja→japanese` 等归一化；`auto`（默认）跟随
上游语种。

### 6.5 改 STT 语种（固定识别语言，不再自动检测）

```yaml
    command:
      ...
      - --qwen3_asr_language
      - "zh"             # ISO 码或语言名；auto 为自动检测（默认）
```

### 6.6 STT 热词 / 上下文偏置

```yaml
    command:
      ...
      - --qwen3_asr_prompt
      - "Vocabulary: Quilter, apostle, Kubernetes."
```

### 6.7 改 STT 生成长度上限

```yaml
    command:
      ...
      - --qwen3_asr_gen_max_new_tokens
      - "256"            # 每轮最大生成 token；调大支持更长语句
```

### 6.8 改 LLM 模型 / 端点

```yaml
    command:
      ...
      - --model_name
      - "Qwen3-8B"                         # 换成 GPUStack 上的其它模型
      - --responses_api_base_url
      - "http://192.168.40.30/v1-openai"    # OpenAI 兼容端点
      - --responses_api_api_key
      - "not-needed"                        # 如需鉴权填真实 key
```
也支持用 `.env.local` 的变量：`GPUSTACK_MODEL` / `GPUSTACK_BASE_URL` / `GPUSTACK_API_KEY`
（compose 中以 `${GPUSTACK_MODEL:-Qwen3-8B}` 形式引用）。

### 6.9 开 / 关 LLM 推理（thinking / reasoning）

当前 `responses_api_reasoning_effort` 设为空字符串，等效关闭推理（走
`enable_thinking=false`）。按需调整：

```yaml
    command:
      ...
      # 关闭推理（默认行为，显式写出）：
      - --responses_api_reasoning_effort
      - "none"          # none / low / medium / high；为空字符串也等效 none
      # 若需“开启思考”，把值改为 low/medium/high；
      # 或反向控制底层开关（默认已 disable_thinking，下面用于恢复思考）：
      # - --no_responses_api_disable_thinking
```

### 6.10 改流式粒度（TTS 触发时机）

```yaml
    command:
      ...
      - --stream_batch_sentences
      - "1"             # 1 = 逐句流式（最快出声）；3 = 累积 3 句再吐（默认）
```

### 6.11 调 VAD 静音判停（打断 / 尾静音）

```yaml
    command:
      ...
      - --min_silence_ms
      - "700"           # 句末静音判定阈值，越大越“晚停”
      - --min_speech_ms
      - "384"           # 最短有效语音段，过短丢弃
      - --thresh
      - "0.6"           # VAD 置信阈值
      # - --max_speech_ms        # 连续语音强制切分上限（默认 ∞）
      # - --speech_pad_ms        # 段前保留音频（默认 500）
      # - --min_speech_continuation_ms  # 续接软尾段的最短语音（默认 192）
```

### 6.12 开启 Smart Turn（更智能的“是否说完”判断）

当前 `--no_smart_turn` 关闭；模型已挂载到 `/root/.cache/smart-turn-v3.2-cpu.onnx`。
开启并调参：

```yaml
    command:
      ...
      # 删掉 --no_smart_turn，改为显式开启并调参：
      - --smart_turn
      - --smart_turn_threshold
      - "0.5"           # 越高越愿意在含糊停顿处等待
      - --smart_turn_max_wait_ms
      - "2000"          # 报告“未说完”时的推测性重开宽限
      - --smart_turn_incomplete_delay_ms
      - "600"           # 推后 STT/LLM 处理，留出续话说无效化的时间
      # - --smart_turn_model_path /root/.cache/smart-turn-v3.2-cpu.onnx  （已挂）
```

### 6.13 开启实时字幕（live transcription）

```yaml
    command:
      ...
      # 删掉 --no_enable_live_transcription，改为：
      - --enable_live_transcription
      - --live_transcription_update_interval
      - "0.5"           # 刷新间隔（秒）
```

### 6.14 多并发（增加 pipeline 实例）

```yaml
    command:
      ...
      - --num_pipelines
      - "2"             # 同时容纳 2 个会话；超出会被拒绝
```
注意：每个 pipeline 各占一套 VAD/STT/LLM/TTS handler 与显存，需 GPU 资源足够。

### 6.15 历史 / 上下文长度

```yaml
    command:
      ...
      - --chat_size
      - "30"            # 保留的最近 user/assistant 轮数
      # 历史压缩（默认开）；关闭则超长直接淘汰旧轮次：
      - --no_compact_history
```

### 6.16 语种指令注入（强制 LLM 用某语言回复）

```yaml
    command:
      ...
      - --enable_lang_prompt            # 每轮在系统提示追加“请用 X 语言回复”
      # 或按 LLM 实际输出语种检测后再交给 TTS：
      - --detect_llm_output_language
```

### 6.17 设备 / 精度覆盖

```yaml
    command:
      ...
      - --device
      - "cuda"                 # 全局覆盖所有 handler 的 device
      - --qwen3_asr_device
      - "auto"                 # STT 单独指定
      - --qwen3_tts_device
      - "cuda"                 # TTS 单独指定
      - --qwen3_asr_torch_dtype
      - "auto"                 # STT 精度
      - --qwen3_tts_dtype
      - "auto"                 # TTS 精度
      - --qwen3_tts_attn_implementation
      - "flash_attention_2"    # eager / flash_attention_2 / sdpa
```

### 6.18 切换 TTS 后端（torch ↔ ggml）

```yaml
    command:
      ...
      # torch 后端（当前，用 GPU）：
      - --qwen3_tts_backend
      - "torch"
      # 或 ggml 后端（CPU / 低延迟，量化可选）：
      # - --qwen3_tts_backend
      # - "ggml"
      # - --qwen3_tts_ggml_quantization
      # - "Q8_0"        # BF16 / Q8_0 / Q4_K_M / F32
```

### 6.19 TTS 流式 / 非流式

```yaml
    command:
      ...
      - --qwen3_tts_non_streaming_mode
      - "False"               # False = 句内流式（默认，出声快）
      - --qwen3_tts_streaming_chunk_size
      - "4"                   # 每个流式块的 codec 步数（torch 默认 4，ggml 默认 8）
```

### 6.20 切换 VAD 后端（Silero ↔ FireRed）

```yaml
    command:
      ...
      - --vad
      - "firered"
      - --vad_firered_model_dir
      - "/root/.cache/fireredvad"   # 需包含 cmvn.ark
      # - --vad_firered_use_gpu            # 可选：FireRed 跑 GPU
```
（FireRed 需要 `fireredvad` 可选依赖与 Stream-VAD 权重。）

### 6.21 说话人分离（diarization）

```yaml
    command:
      ...
      - --diarization
      # - --diarization_model_name <checkpoint>   # 可选自定义流式分离 checkpoint
      # - --diarization_device auto
      # - --diarization_streaming_mode low_latency
```

### 6.22 日志 / 调试

```yaml
    command:
      ...
      - --log_level
      - "debug"              # info / debug / warning
      - --log_transcripts    # 把对话文本写入日志（默认关，注意隐私）
      - --torch_num_threads
      - "4"                  # 全局 PyTorch CPU 线程（影响 Silero / CPU STT）
```

### 6.23 音频增强

```yaml
    command:
      ...
      - --audio_enhancement   # 降噪 / 均衡，改善输入音质
```

### 6.24 自定义人设 / 系统提示

```yaml
    command:
      ...
      - --init_chat_role
      - "system"
      - --init_chat_prompt
      - "You are a helpful voice assistant. ..."
```

### 6.25 开启 LLM 代理端点（暴露 OpenAI 兼容 HTTP）

```yaml
    command:
      ...
      - --enable_llm_proxy
      - --llm_proxy_connect_timeout_s
      - "10.0"
```
> 仅在受信任网络或已加网关鉴权时开启；服务端自身不做认证。

---

## 7. 组合示例：把默认部署改成“中文客服 + 自定义音色 + 智能判停”

```yaml
services:
  pipeline:
    image: speech-to-speech-pipeline:latest
    command:
      - speech-to-speech
      - serve
      - --host
      - 0.0.0.0
      - --port
      - "8765"
      # LLM
      - --llm_backend
      - chat-completions
      - --model_name
      - "${GPUSTACK_MODEL:-Qwen3-8B}"
      - --responses_api_base_url
      - "${GPUSTACK_BASE_URL:-http://192.168.40.30/v1-openai}"
      - --responses_api_api_key
      - "${GPUSTACK_API_KEY:-not-needed}"
      - --responses_api_stream
      - --responses_api_reasoning_effort
      - "none"
      - --stream_batch_sentences
      - "1"
      # STT：固定中文
      - --stt
      - qwen3-asr
      - --qwen3_asr_model_name
      - /root/.cache/qwen3-asr-model-hf
      - --qwen3_asr_device
      - auto
      - --qwen3_asr_language
      - "zh"
      # TTS：自定义音色 + 中文
      - --tts
      - qwen3
      - --qwen3_tts_model_name
      - /root/.cache/qwen3-tts-model
      - --qwen3_tts_backend
      - torch
      - --qwen3_tts_device
      - cuda
      - --qwen3_tts_non_streaming_mode
      - "False"
      - --qwen3_tts_streaming_chunk_size
      - "4"
      - --qwen3_tts_language
      - "chinese"
      - --qwen3_tts_speaker
      - "Aiden"
      # VAD：开启 Smart Turn 智能判停
      - --min_silence_ms
      - "700"
      - --smart_turn
      - --smart_turn_threshold
      - "0.5"
      - --smart_turn_max_wait_ms
      - "2000"
      - --smart_turn_incomplete_delay_ms
      - "600"
      - --smart_turn_model_path
      - /root/.cache/smart-turn-v3.2-cpu.onnx
      # 人设
      - --init_chat_role
      - system
      - --init_chat_prompt
      - "你是中文客服助手，语气礼貌简洁，用中文回复。"
      # 实时字幕 + 调试
      - --enable_live_transcription
      - --log_level
      - "info"
    ports:
      - "${PIPELINE_PORT:-8765}:8765/tcp"
    volumes:
      - ./cache/:/root/.cache/
      - ./silero-vad:/opt/silero-vad:ro
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              device_ids: ['${PIPELINE_GPU_ID:-0}']
              capabilities: [gpu]
```

> 改动后重启：`docker compose -f docker-compose.local.yml --env-file .env.local up -d`。
> 参数名称与各模型默认值以 `src/speech_to_speech/arguments_classes/` 下对应文件为准。

---

## 8. 语音合成风格参数配置方案（音色 / 语速 / 语气 / 情感 / 方言 / 自定义风格）

本方案定义六个语音风格属性的控制方式。每条属性均可通过 **调用参数**（compose 启动参数、
WebSocket 会话/响应参数）或 **提示词模板**（TTS `instruct`、LLM `instructions`）控制，
并给出取值范围、模板与可直接套用的范例。

### 8.1 四条控制通道

| 通道 | 载体 | 生效范围 | 需重启容器 |
|---|---|---|---|
| ① 启动参数 | compose `command:`（CLI 标志） | 进程级默认 | 是 |
| ② 会话参数 | ws `session.update` → `session.audio.output.voice`、`session.audio.input.transcription.language`、`session.instructions` | 单个连接（`on_session_end` 时音色复位） | 否 |
| ③ 响应参数 | ws `response.create` → `response.audio.output.voice` | 单次回复 | 否 |
| ④ 提示词模板 | TTS `instruct`（经 ① 注入）；LLM `instructions`（经 ① `--init_chat_prompt` 或 ② 注入） | instruct 进程级；instructions 会话级 | instruct 是 / instructions 否 |

代码落点：

- ②③ 音色覆盖：`TTS/qwen3_tts_handler.py::_apply_session_voice_override` —— CustomVoice
  模型按 `get_supported_speakers()` 大小写不敏感校验预设名；非预设名则尝试当作音频路径
  （声音克隆）；非法值告警并忽略。
- ② 语言：`_language_for_utterance(language_code, tts_input.selected_language)` —— 会话
  语言优先于启动配置；TTS 说不了的语言回退会话语言。
- ② `instructions`：`LLM/chat.py::prepend_instructions` —— 与系统提示拼接。
- ④ `instruct`：`generate_custom_voice(instruct=...)` / `generate_voice_design(instruct=...)`
  —— 所有 CustomVoice / VoiceDesign 合成都携带。

### 8.2 能力矩阵

| 属性 | ① 启动参数 | ② 会话参数 | ③ 响应参数 | ④ TTS instruct | ④ LLM instructions |
|---|---|---|---|---|---|
| 音色 | `--qwen3_tts_speaker` / `--qwen3_tts_ref_audio` / `--qwen3_tts_instruct`(VoiceDesign) | `audio.output.voice` | `audio.output.voice` | VoiceDesign：音色描述 | 间接（措辞影响听感） |
| 语速 | —（无数值参数） | — | — | 速度描述词 | 间接（短句、停顿、标点） |
| 语气 | `--qwen3_tts_instruct` | 扩展点 §8.11 | 同左 | 语气描述词 | 直接 |
| 情感 | `--qwen3_tts_instruct` | 扩展点 §8.11 | 同左 | 情感描述词 | 直接 |
| 方言 | `--qwen3_tts_instruct` + `--qwen3_tts_language zh` | 扩展点 §8.11 | 同左 | 方言描述词 | 直接 |
| 自定义风格 | `--qwen3_tts_instruct` | 扩展点 §8.11 | 同左 | 自由文本 | 直接 |

> 说明：`instruct` 目前是进程级常量（仅 ① 可设）；要按会话动态切换语气/情感/方言，见
> §8.11 扩展点。音色与语言是仅有的两个**原生支持会话级动态切换**的属性。

### 8.3 属性一：音色

**参数定义**

| 参数 | 类型 | 取值范围 | 默认 | 通道 |
|---|---|---|---|---|
| `qwen3_tts_speaker` | string | CustomVoice 预设音色名（枚举 = `model.get_supported_speakers()`，大小写不敏感） | `"Aiden"` | ① |
| `qwen3_tts_ref_audio` | path | 容器内音频文件路径（需 bind 挂载） | None（克隆模式） | ① |
| `qwen3_tts_ref_spk` / `ref_rvq` / `ref_text` / `xvec_only` | path / string / bool | 预计算克隆嵌入（GGML） / 参考音频转写 / x-vector-only 模式 | 见 §3.4 | ① |
| `qwen3_tts_instruct` | string | VoiceDesign 模型：自然语言音色描述 | None | ① |
| `audio.output.voice`（session/response） | string | 预设音色名 **或** 容器内音频路径 | 未设则用 ① 值 | ②③ |

**提示词模板（VoiceDesign 音色描述）**

```text
一个{性别}声音，{音质特征}，{韵律特征}。
```

**范例 A（参数方式，启动默认音色）**

```yaml
    command:
      ...
      - --qwen3_tts_speaker
      - "Aiden"          # 换成 get_supported_speakers() 返回的任一预设名
```

**范例 B（参数方式，会话内换音色，前端实时生效）**

```json
{
  "type": "session.update",
  "session": {
    "type": "realtime",
    "audio": { "output": { "voice": "Aiden" } }
  }
}
```

**范例 C（提示词方式，VoiceDesign 定制音色）**

```yaml
    command:
      ...
      - --qwen3_tts_instruct
      - "一个成熟女性声音，温柔清亮，标准播音腔，中速沉稳。"
```

> 查询可用预设音色：`python -c "from faster_qwen3_tts import ...; print(model.get_supported_speakers())"`，
> 或参考所加载模型的模型卡。

### 8.4 属性二：语速

Qwen3-TTS 处理器**没有数值型语速参数**，语速走两个提示词通道（外加一个可选后处理扩展）。

**取值映射表（TTS instruct 描述词）**

| 档位 | 模板词 |
|---|---|
| 很慢 | `非常缓慢地` |
| 偏慢 | `缓慢地` |
| 适中 | `以适中的语速`（默认） |
| 偏快 | `快速地` |
| 很快 | `非常快地` |

**参数定义（可选扩展，后处理 time-stretch）**

| 参数 | 类型 | 取值范围 | 默认 | 通道 |
|---|---|---|---|---|
| `qwen3_tts_speed`（扩展，§8.11） | float | 0.5 – 2.0（1.0 = 原速；<1 变慢，>1 变快） | 1.0 | ①② |

**提示词模板**

```text
TTS instruct:   {speed}说话。
LLM instructions: 用简短的句子，重要的词之间稍作停顿，保持{speed}的节奏。
```

**范例 A（提示词方式，TTS 层放慢）**

```yaml
    command:
      ...
      - --qwen3_tts_instruct
      - "用温和亲切的语气，非常缓慢地说话，适合老人收听。"
```

**范例 B（提示词方式，LLM 层控制节奏——对任何 TTS 都有效）**

```json
{
  "type": "session.update",
  "session": {
    "type": "realtime",
    "instructions": "你的回复要短，每句不超过 15 个字，多用句号制造停顿，节奏平缓。"
  }
}
```

### 8.5 属性三：语气

**参数定义**

| 参数 | 类型 | 取值范围（示例枚举，可自由扩展） | 默认 | 通道 |
|---|---|---|---|---|
| `qwen3_tts_instruct` 语气槽 | string | `温和亲切 / 正式专业 / 活泼轻快 / 严肃权威 / 低沉稳重 / 俏皮幽默 / 礼貌客服` | None | ①（②见 §8.11） |

**提示词模板**

```text
TTS instruct:     用{tone}的语气与听众交谈。
LLM instructions: 你与用户交谈的整体语气是{tone}：体现在措辞、称谓与句式上。
```

**范例（客服场景，参数 + 提示词组合）**

```yaml
    command:
      ...
      - --qwen3_tts_instruct
      - "用礼貌客服的语气与听众交谈，音量平稳，吐字清晰。"
      - --init_chat_prompt
      - "你是银行客服。整体语气礼貌专业：先称呼用户，再给结论，最后补一句确认。"
```

### 8.6 属性四：情感

**参数定义**

| 槽位 | 类型 | 取值范围（示例枚举） | 默认 | 通道 |
|---|---|---|---|---|
| emotion | string | `开心 / 平静 / 悲伤 / 生气 / 惊讶 / 兴奋 / 同情 / 鼓励 / 抱歉` | 平静 | ①（②见 §8.11） |
| intensity | string | `轻度 / 中度 / 强烈` | 中度 | ①（②见 §8.11） |

**提示词模板**

```text
TTS instruct:     带着{intensity}的{emotion}情感说话。
LLM instructions: 你的回复应传达{emotion}的情绪——在措辞和内容上自然流露，但保持语音助手应有的克制。
```

**范例（情绪安慰场景）**

```yaml
    command:
      ...
      - --qwen3_tts_instruct
      - "带着中度的同情情感说话，语速放缓，尾音柔和。"
```

```json
{
  "type": "session.update",
  "session": {
    "type": "realtime",
    "instructions": "用户情绪低落时，回复要简短、先共情再建议，语气像老朋友，不要说教。"
  }
}
```

> 注：模型对情感的实际表现力取决于所加载 CustomVoice / VoiceDesign 权重的训练覆盖，
> `instruct` 情感词建议先实测校准。

### 8.7 属性五：方言风格

方言 = **语言锁定中文 + instruct 方言描述**（+ 可选 LLM 方言口头语）。

**参数定义**

| 参数 | 类型 | 取值范围 | 默认 | 通道 |
|---|---|---|---|---|
| `qwen3_tts_language` | string | 方言场景固定 `zh`（`QWEN3_LANGUAGE_ALIASES` 归一化） | `auto` | ① |
| `qwen3_tts_instruct` 方言槽 | string | `粤语 / 四川话 / 东北话 / 上海话 / 北京话 / 台湾腔 …` | None | ①（②见 §8.11） |

**提示词模板**

```text
TTS instruct:     用{dialect}说话。
LLM instructions: 回复中自然融入{dialect}的表达习惯与口头语，但保证其他地区用户也能听懂。
```

**范例（四川话客服）**

```yaml
    command:
      ...
      - --qwen3_tts_language
      - "zh"                                        # 锁定中文，防止 auto 漂移
      - --qwen3_tts_instruct
      - "用四川话说话，语气热情爽快。"
      - --init_chat_prompt
      - "你是四川本地的餐饮客服，回答自然带四川话口头语（如巴适、要得），但保持易懂。"
```

> 可靠性提示：方言表现力取决于模型权重的方言覆盖；`instruct` 方言词需实测。若模型
> 不支持目标方言，会退化为带口音的普通话（可接受）或忽略方言词。

### 8.8 属性六：自定义风格

**参数定义**

| 参数 | 类型 | 取值范围 | 默认 | 通道 |
|---|---|---|---|---|
| `qwen3_tts_instruct` | string | 自由文本（建议 ≤ 2 句，具体可感的描述效果好于抽象词） | None | ①（②见 §8.11） |

**提示词模板（六属性组合模板——所有风格槽统一拼进一条 instruct）**

```text
用{tone}的语气，带着{intensity}的{emotion}情感，{speed}说话{，用{dialect}（可选）}。{custom}
```

**范例（深夜电台风格）**

```yaml
    command:
      ...
      - --qwen3_tts_instruct
      - "用低沉稳重的语气，带着轻度的平静情感，非常缓慢地说话，像深夜电台主持人，嗓音低沉带磁性，句尾轻轻收住。"
      - --init_chat_prompt
      - "你是深夜陪伴电台主播。回复像电台独白：舒缓、有画面感、不超过两句话。"
```

### 8.9 提示词 ↔ 参数对应关系总表

| 属性 | 参数位（通道①） | 提示词位（通道②/④） | 代码生效点 |
|---|---|---|---|
| 音色 | `--qwen3_tts_speaker` / `--qwen3_tts_ref_audio` | `audio.output.voice`（②③）；VoiceDesign 用 `instruct` 描述 | `_apply_session_voice_override` → `self.speaker` / `self.ref_audio` |
| 语言 | `--qwen3_tts_language` | `audio.input.transcription.language`（②） | `_language_for_utterance` → `generate_*(language=...)` |
| 语速 | —（扩展 `qwen3_tts_speed`） | `instruct` 速度描述词；LLM 短句/停顿指令 | `generate_custom_voice(instruct=...)` |
| 语气 | `--qwen3_tts_instruct` | `instruct` 语气槽；LLM `instructions` 语气定义 | 同上；LLM 侧 `prepend_instructions` |
| 情感 | `--qwen3_tts_instruct` | `instruct` 情感×强度槽；LLM 情绪表达指令 | 同上 |
| 方言 | `--qwen3_tts_language zh` + `--qwen3_tts_instruct` | `instruct` 方言槽；LLM 口头语指令 | 同上 |
| 自定义风格 | `--qwen3_tts_instruct` | `instruct` 自由文本；LLM 人设（`--init_chat_prompt` / ② `instructions`） | 同上 |

**使用原则**

1. 音色、语言 → 用**参数**（精确、可枚举、支持会话级切换）。
2. 语气、情感、方言、自定义风格 → 用**提示词**（`instruct` 管声音层面的风格，LLM
   `instructions` 管措辞层面的风格，两者叠加效果最好）。
3. 同一模板里的槽位可独立取值；槽位为空时从模板中整段删除，不要留"默认/无"字样。
4. 改 ① 需重启容器；改 ② 发 `session.update` 即时生效（音色在会话结束复位，语言与
   instructions 持续到会话结束）。

### 8.10 组合范例：完整配置（中文客服 + 定制语气/情感/语速）

```yaml
services:
  pipeline:
    image: speech-to-speech-pipeline:latest
    command:
      - speech-to-speech
      - serve
      - --host
      - 0.0.0.0
      - --port
      - "8765"
      - --llm_backend
      - chat-completions
      - --model_name
      - "${GPUSTACK_MODEL:-Qwen3-8B}"
      - --responses_api_base_url
      - "${GPUSTACK_BASE_URL:-http://192.168.40.30/v1-openai}"
      - --responses_api_api_key
      - "${GPUSTACK_API_KEY:-not-needed}"
      - --responses_api_stream
      - --stream_batch_sentences
      - "1"
      # STT：锁定中文
      - --stt
      - qwen3-asr
      - --qwen3_asr_model_name
      - /root/.cache/qwen3-asr-model-hf
      - --qwen3_asr_device
      - auto
      - --qwen3_asr_language
      - "zh"
      # TTS：音色（参数）+ 语气/情感/语速/方言（instruct 模板）
      - --tts
      - qwen3
      - --qwen3_tts_model_name
      - /root/.cache/qwen3-tts-model
      - --qwen3_tts_backend
      - torch
      - --qwen3_tts_device
      - cuda
      - --qwen3_tts_non_streaming_mode
      - "False"
      - --qwen3_tts_streaming_chunk_size
      - "4"
      - --qwen3_tts_language
      - "zh"
      - --qwen3_tts_speaker
      - "Aiden"
      - --qwen3_tts_instruct
      - "用礼貌客服的语气，带着轻度的鼓励情感，以适中的语速说话，吐字清晰。"
      # 人设（LLM 层风格）
      - --init_chat_role
      - system
      - --init_chat_prompt
      - "你是银行客服。礼貌专业：先称呼用户，再给结论，最后确认。语气克制，不说教。"
    ports:
      - "${PIPELINE_PORT:-8765}:8765/tcp"
    volumes:
      - ./cache/:/root/.cache/
      - ./silero-vad:/opt/silero-vad:ro
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              device_ids: ['${PIPELINE_GPU_ID:-0}']
              capabilities: [gpu]
```

**会话内动态调整（参数方式，免重启）**

```json
{
  "type": "session.update",
  "session": {
    "type": "realtime",
    "instructions": "夜间时段用户来电，请把语气放得更柔和，语速稍慢，先安抚再办业务。",
    "audio": {
      "input": { "transcription": { "language": "zh" } },
      "output": { "voice": "Aiden" }
    }
  }
}
```

**单次回复临时换音色（响应方式）**

```json
{
  "type": "response.create",
  "response": {
    "audio": { "output": { "voice": "Aiden" } }
  }
}
```

### 8.11 扩展点：会话级动态切换语气 / 情感 / 方言（可选实现）

**现状**：`instruct` 在 handler 构造时固定（`self.instruct`），`session.update` 只原生
覆盖音色与语言，不覆盖风格。

**建议实现（约 30 行）**：复用现有 `session.extensions` 机制（`RuntimeConfig` 已用它承载
字幕快照开关），约定一条扩展键：

```json
{
  "type": "session.update",
  "session": {
    "type": "realtime",
    "extensions": [
      "speech_to_speech.tts.instruct=用活泼轻快的语气，带着中度的开心情感，快速地说话。"
    ]
  }
}
```

落点改动：

1. `api/openai_realtime/runtime_config.py`：新增 `tts_instruct: str | None` 属性，从
   `session.extensions` 解析前缀 `speech_to_speech.tts.instruct=` 的条目。
2. `TTS/qwen3_tts_handler.py::_apply_session_voice_override` 旁新增
   `_apply_session_instruct_override(runtime_config)`：非空时写入 `self.instruct`，
   并在 `on_session_end` 中复位（与 `self.speaker` 的复位逻辑同款，参照现有
   `_initial_speaker` 模式）。

改动后，§8.5–§8.8 的语气 / 情感 / 方言 / 自定义风格即可从"进程级"升级为"会话级"，
其余通道无需变化。

### 8.12 合并冲突解决记录（2026-10-20 已处理）

仓库处于一次合并中途：HEAD = `4f1ecb1`（含模型监控特性 `f88ce2c`），MERGE_HEAD =
`619e3fe`（PR #719 语音延迟归因，逐句语言 + 延迟跟踪）。

**`TTS/qwen3_tts_handler.py` 的 3 处冲突已解决**（导入 / 生成主体 / 音频统计块），合并策略
为**两侧特性都保留**：

- 导入：`model_monitor._truncate`（监控埋点用）+ `utils.resolve_device`（`setup` 中
  torch 后端设备解析已引用，缺导入会 `NameError`）同时保留；
- 生成主体：`request_language` 逐句语言传入 `_process_*`，外层包
  `bind_active_turn_latency_tracker(tracker)`（延迟归因），再包 `monitor.trace`
  （监控埋点，`language` 字段用 `request_language`），并保留音频字节统计
  （`rec.set_output`）与错误记录（`rec.error`）；
- 测试文件同步更新：测试用 `object.__new__` 构造 handler 会绕过
  `BaseHandler.__init__`（monitor）与 `setup`（model_name），模块级补了 no-op 桩。
  `tests/test_qwen3_tts_handler_backend.py` **70 passed**。

> 修复前的人为解决留有缺陷：`request_language` 算了不传、`resolve_device` 导入被删
> （torch 后端启动即 NameError）、延迟绑定与监控埋点被丢弃——现已全部纠正。

**合并仍未完成**：以下 4 个文件还有冲突标记未解决（合计 8 处），当前无法全量 import，
会影响从源码启动与全量测试收集：

| 文件 | 冲突处数 |
|---|---|
| `src/speech_to_speech/LLM/language_model.py` | 3 |
| `src/speech_to_speech/STT/paraformer_handler.py` | 3 |
| `src/speech_to_speech/VAD/vad_handler.py` | 1 |
| `src/speech_to_speech/s2s_pipeline.py` | 1 |

（`baseHandler.py` 已被解决但未 `git add`。）解决建议同本次策略：HEAD 的监控埋点与
theirs 的延迟归因/设备解析合并保留，而不是二选一。
