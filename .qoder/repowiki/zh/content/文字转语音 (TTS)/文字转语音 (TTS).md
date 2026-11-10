# 文字转语音 (TTS)

<cite>
**本文引用的文件**   
- [src/speech_to_speech/TTS/README.md](file://src/speech_to_speech/TTS/README.md)
- [src/speech_to_speech/TTS/qwen3_tts_handler.py](file://src/speech_to_speech/TTS/qwen3_tts_handler.py)
- [src/speech_to_speech/TTS/kokoro_handler.py](file://src/speech_to_speech/TTS/kokoro_handler.py)
- [src/speech_to_speech/TTS/chatTTS_handler.py](file://src/speech_to_speech/TTS/chatTTS_handler.py)
- [src/speech_to_speech/TTS/omnivoice_handler.py](file://src/speech_to_speech/TTS/omnivoice_handler.py)
- [src/speech_to_speech/TTS/phonon_tts_handler.py](file://src/speech_to_speech/TTS/phonon_tts_handler.py)
- [src/speech_to_speech/arguments_classes/phonon_tts_arguments.py](file://src/speech_to_speech/arguments_classes/phonon_tts_arguments.py)
- [src/speech_to_speech/utils/model_monitor.py](file://src/speech_to_speech/utils/model_monitor.py)
- [src/speech_to_speech/baseHandler.py](file://src/speech_to_speech/baseHandler.py)
- [src/speech_to_speech/pipeline/visemes.py](file://src/speech_to_speech/pipeline/visemes.py)
- [src/speech_to_speech/api/openai_realtime/visemes.py](file://src/speech_to_speech/api/openai_realtime/visemes.py)
</cite>

## 更新摘要
**变更内容**   
- 新增 Phonon TTS 引擎支持，提供高性能 CPU 流式语音合成
- 增强所有 TTS handler 的模型监控能力，集成统一的性能追踪和资源监控
- 更新架构图以包含新的 Phonon 引擎
- 扩展故障排除指南以涵盖 Phonon 特定的配置问题

## 目录
1. [简介](#简介)
2. [项目结构](#项目结构)
3. [核心组件](#核心组件)
4. [架构总览](#架构总览)
5. [详细组件分析](#详细组件分析)
6. [依赖关系分析](#依赖关系分析)
7. [性能与延迟优化](#性能与延迟优化)
8. [模型监控与性能追踪](#模型监控与性能追踪)
9. [故障排除指南](#故障排除指南)
10. [结论](#结论)
11. [附录：集成示例与参数速查](#附录：集成示例与参数速查)

## 简介
本技术文档面向 TTS（文字转语音）子系统，系统性梳理多种后端引擎的架构、实现要点与使用方式。重点覆盖 Qwen3-TTS、Kokoro、ChatTTS、OmniVoice、Phonon 等引擎的技术优势；说明流式合成、多语言支持、声音克隆、口型同步（visemes）、音频格式与采样率处理；并给出性能基准建议、资源需求、平台兼容性、音质与延迟调优策略、实际集成示例与常见问题排查方法。

## 项目结构
TTS 子系统位于 `src/speech_to_speech/TTS`，每个引擎以独立 handler 模块提供统一接口；运行时通过统一的 pipeline 消息类型进行输入输出，并在 OpenAI Realtime 扩展中暴露 visemes 事件。

```mermaid
graph TB
subgraph "TTS 模块"
Q3["Qwen3-TTS<br/>qwen3_tts_handler.py"]
KOK["Kokoro<br/>kokoro_handler.py"]
CHAT["ChatTTS<br/>chatTTS_handler.py"]
OMNI["OmniVoice<br/>omnivoice_handler.py"]
PHONON["Phonon<br/>phonon_tts_handler.py"]
end
subgraph "Pipeline 与协议"
VIS["Viseme 模型<br/>pipeline/visemes.py"]
RVIS["RT Visemes 事件<br/>api/openai_realtime/visemes.py"]
MON["模型监控<br/>utils/model_monitor.py"]
end
Q3 --> VIS
KOK --> VIS
CHAT --> VIS
OMNI --> VIS
PHONON --> VIS
VIS --> RVIS
Q3 --> MON
KOK --> MON
CHAT --> MON
OMNI --> MON
PHONON --> MON
```

**图表来源**
- [src/speech_to_speech/TTS/qwen3_tts_handler.py:96-1085](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L96-L1085)
- [src/speech_to_speech/TTS/kokoro_handler.py:82-506](file://src/speech_to_speech/TTS/kokoro_handler.py#L82-L506)
- [src/speech_to_speech/TTS/chatTTS_handler.py:27-163](file://src/speech_to_speech/TTS/chatTTS_handler.py#L27-L163)
- [src/speech_to_speech/TTS/omnivoice_handler.py:28-230](file://src/speech_to_speech/TTS/omnivoice_handler.py#L28-L230)
- [src/speech_to_speech/TTS/phonon_tts_handler.py:26-236](file://src/speech_to_speech/TTS/phonon_tts_handler.py#L26-L236)
- [src/speech_to_speech/pipeline/visemes.py:1-18](file://src/speech_to_speech/pipeline/visemes.py#L1-L18)
- [src/speech_to_speech/api/openai_realtime/visemes.py:1-18](file://src/speech_to_speech/api/openai_realtime/visemes.py#L1-L18)
- [src/speech_to_speech/utils/model_monitor.py:302-472](file://src/speech_to_speech/utils/model_monitor.py#L302-L472)

章节来源
- [src/speech_to_speech/TTS/README.md:13-29](file://src/speech_to_speech/TTS/README.md#L13-L29)

## 核心组件
- **Qwen3-TTS**：跨平台高性能 TTS，Apple Silicon 走 MLX，其他平台走 faster-qwen3-tts；支持声音克隆、预设说话人、声音设计；自动语言映射与流式分块。
- **Kokoro**：多语言高质量 TTS，Apple Silicon 走 MLX，其他平台走原生 kokoro；按语言自动选择默认音色，支持速度控制。
- **ChatTTS**：基于 ChatTTS 库的流式/非流式合成，自动重采样到 16kHz，支持 MPS/CUDA/NPU/CPU。
- **OmniVoice**：扩散式语音合成，支持参考音频克隆、按语言预置克隆提示、指令式声音设计；阻塞生成后分块输出。
- **Phonon**：高性能 CPU 流式 TTS，基于 ptts 原生运行时；支持多语言文本规范化、实时流式合成、高质量重采样。

**章节来源**
- [src/speech_to_speech/TTS/qwen3_tts_handler.py:96-1085](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L96-L1085)
- [src/speech_to_speech/TTS/kokoro_handler.py:82-506](file://src/speech_to_speech/TTS/kokoro_handler.py#L82-L506)
- [src/speech_to_speech/TTS/chatTTS_handler.py:27-163](file://src/speech_to_speech/TTS/chatTTS_handler.py#L27-L163)
- [src/speech_to_speech/TTS/omnivoice_handler.py:28-230](file://src/speech_to_speech/TTS/omnivoice_handler.py#L28-L230)
- [src/speech_to_speech/TTS/phonon_tts_handler.py:26-236](file://src/speech_to_speech/TTS/phonon_tts_handler.py#L26-L236)

## 架构总览
TTS 各 handler 遵循统一接口：setup 初始化模型与设备，process 接收文本输入并产出固定大小的 int16 PCM 音频块；同时记录 TTFA（首音频时间）和端到端延迟，支持取消与推测性回合。所有 handler 都集成了统一的模型监控功能。

```mermaid
sequenceDiagram
participant Pipe as "Pipeline"
participant Handler as "TTS Handler"
participant Monitor as "ModelMonitor"
participant Model as "底层模型/库"
participant RT as "Realtime 扩展"
Pipe->>Handler : process(TTSInput)
Handler->>Monitor : trace(category, model_name, input)
Handler->>Model : generate/stream(...)
Model-->>Handler : 音频块(不同采样率)
Handler->>Handler : 重采样至 16kHz / int16 / 分块
Handler-->>Pipe : 音频块 + 指标(TTFA/E2E)
Handler->>Monitor : 记录资源使用统计
Pipe->>RT : 可选 visemes 事件
```

**图表来源**
- [src/speech_to_speech/TTS/qwen3_tts_handler.py:704-762](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L704-L762)
- [src/speech_to_speech/TTS/kokoro_handler.py:328-418](file://src/speech_to_speech/TTS/kokoro_handler.py#L328-L418)
- [src/speech_to_speech/TTS/chatTTS_handler.py:94-163](file://src/speech_to_speech/TTS/chatTTS_handler.py#L94-L163)
- [src/speech_to_speech/TTS/omnivoice_handler.py:127-230](file://src/speech_to_speech/TTS/omnivoice_handler.py#L127-L230)
- [src/speech_to_speech/TTS/phonon_tts_handler.py:125-167](file://src/speech_to_speech/TTS/phonon_tts_handler.py#L125-L167)
- [src/speech_to_speech/api/openai_realtime/visemes.py:10-18](file://src/speech_to_speech/api/openai_realtime/visemes.py#L10-L18)
- [src/speech_to_speech/utils/model_monitor.py:357-390](file://src/speech_to_speech/utils/model_monitor.py#L357-L390)

## 详细组件分析

### Qwen3-TTS 组件
- 后端选择：Apple Silicon 使用 mlx-audio；其他平台使用 faster-qwen3-tts（ggml/torch）。
- 模式支持：声音克隆（原始参考或缓存 .spk/.rvq）、CustomVoice 预设说话人、VoiceDesign 指令。
- 语言处理：内置语言别名映射，支持 auto 检测与会话级覆盖。
- 流式与分块：统一 _stream 循环，TTFA 统计、RTF 日志、静音裁剪、blocksize 对齐。
- 采样率：统一到 PIPELINE_SR=16000，int16 输出。
- 会话状态：on_session_end 恢复初始 speaker/ref_audio/ref_spk/ref_rvq。

```mermaid
classDiagram
class Qwen3TTSHandler {
+setup(...)
+warmup()
+process(tts_input) Iterator
-_stream(gen, label) Iterator
-_estimate_max_new_tokens(text) int
-_resample_to_pipeline_sr(audio, sr) np.ndarray
-_apply_session_voice_override(...)
+on_session_end()
}
```

**图表来源**
- [src/speech_to_speech/TTS/qwen3_tts_handler.py:96-1085](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L96-L1085)

章节来源
- [src/speech_to_speech/TTS/qwen3_tts_handler.py:96-1085](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L96-L1085)

### Kokoro 组件
- 后端选择：Apple Silicon 使用 mlx-audio；其他平台使用原生 kokoro。
- 多语言：Whisper/langdetect 代码到 Kokoro lang_code 映射；为不支持的语言回退到英语变体。
- 音色管理：按语言默认音色，支持客户端 voice 覆盖；MLX 下预加载常用语言音色以降低首次延迟。
- 音频处理：24kHz→16kHz 重采样，int16，blocksize 分块；TTFA/E2E 指标记录。
- 会话重置：on_session_end 恢复初始 voice/lang_code。

```mermaid
flowchart TD
Start(["进入 process"]) --> DetectLang["根据 language_code 选择 lang_code/voice"]
DetectLang --> Backend{"Apple Silicon?"}
Backend --> |是| MLX["mlx-audio 管线生成"]
Backend --> |否| Native["原生 kokoro 管线生成"]
MLX --> Resample["24kHz→16kHz 重采样"]
Native --> Resample
Resample --> Int16["转换为 int16"]
Int16 --> Chunk["按 blocksize 分块输出"]
Chunk --> End(["结束"])
```

**图表来源**
- [src/speech_to_speech/TTS/kokoro_handler.py:311-418](file://src/speech_to_speech/TTS/kokoro_handler.py#L311-L418)

章节来源
- [src/speech_to_speech/TTS/kokoro_handler.py:82-506](file://src/speech_to_speech/TTS/kokoro_handler.py#L82-L506)

### ChatTTS 组件
- 模型加载：ChatTTS.Chat，支持 CUDA/NPU/MPS/CPU；MPS 场景有额外同步与缓存清理逻辑。
- 流式/非流式：infer 返回流式生成器或完整波形；统一重采样到 16kHz，int16 分块。
- 指标：TTFA 在首个 provider 样本前记录；E2E 在首次 yield 时记录。

```mermaid
sequenceDiagram
participant H as "ChatTTSHandler"
participant C as "ChatTTS.Chat"
H->>C : infer(text, stream, params)
alt 流式
C-->>H : 多个音频块
H->>H : librosa.resample(24k→16k), int16, 分块
else 非流式
C-->>H : 完整波形
H->>H : resample/int16/分块
end
H-->>H : 记录 TTFA/E2E
```

**图表来源**
- [src/speech_to_speech/TTS/chatTTS_handler.py:27-163](file://src/speech_to_speech/TTS/chatTTS_handler.py#L27-L163)

章节来源
- [src/speech_to_speech/TTS/chatTTS_handler.py:27-163](file://src/speech_to_speech/TTS/chatTTS_handler.py#L27-L163)

### OmniVoice 组件
- 克隆与指令：支持 ref_audio+ref_text 克隆、预存 voice_clone_prompt、按语言目录预置克隆提示；或 instruct 声音设计。
- 生成特性：generate 为阻塞调用，完成后按 blocksize 切块输出；支持 num_steps 与 speed 控制。
- 采样率：默认 24kHz，统一重采样到 16kHz，int16 输出。
- 取消：在阻塞生成后检查 cancel_scope，丢弃已完成的缓冲。

```mermaid
flowchart TD
S(["开始"]) --> Prep["准备克隆提示/指令/语言"]
Prep --> Gen["model.generate(...) 阻塞生成"]
Gen --> CheckCancel{"是否被取消?"}
CheckCancel --> |是| Drop["丢弃结果并返回"]
CheckCancel --> |否| Resample["24kHz→16kHz 重采样"]
Resample --> Int16["int16 量化"]
Int16 --> Chunk["按 blocksize 分块输出"]
Chunk --> E(["结束"])
```

**图表来源**
- [src/speech_to_speech/TTS/omnivoice_handler.py:28-230](file://src/speech_to_speech/TTS/omnivoice_handler.py#L28-L230)

章节来源
- [src/speech_to_speech/TTS/omnivoice_handler.py:28-230](file://src/speech_to_speech/TTS/omnivoice_handler.py#L28-L230)

### Phonon 组件
**新增** Phonon 是一个高性能 CPU 流式 TTS 引擎，基于 ptts 原生运行时，专为低延迟语音合成设计。

- **后端选择**：使用 ptts==0.4.0 Python 绑定，运行在 CPU 上；GPU 标志不影响 Phonon 的设备选择。
- **流式合成**：通过 `model.stream()` 上下文管理器实现真正的流式生成，支持实时音频输出。
- **语言处理**：支持 en、fr、de、es、pt、none 五种文本规范化语言，启动时固定配置。
- **音色管理**：支持 checkpoint 内建音色和远程 voice catalog 音色；catalog 不可用时回退到 checkpoint 音色。
- **音频处理**：原生 float32 音频流，使用 soxr 高质量重采样到 16kHz，int16 量化，固定 blocksize 输出。
- **线程优化**：支持进程级 CPU 线程池配置，默认 4 线程，可在模型加载前设置。
- **错误处理**：完整的取消支持、失败响应跟踪、会话状态管理。

```mermaid
classDiagram
class PhononTTSHandler {
+setup(should_listen, model_name, revision, voice, language, quant, blocksize, num_threads, gen_kwargs, cancel_scope, speculative_turns)
+_selectable_voices(ptts) str[]
-_validate_voice(voice) void
-_resolve_voice(tts_input) str|None
-_is_cancelled(generation, tts_input) bool
-_synthesize(tts_input, generation) Iterator
+process(tts_input) Iterator
+on_session_end() void
}
```

**图表来源**
- [src/speech_to_speech/TTS/phonon_tts_handler.py:26-236](file://src/speech_to_speech/TTS/phonon_tts_handler.py#L26-L236)

章节来源
- [src/speech_to_speech/TTS/phonon_tts_handler.py:26-236](file://src/speech_to_speech/TTS/phonon_tts_handler.py#L26-L236)
- [src/speech_to_speech/arguments_classes/phonon_tts_arguments.py:5-42](file://src/speech_to_speech/arguments_classes/phonon_tts_arguments.py#L5-L42)

### 口型同步（visemes）机制
- 数据模型：Viseme 包含 viseme 编号与起止时间（秒），保证区间有序。
- 实时扩展：SpeechToSpeechVisemesEvent 将 visemes 列表作为附加事件发送到客户端，不改变标准音频事件。

```mermaid
classDiagram
class Viseme {
+int viseme
+float start_s
+float end_s
}
class SpeechToSpeechVisemesEvent {
+string type
+string event_id
+string response_id
+string item_id
+int output_index
+int content_index
+Viseme[] visemes
}
SpeechToSpeechVisemesEvent --> Viseme : "包含"
```

**图表来源**
- [src/speech_to_speech/pipeline/visemes.py:1-18](file://src/speech_to_speech/pipeline/visemes.py#L1-L18)
- [src/speech_to_speech/api/openai_realtime/visemes.py:10-18](file://src/speech_to_speech/api/openai_realtime/visemes.py#L10-L18)

章节来源
- [src/speech_to_speech/pipeline/visemes.py:1-18](file://src/speech_to_speech/pipeline/visemes.py#L1-L18)
- [src/speech_to_speech/api/openai_realtime/visemes.py:1-18](file://src/speech_to_speech/api/openai_realtime/visemes.py#L1-L18)

## 依赖关系分析
- 平台相关依赖：
  - Apple Silicon：mlx-audio（Qwen3/Kokoro）。
  - 其他平台：faster-qwen3-tts（GGML/Torch）、kokoro、ChatTTS、omnivoice。
  - **新增**：Phonon 使用 ptts==0.4.0，仅支持 CPU 运行。
- 音频处理：scipy.signal.resample_poly、librosa（ChatTTS）、soxr（Phonon）。
- 设备选择：utils.resolve_device、torch 设备枚举。

```mermaid
graph LR
Q3["Qwen3-TTS"] --> FQT["faster-qwen3-tts"]
Q3 --> MLX["mlx-audio"]
KOK["Kokoro"] --> MLX
KOK --> KOKLib["kokoro"]
CHAT["ChatTTS"] --> CT["ChatTTS"]
OMNI["OmniVoice"] --> OV["omnivoice"]
PHONON["Phonon"] --> PTTS["ptts==0.4.0"]
All["所有 TTS"] --> SciPy["scipy.signal.resample_poly"]
CHAT --> Librosa["librosa"]
PHONON --> SoXR["soxr"]
```

**图表来源**
- [src/speech_to_speech/TTS/qwen3_tts_handler.py:222-268](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L222-L268)
- [src/speech_to_speech/TTS/kokoro_handler.py:153-195](file://src/speech_to_speech/TTS/kokoro_handler.py#L153-L195)
- [src/speech_to_speech/TTS/chatTTS_handler.py:8-12](file://src/speech_to_speech/TTS/chatTTS_handler.py#L8-L12)
- [src/speech_to_speech/TTS/omnivoice_handler.py:65-88](file://src/speech_to_speech/TTS/omnivoice_handler.py#L65-L88)
- [src/speech_to_speech/TTS/phonon_tts_handler.py:57-72](file://src/speech_to_speech/TTS/phonon_tts_handler.py#L57-L72)

章节来源
- [src/speech_to_speech/TTS/qwen3_tts_handler.py:222-268](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L222-L268)
- [src/speech_to_speech/TTS/kokoro_handler.py:153-195](file://src/speech_to_speech/TTS/kokoro_handler.py#L153-L195)
- [src/speech_to_speech/TTS/chatTTS_handler.py:8-12](file://src/speech_to_speech/TTS/chatTTS_handler.py#L8-L12)
- [src/speech_to_speech/TTS/omnivoice_handler.py:65-88](file://src/speech_to_speech/TTS/omnivoice_handler.py#L65-L88)
- [src/speech_to_speech/TTS/phonon_tts_handler.py:57-72](file://src/speech_to_speech/TTS/phonon_tts_handler.py#L57-L72)

## 性能与延迟优化
- 流式优先：
  - Qwen3-TTS：合理设置 streaming_chunk_size 与 max_new_tokens，减少 TTFA；启用 warmup。
  - ChatTTS：开启 stream=true，降低首包延迟。
  - Kokoro：预加载常用语言音色，避免首次下载开销。
  - **新增** Phonon：使用原生流式 API，blocksize 设置为 512 以获得最佳延迟平衡。
- 采样率与分块：
  - 统一输出 16kHz int16，blocksize 建议 512；OmniVoice 需 24kHz→16kHz 重采样。
  - **新增** Phonon：使用 soxr HQ 质量重采样，确保高质量音频转换。
- 设备与精度：
  - Qwen3-TTS：CUDA 用 torch backend，macOS 用 MLX；按需选择 GGML 量化（BF16/Q8_0/Q4_K_M/F32）或 MLX 量化（bf16/4bit/6bit/8bit）。
  - Kokoro：Apple Silicon 用 MLX，其他平台用原生 kokoro。
  - OmniVoice：dtype=float16/bfloat16/float32，num_steps 控制质量与延迟权衡。
  - **新增** Phonon：CPU 专用，num_threads 默认为 4，可根据硬件调整。
- 语言与音色：
  - Qwen3-TTS：auto 语言检测与会话覆盖；CustomVoice 指定说话人。
  - Kokoro：按语言自动选择默认音色，必要时显式 voice。
  - **新增** Phonon：固定语言规范化，支持 en/fr/de/es/pt/none。
- 中断与取消：
  - 所有 handler 均支持 cancel_scope；OmniVoice 在阻塞生成后检查取消并丢弃结果。
  - **新增** Phonon：完整的流式取消支持，关闭原生流并释放工作线程。

**章节来源**
- [src/speech_to_speech/TTS/qwen3_tts_handler.py:563-582](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L563-L582)
- [src/speech_to_speech/TTS/qwen3_tts_handler.py:624-667](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L624-L667)
- [src/speech_to_speech/TTS/kokoro_handler.py:197-213](file://src/speech_to_speech/TTS/kokoro_handler.py#L197-L213)
- [src/speech_to_speech/TTS/omnivoice_handler.py:172-178](file://src/speech_to_speech/TTS/omnivoice_handler.py#L172-L178)
- [src/speech_to_speech/TTS/phonon_tts_handler.py:36-40](file://src/speech_to_speech/TTS/phonon_tts_handler.py#L36-L40)
- [src/speech_to_speech/TTS/phonon_tts_handler.py:193-236](file://src/speech_to_speech/TTS/phonon_tts_handler.py#L193-L236)

## 模型监控与性能追踪
**新增** 所有 TTS handler 现已集成统一的模型监控功能，提供全面的性能追踪和资源使用情况监控。

### 监控功能概览
- **延迟追踪**：记录每次模型调用的墙钟持续时间。
- **资源使用**：GPU 利用率/显存、CPU 百分比和内存百分比，在调用期间定期采样。
- **输入/输出负载**：结构化摘要，截断以避免记录原始音频字节或巨大转录。
- **聚合统计**：每 30 秒输出一次汇总统计，包括调用次数、错误率、吞吐量（QPS）和延迟百分位数。

### 监控配置
- 环境变量：`MODEL_METRICS_LOG`、`MODEL_METRICS_LOG_MAX_BYTES`、`MODEL_METRICS_LOG_BACKUPS`
- 运行时配置：`configure_model_monitor(enabled, sample_interval, aggregate_interval_s, metrics_log_path)`
- 日志格式：JSON 行格式，分别写入 `model_metrics.log` 文件

### 监控数据结构
```mermaid
classDiagram
class CallRecord {
+string category
+string model_name
+float start_ts
+float duration_s
+dict input
+dict output
+dict resources
+string error
}
class ModelMonitor {
+trace(category, model_name, input) ContextManager
+get_model_monitor() ModelMonitor
+configure_model_monitor(...)
}
class ResourceSampler {
+start()
+stop()
+summary() dict
}
ModelMonitor --> CallRecord : "创建"
ModelMonitor --> ResourceSampler : "使用"
CallRecord --> ResourceSampler : "包含资源统计"
```

**图表来源**
- [src/speech_to_speech/utils/model_monitor.py:227-256](file://src/speech_to_speech/utils/model_monitor.py#L227-L256)
- [src/speech_to_speech/utils/model_monitor.py:302-472](file://src/speech_to_speech/utils/model_monitor.py#L302-L472)
- [src/speech_to_speech/baseHandler.py:54-56](file://src/speech_to_speech/baseHandler.py#L54-L56)

### 集成方式
所有 TTS handler 通过 BaseHandler 基类自动获得监控功能：
- BaseHandler 在初始化时获取全局 ModelMonitor 单例
- 各 handler 使用 `self.monitor.trace()` 上下文管理器包装关键操作
- 监控数据自动记录到独立的 JSON 日志文件

**章节来源**
- [src/speech_to_speech/utils/model_monitor.py:1-472](file://src/speech_to_speech/utils/model_monitor.py#L1-L472)
- [src/speech_to_speech/baseHandler.py:54-56](file://src/speech_to_speech/baseHandler.py#L54-L56)
- [src/speech_to_speech/TTS/qwen3_tts_handler.py:575-576](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L575-L576)

## 故障排除指南
- 依赖缺失：
  - Qwen3-TTS 非 macOS：安装 faster-qwen3-tts；macOS：安装 mlx-audio。
  - Kokoro：Apple Silicon 需要额外依赖（misaki/spacy/phonemizer/espeakng_loader/num2words）；其他平台需 kokoro>=0.9.2 与 soundfile，系统 espeak-ng。
  - ChatTTS：确保 torch 可用；MPS 场景注意同步与缓存清理。
  - OmniVoice：确保 omnivoice 与匹配 PyTorch 构建（CUDA/MPS/XPU）。
  - **新增** Phonon：安装 `speech-to-speech[phonon]` 或单独安装 `ptts==0.4.0`；确保 CPU 环境可用。
- 配置冲突：
  - Qwen3-TTS：ref_audio 与 ref_spk/ref_rvq 互斥；ref_rvq 需要 ref_spk 与 ref_text；gguf_talker_path 与 gguf_codec_path 必须成对。
  - OmniVoice：ref_audio 与 voice_clone_prompt 互斥；instruct 不能与克隆配置混用。
  - **新增** Phonon：model_name 必须提供且非空；language 必须是 en/fr/de/es/pt/none 之一；blocksize 和 num_threads 必须为正数。
- 采样率与格式：
  - 所有 handler 最终输出 16kHz int16；若上游返回不同采样率，会进行重采样。
  - **新增** Phonon：使用 soxr HQ 质量重采样，确保高质量音频转换。
- 语言与音色：
  - Kokoro：不支持的语言回退到英语；会话结束时恢复初始 voice/lang_code。
  - Qwen3-TTS：Base 模型需要声音克隆参考；CustomVoice 需要 speaker。
  - **新增** Phonon：voice 名称必须在 checkpoint 或 catalog 中；catalog 不可用时只使用 checkpoint 音色。
- 性能问题：
  - **新增** 监控日志：检查 `model_metrics.log` 文件获取详细的性能数据和资源使用情况。
  - **新增** Phonon 线程数：调整 `--phonon_tts_num_threads` 参数优化 CPU 使用效率。

**章节来源**
- [src/speech_to_speech/TTS/qwen3_tts_handler.py:294-328](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L294-L328)
- [src/speech_to_speech/TTS/kokoro_handler.py:170-195](file://src/speech_to_speech/TTS/kokoro_handler.py#L170-L195)
- [src/speech_to_speech/TTS/chatTTS_handler.py:41-54](file://src/speech_to_speech/TTS/chatTTS_handler.py#L41-L54)
- [src/speech_to_speech/TTS/omnivoice_handler.py:48-64](file://src/speech_to_speech/TTS/omnivoice_handler.py#L48-L64)
- [src/speech_to_speech/TTS/phonon_tts_handler.py:43-55](file://src/speech_to_speech/TTS/phonon_tts_handler.py#L43-L55)
- [src/speech_to_speech/TTS/phonon_tts_handler.py:81-98](file://src/speech_to_speech/TTS/phonon_tts_handler.py#L81-L98)

## 结论
该 TTS 子系统通过统一 handler 接口整合了多种高质量语音合成引擎，兼顾低延迟流式输出、多语言与声音克隆能力，并提供稳定的音频格式与采样率转换。针对不同平台与设备，提供了 MLX、GGML、原生库等多路径优化；配合 visemes 扩展，可进一步满足唇形同步需求。**新增的 Phonon 引擎**为 CPU 环境提供了高性能流式语音合成选项，而**统一的模型监控功能**则为所有 TTS handler 提供了全面的性能追踪和资源使用情况监控。在生产环境中，建议依据设备与延迟目标选择合适的后端与量化/精度配置，并结合语言与音色策略以获得最佳体验。

## 附录：集成示例与参数速查
- 运行模式与后端选择：参见 README 中的 --tts 选项与各引擎主参数前缀。
- 典型命令：
  - ChatTTS：--tts chatTTS，--chat_tts_device cuda，--chat_tts_stream true，--chat_tts_chunk_size 512。
  - Kokoro：--tts kokoro，--kokoro_device auto，--kokoro_voice bm_fable，--kokoro_lang_code b。
  - Qwen3-TTS：--tts qwen3，--qwen3_tts_model_name ...，--qwen3_tts_backend ggml，--qwen3_tts_speaker Aiden，--qwen3_tts_language auto，--qwen3_tts_non_streaming_mode True。
  - OmniVoice：--tts omnivoice，--omnivoice_model_name k2-fsa/OmniVoice，--omnivoice_device cuda，--omnivoice_dtype float16，--omnivoice_ref_audio ...，--omnivoice_ref_text ...。
  - **新增** Phonon：--tts phonon，--phonon_tts_model_name gradium/phonon-31m-en，--phonon_tts_voice voice-name，--phonon_tts_language en，--phonon_tts_blocksize 512，--phonon_tts_num_threads 4。

**章节来源**
- [src/speech_to_speech/TTS/README.md:31-394](file://src/speech_to_speech/TTS/README.md#L31-L394)
- [src/speech_to_speech/TTS/phonon_tts_handler.py:26-236](file://src/speech_to_speech/TTS/phonon_tts_handler.py#L26-L236)
- [src/speech_to_speech/arguments_classes/phonon_tts_arguments.py:5-42](file://src/speech_to_speech/arguments_classes/phonon_tts_arguments.py#L5-L42)