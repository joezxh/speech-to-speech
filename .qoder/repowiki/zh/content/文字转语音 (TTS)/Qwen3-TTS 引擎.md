# Qwen3-TTS 引擎

<cite>
**本文引用的文件**   
- [qwen3_tts_handler.py](file://src/speech_to_speech/TTS/qwen3_tts_handler.py)
- [qwen3_tts_arguments.py](file://src/speech_to_speech/arguments_classes/qwen3_tts_arguments.py)
- [benchmark_tts.py](file://scripts/benchmark_tts.py)
- [s2s_pipeline.py](file://src/speech_to_speech/s2s_pipeline.py)
- [edge-box-feasibility.md](file://docs/hardware/edge-box-feasibility.md)
- [install_smoke.py](file://tests/install_smoke.py)
- [useBubbles.ts](file://console/frontend/src/features/voice/useBubbles.ts)
- [playback-capture.ts](file://console/frontend/src/features/voice/audio/playback-capture.ts)
- [voice.ts](file://console/frontend/src/stores/voice.ts)
- [voice_precompute.py](file://console/backend/app/services/voice_precompute.py)
</cite>

## 更新摘要
**变更内容**   
- 新增 WebRTC 音频播放捕获功能，通过 `captureStream` API 实现助手侧录音
- 增强气泡生命周期管理，使用 `useBubbles.ts` 实现响应式气泡状态管理
- 集成新的语音存储架构，支持更完善的会话状态管理
- 添加声音预计算功能，优化音色处理流程
- 改进音频处理管道，提升整体性能和稳定性

## 目录
1. [简介](#简介)
2. [项目结构](#项目结构)
3. [核心组件](#核心组件)
4. [架构总览](#架构总览)
5. [详细组件分析](#详细组件分析)
6. [依赖关系分析](#依赖关系分析)
7. [性能与延迟优化](#性能与延迟优化)
8. [配置参数与声音选择](#配置参数与声音选择)
9. [多语言支持与音质调优](#多语言支持与音质调优)
10. [WebRTC 音频捕获与气泡管理](#webrtc-音频捕获与气泡管理)
11. [声音预计算与处理管道](#声音预计算与处理管道)
12. [部署建议与资源使用](#部署建议与资源使用)
13. [基准测试方法](#基准测试方法)
14. [故障排查指南](#故障排查指南)
15. [结论](#结论)

## 简介
Qwen3-TTS 是 speech-to-speech 管线中的文本转语音后端，封装了 Qwen3-TTS 模型的推理流程。该实现根据运行平台自动选择后端：在 Apple Silicon 上使用 mlx-audio，在其他平台上使用 faster-qwen3-tts（支持 ggml 或 torch 后端）。它同时支持三种模型类型：声音克隆、自定义音色和声音设计，并提供流式音频输出、首帧延迟统计、实时因子评估、会话级声音覆盖、语言自动检测与对齐等能力。

**更新** 新增了 WebRTC 音频捕获、气泡生命周期管理和声音预计算功能，增强了前端交互体验和后端处理能力。

## 项目结构
Qwen3-TTS 相关代码主要分布在以下位置：
- TTS 处理器实现：`src/speech_to_speech/TTS/qwen3_tts_handler.py`
- 处理器参数定义：`src/speech_to_speech/arguments_classes/qwen3_tts_arguments.py`
- TTS 基准脚本：`scripts/benchmark_tts.py`
- 运行时管线集成与语言集合注册：`src/speech_to_speech/s2s_pipeline.py`
- 边缘设备可行性与性能参考：`docs/hardware/edge-box-feasibility.md`
- 安装冒烟测试与默认值校验：`tests/install_smoke.py`
- **新增** 气泡生命周期管理：`console/frontend/src/features/voice/useBubbles.ts`
- **新增** WebRTC 音频捕获：`console/frontend/src/features/voice/audio/playback-capture.ts`
- **新增** 语音存储架构：`console/frontend/src/stores/voice.ts`
- **新增** 声音预计算服务：`console/backend/app/services/voice_precompute.py`

```mermaid
graph TB
subgraph "TTS 层"
QTH["Qwen3TTSHandler<br/>qwen3_tts_handler.py"]
QArgs["Qwen3TTSHandlerArguments<br/>qwen3_tts_arguments.py"]
end
subgraph "前端交互层"
Bubbles["useBubbles.ts<br/>气泡生命周期管理"]
Capture["playback-capture.ts<br/>WebRTC 音频捕获"]
VoiceStore["voice.ts<br/>语音存储架构"]
end
subgraph "后端服务层"
Precompute["voice_precompute.py<br/>声音预计算"]
end
subgraph "管线层"
S2S["s2s_pipeline.py<br/>构建 STT→LLM→TTS 链"]
end
subgraph "评测与文档"
Bench["benchmark_tts.py<br/>TTFC/RTF/耗时统计"]
Edge["edge-box-feasibility.md<br/>边缘设备可行性"]
Smoke["install_smoke.py<br/>默认参数与依赖检查"]
end
QArgs --> QTH
S2S --> QTH
Bench --> QTH
Smoke --> QTH
Edge -.-> QTH
Bubbles --> VoiceStore
Capture --> VoiceStore
Precompute --> QTH
```

**图表来源**
- [qwen3_tts_handler.py:96-108](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L96-L108)
- [useBubbles.ts:1-259](file://console/frontend/src/features/voice/useBubbles.ts#L1-L259)
- [playback-capture.ts:1-255](file://console/frontend/src/features/voice/audio/playback-capture.ts#L1-L255)
- [voice.ts:81-274](file://console/frontend/src/stores/voice.ts#L81-L274)
- [voice_precompute.py:1-140](file://console/backend/app/services/voice_precompute.py#L1-L140)

**章节来源**
- [qwen3_tts_handler.py:1-1085](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L1-L1085)
- [qwen3_tts_arguments.py:1-135](file://src/speech_to_speech/arguments_classes/qwen3_tts_arguments.py#L1-L135)
- [s2s_pipeline.py:548-574](file://src/speech_to_speech/s2s_pipeline.py#L548-L574)
- [benchmark_tts.py:1-416](file://scripts/benchmark_tts.py#L1-L416)
- [edge-box-feasibility.md:1-509](file://docs/hardware/edge-box-feasibility.md#L1-L509)
- [install_smoke.py:126-145](file://tests/install_smoke.py#L126-L145)
- [useBubbles.ts:1-259](file://console/frontend/src/features/voice/useBubbles.ts#L1-L259)
- [playback-capture.ts:1-255](file://console/frontend/src/features/voice/audio/playback-capture.ts#L1-L255)
- [voice.ts:1-274](file://console/frontend/src/stores/voice.ts#L1-L274)
- [voice_precompute.py:1-140](file://console/backend/app/services/voice_precompute.py#L1-L140)

## 核心组件
Qwen3-TTS 的核心是一个处理器类，负责：
- 初始化并加载模型（mlx-audio 或 faster-qwen3-tts）
- 选择声音克隆、自定义音色或声音设计模式
- 合并待合成文本、估计最大 token 数
- 流式生成音频块、统一采样率、量化为 int16
- 记录 TTFA、RTF、音频时长等指标
- 处理会话结束状态重置与资源清理

该类继承自通用处理器基类，并通过 `process` 方法接入 pipeline 的输入输出队列。

**更新** 新增了前端气泡管理、WebRTC 音频捕获和声音预计算等辅助组件，提供更完整的用户体验。

**章节来源**
- [qwen3_tts_handler.py:96-108](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L96-L108)
- [qwen3_tts_handler.py:825-910](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L825-L910)
- [useBubbles.ts:47-259](file://console/frontend/src/features/voice/useBubbles.ts#L47-L259)
- [playback-capture.ts:125-255](file://console/frontend/src/features/voice/audio/playback-capture.ts#L125-L255)
- [voice.ts:81-274](file://console/frontend/src/stores/voice.ts#L81-L274)

## 架构总览
Qwen3-TTS 在整体 speech-to-speech 管线中位于 LLM 之后，作为最终音频输出阶段。其关键交互如下：
- 上游 LLM 输出文本片段被聚合后送入 TTS
- TTS 根据模型类型决定调用声音克隆、自定义音色或声音设计接口
- 音频以固定 blocksize 分块输出到下游（可选唇形同步模块）
- 运行时可注入会话级声音覆盖，例如通过 OpenAI Realtime Response 的 voice 字段

**更新** 新增了前端交互层，包括气泡生命周期管理和 WebRTC 音频捕获，以及后端的声音预计算服务。

```mermaid
sequenceDiagram
participant LLM as "LLM 输出"
participant Pipeline as "s2s_pipeline.py"
participant TTS as "Qwen3TTSHandler"
participant Frontend as "前端交互层"
participant Backend as "声音预计算"
participant Backend as "mlx-audio / faster-qwen3-tts"
participant Downstream as "下游播放/STV"
LLM-->>Pipeline : "文本片段"
Pipeline->>TTS : "TTSInput(文本, 语言, 会话配置)"
TTS->>TTS : "合并文本/估计 max_new_tokens"
Frontend->>Backend : "触发声音预计算"
Backend-->>Frontend : "预计算进度"
TTS->>Backend : "generate_voice_clone/custom_voice/voice_design"
Backend-->>TTS : "音频流"
TTS->>TTS : "重采样/量化/切块"
TTS-->>Downstream : "int16 PCM 块"
Frontend->>Frontend : "WebRTC 音频捕获"
Frontend->>Frontend : "气泡生命周期管理"
```

**图表来源**
- [s2s_pipeline.py:548-574](file://src/speech_to_speech/s2s_pipeline.py#L548-L574)
- [qwen3_tts_handler.py:825-910](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L825-L910)
- [qwen3_tts_handler.py:957-1053](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L957-L1053)
- [useBubbles.ts:47-259](file://console/frontend/src/features/voice/useBubbles.ts#L47-L259)
- [playback-capture.ts:125-255](file://console/frontend/src/features/voice/audio/playback-capture.ts#L125-L255)
- [voice_precompute.py:57-102](file://console/backend/app/services/voice_precompute.py#L57-L102)

## 详细组件分析

### Qwen3TTSHandler 类
该类实现了完整的 Qwen3-TTS 推理生命周期：
- `setup`：解析参数、选择后端、加载模型、预热
- `_setup_faster`：faster-qwen3-tts 后端初始化（ggml/torch）
- `_setup_mlx`：Apple Silicon MLX 后端初始化
- `_model_type`：推断模型类型（base/custom_voice/voice_design）
- `_estimate_max_new_tokens`：按词数、字符数、CJK 字符数和标点停顿估算音频长度，再映射为 codec token 上限
- `_stream`：公共流式循环，记录 TTFA、RTF，输出固定 blocksize 的 int16 音频
- `_process_voice_clone/_process_custom_voice/_process_voice_design`：三类生成路径
- `on_session_end/cleanup`：会话状态恢复与资源释放

```mermaid
classDiagram
class Qwen3TTSHandler {
+setup(...)
+process(tts_input) Iterator[TTSOut]
-_setup_faster(model_name, dtype, attn_implementation, backend)
-_setup_mlx(model_name)
-_model_type() str
-_estimate_max_new_tokens(text) int
-_stream(gen, label) Iterator[bytes|np.ndarray]
-_process_voice_clone(text, language) Iterator[bytes|np.ndarray]
-_process_custom_voice(text, language) Iterator[bytes|np.ndarray]
-_process_voice_design(text, language) Iterator[bytes|np.ndarray]
+on_session_end() void
+cleanup() void
}
```

**图表来源**
- [qwen3_tts_handler.py:96-108](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L96-L108)
- [qwen3_tts_handler.py:110-220](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L110-L220)
- [qwen3_tts_handler.py:222-270](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L222-L270)
- [qwen3_tts_handler.py:583-667](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L583-L667)
- [qwen3_tts_handler.py:704-762](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L704-L762)
- [qwen3_tts_handler.py:957-1053](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L957-L1053)
- [qwen3_tts_handler.py:1055-1085](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L1055-L1085)

**章节来源**
- [qwen3_tts_handler.py:96-1085](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L96-L1085)

### 后端选择与模型加载
- Apple Silicon：使用 mlx-audio，自动选择 MLX 模型名称，支持 bf16/4bit/6bit/8bit 量化后缀
- 非 Apple Silicon：使用 faster-qwen3-tts，支持 ggml 或 torch 后端；ggml 后端可指定 GGUF talker/codec 路径与量化格式

```mermaid
flowchart TD
Start(["启动 Qwen3TTSHandler"]) --> CheckPlatform{"是否 Apple Silicon?"}
CheckPlatform --> |是| UseMLX["使用 mlx-audio<br/>自动映射模型名与量化后缀"]
CheckPlatform --> |否| UseFaster["使用 faster-qwen3-tts<br/>ggml 或 torch 后端"]
UseMLX --> LoadModel["加载 MLX 模型"]
UseFaster --> LoadGGML{"后端是否为 ggml?"}
LoadGGML --> |是| LoadGGUF["加载 GGUF talker/codec<br/>应用量化设置"]
LoadGGML --> |否| LoadTorch["加载 torch 模型"]
LoadModel --> Warmup["预热与首次合成"]
LoadGGUF --> Warmup
LoadTorch --> Warmup
```

**图表来源**
- [qwen3_tts_handler.py:168-206](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L168-L206)
- [qwen3_tts_handler.py:222-270](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L222-L270)
- [qwen3_tts_handler.py:329-379](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L329-L379)

**章节来源**
- [qwen3_tts_handler.py:168-206](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L168-L206)
- [qwen3_tts_handler.py:222-270](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L222-L270)
- [qwen3_tts_handler.py:329-379](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L329-L379)

### 声音克隆、自定义音色与声音设计
- 声音克隆：需要参考音频或缓存的 speaker embedding/acoustic codes，支持 xvec_only 模式（非 MLX）
- 自定义音色：需要 speaker 名称，可从模型支持的说话人列表中选择第一个
- 声音设计：通过 instruct 文本描述声音风格

```mermaid
flowchart TD
Input["输入文本与语言"] --> ModelType{"模型类型"}
ModelType --> |Base+参考| VoiceClone["声音克隆<br/>ref_audio/ref_spk/ref_rvq"]
ModelType --> |CustomVoice| CustomVoice["自定义音色<br/>speaker/instruct"]
ModelType --> |VoiceDesign| VoiceDesign["声音设计<br/>instruct/language"]
VoiceClone --> Stream["流式生成音频"]
CustomVoice --> Stream
VoiceDesign --> Stream
```

**图表来源**
- [qwen3_tts_handler.py:583-667](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L583-L667)
- [qwen3_tts_handler.py:957-1053](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L957-L1053)

**章节来源**
- [qwen3_tts_handler.py:583-667](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L583-L667)
- [qwen3_tts_handler.py:957-1053](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L957-L1053)

### 流式输出与延迟统计
- TTFA（Time To First Audio）：从开始合成到首个音频块的时间
- RTF（Real-Time Factor）：音频时长除以生成时间
- 音频块大小：blocksize 控制输出粒度，默认 512 样本
- 采样率归一化：统一到 PIPELINE_SR（16kHz），必要时进行 resample_poly 重采样

```mermaid
flowchart TD
Gen["模型生成器"] --> Prepare["_prepare_audio_chunk"]
Prepare --> Resample["_resample_to_pipeline_sr"]
Resample --> Quantize["_to_int16"]
Quantize --> Chunk["按 blocksize 切块"]
Chunk --> Yield["yield 音频块"]
Yield --> Metrics["记录 TTFA/RTF/时长"]
```

**图表来源**
- [qwen3_tts_handler.py:683-762](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L683-L762)

**章节来源**
- [qwen3_tts_handler.py:683-762](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L683-L762)

## 依赖关系分析
Qwen3-TTS 依赖的外部库与运行时环境：
- Apple Silicon：mlx-audio、mlx.core
- 非 Apple Silicon：torch、faster-qwen3-tts（可选 ggml 后端）
- 音频处理：numpy、scipy.signal.resample_poly、soundfile（用于参考音频预处理）
- 日志与监控：rich.console、pipeline.monitor.trace

**更新** 新增了前端依赖（Vue.js、Pinia）和后端依赖（asyncio、wave）来支持新的功能。

```mermaid
graph TB
QTH["Qwen3TTSHandler"] --> Torch["torch"]
QTH --> Faster["faster-qwen3-tts"]
QTH --> MLX["mlx-audio"]
QTH --> Numpy["numpy"]
QTH --> Scipy["scipy.signal"]
QTH --> Soundfile["soundfile"]
Frontend["前端组件"] --> Vue["Vue.js"]
Frontend --> Pinia["Pinia"]
Backend["预计算服务"] --> Asyncio["asyncio"]
Backend --> Wave["wave"]
```

**图表来源**
- [qwen3_tts_handler.py:222-270](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L222-L270)
- [qwen3_tts_handler.py:475-512](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L475-L512)
- [useBubbles.ts:1-3](file://console/frontend/src/features/voice/useBubbles.ts#L1-L3)
- [voice.ts:1-3](file://console/frontend/src/stores/voice.ts#L1-L3)
- [voice_precompute.py:16-21](file://console/backend/app/services/voice_precompute.py#L16-L21)

**章节来源**
- [qwen3_tts_handler.py:222-270](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L222-L270)
- [qwen3_tts_handler.py:475-512](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L475-L512)
- [useBubbles.ts:1-3](file://console/frontend/src/features/voice/useBubbles.ts#L1-L3)
- [voice.ts:1-3](file://console/frontend/src/stores/voice.ts#L1-L3)
- [voice_precompute.py:16-21](file://console/backend/app/services/voice_precompute.py#L16-L21)

## 性能与延迟优化
- 流式 chunk size：faster-qwen3-tts 默认 8，mlx-audio 默认 4；可通过 `streaming_chunk_size` 调整
- 预填充策略：`non_streaming_mode=True` 会在 faster-qwen3-tts 上预填完整文本，减少解码抖动
- CUDA Graph 稳定性：`parity_mode=True` 禁用 CUDA-graph 流式路径以提升稳定性
- Token 预算估算：基于词数、字符数、CJK 字符数和标点停顿估算音频时长，乘以安全系数得到 max_new_tokens
- 首帧延迟：TTFA 通过 perf_counter 记录，并在活跃 turn 延迟追踪器中上报
- 实时因子：RTF = 音频时长 / 生成时间，用于衡量是否达到实时

**更新** 新增了 WebRTC 音频捕获的性能考虑，包括浏览器兼容性检查和降级策略。

```mermaid
flowchart TD
Text["输入文本"] --> Estimate["_estimate_max_new_tokens"]
Estimate --> Tokens["计算 max_new_tokens"]
Tokens --> Stream["流式生成"]
Stream --> TTFA["记录 TTFA"]
Stream --> RTF["计算 RTF"]
RTF --> Optimize{"RTF > 1?"}
Optimize --> |是| Tune["调整 chunk size/quantization/backend"]
Optimize --> |否| Done["满足实时要求"]
```

**图表来源**
- [qwen3_tts_handler.py:624-667](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L624-L667)
- [qwen3_tts_handler.py:704-762](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L704-L762)

**章节来源**
- [qwen3_tts_handler.py:624-667](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L624-L667)
- [qwen3_tts_handler.py:704-762](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L704-L762)

## 配置参数与声音选择
Qwen3-TTS 的配置参数集中在 `Qwen3TTSHandlerArguments` 数据类中，涵盖模型名称、设备、数据类型、注意力实现、后端选择、GGUF 量化、参考音频/嵌入、说话人、指令、xvec_only、parity_mode、non_streaming_mode、MLX 量化、语言、流式 chunk size、max_new_tokens、blocksize 等。

关键参数说明：
- `qwen3_tts_model_name`：HuggingFace Hub ID 或本地路径；Apple Silicon 下自动映射到 mlx-community
- `qwen3_tts_device`：torch 后端设备，默认 cuda
- `qwen3_tts_dtype`：auto/float16/bfloat16/float32
- `qwen3_tts_attn_implementation`：eager/flash_attention_2/sdpa
- `qwen3_tts_backend`：ggml/torch（非 macOS）
- `qwen3_tts_ggml_quantization`：BF16/Q8_0/Q4_K_M/F32
- `qwen3_tts_ref_audio/ref_spk/ref_rvq/ref_text`：声音克隆参考
- `qwen3_tts_speaker`：CustomVoice 说话人，默认 Aiden
- `qwen3_tts_instruct`：VoiceDesign 指令
- `qwen3_tts_xvec_only`：仅使用 x-vector 的声音克隆模式
- `qwen3_tts_parity_mode`：禁用 CUDA-graph 流式路径
- `qwen3_tts_non_streaming_mode`：预填完整文本
- `qwen3_tts_mlx_quantization`：bf16/4bit/6bit/8bit
- `qwen3_tts_language`：目标语言，默认 auto
- `qwen3_tts_streaming_chunk_size`：流式 chunk 大小
- `qwen3_tts_max_new_tokens`：最大 token 上限，默认 1536
- `qwen3_tts_blocksize`：音频块大小，默认 512

**章节来源**
- [qwen3_tts_arguments.py:6-135](file://src/speech_to_speech/arguments_classes/qwen3_tts_arguments.py#L6-L135)
- [qwen3_tts_handler.py:110-220](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L110-L220)

## 多语言支持与音质调优
- 语言别名映射：中文、英文、日文、韩文、德文、法文、俄文、葡萄牙文、西班牙文、意大利文等
- 自动语言检测：当 selected_language 为 auto 且 detect_llm_output_language 启用时，根据输入语言代码选择目标语言
- 会话级声音覆盖：通过 RuntimeConfig 或 RealtimeResponseCreateParams 的 voice 字段覆盖当前会话声音
- 音质调优：
  - 降低 streaming_chunk_size 可减少首帧延迟但可能增加调度开销
  - 使用更高分辨率的 GGUF 量化（如 BF16）提升音质但增加显存占用
  - 使用 xvec_only 模式改善起始静音和语言切换
  - 调整 non_streaming_mode 平衡预填延迟与解码抖动

```mermaid
flowchart TD
LangCode["输入语言代码"] --> Normalize["_normalize_language"]
Normalize --> Selected{"selected_language == 'auto'?"}
Selected --> |是| Detect["检测 LLM 输出语言"]
Selected --> |否| UseConfig["使用配置语言"]
Detect --> Map["映射到 QWEN3_LANGUAGE_ALIASES"]
UseConfig --> Map
Map --> Synthesize["执行合成"]
```

**图表来源**
- [qwen3_tts_handler.py:388-408](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L388-L408)
- [s2s_pipeline.py:691-692](file://src/speech_to_speech/s2s_pipeline.py#L691-L692)

**章节来源**
- [qwen3_tts_handler.py:388-408](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L388-L408)
- [s2s_pipeline.py:691-692](file://src/speech_to_speech/s2s_pipeline.py#L691-L692)

## WebRTC 音频捕获与气泡管理

### WebRTC 音频捕获系统
新增了基于 WebRTC 的音频播放捕获功能，通过浏览器的 `captureStream` API 实现对助手侧音频的录制。该系统具有以下特点：

- **浏览器兼容性**：自动检测 `captureStream`、`MediaRecorder` 和音频解码器支持情况
- **降级策略**：在不支持的浏览器环境中优雅降级，不影响核心功能
- **音频处理**：将捕获的音频转换为单声道 PCM16 格式，采样率统一为 24kHz
- **容器格式**：Chrome/Edge 使用 webm，Firefox 使用 ogg，其他浏览器使用默认格式

```mermaid
flowchart TD
AudioElement["HTMLAudioElement"] --> CaptureStream["captureStream()"]
CaptureStream --> MediaRecorder["MediaRecorder"]
MediaRecorder --> Chunks["音频数据块"]
Chunks --> Decode["音频解码"]
Decode --> Downmix["多声道混音"]
Downmix --> Resample["线性插值重采样"]
Resample --> PCM16["PCM16 转换"]
PCM16 --> WAV["WAV 封装"]
```

**图表来源**
- [playback-capture.ts:94-101](file://console/frontend/src/features/voice/audio/playback-capture.ts#L94-L101)
- [playback-capture.ts:125-255](file://console/frontend/src/features/voice/audio/playback-capture.ts#L125-L255)

### 气泡生命周期管理系统
使用 `useBubbles.ts` 实现了响应式的气泡生命周期管理，替代了原有的命令式 DOM 操作：

- **单一活动气泡**：每个用户消息只有一个活动气泡，增量更新在原位进行
- **智能过期机制**：每条气泡都有独立的到期时间，持续更新会延长显示时间
- **定时器优化**：使用单个定时器按栈序清理过期气泡，避免内存泄漏
- **状态管理**：支持监听、发送、转写等多种气泡状态

```mermaid
stateDiagram-v2
[*] --> 空闲
空闲 --> 监听 : userTurnStarted
监听 --> 发送 : userTurnStopped
发送 --> 转写 : userTranscript
转写 --> 助手回复 : assistantActivity
助手回复 --> 工具调用 : toolCall
工具调用 --> 助手回复 : responseFinished
监听 --> 助手回复 : assistantActivity
发送 --> 助手回复 : assistantActivity
```

**图表来源**
- [useBubbles.ts:47-259](file://console/frontend/src/features/voice/useBubbles.ts#L47-L259)

### 语音存储架构
新的 `voice.ts` store 提供了完整的会话状态管理：

- **状态持久化**：用户设置存储在 localStorage，刷新页面后保持配置
- **事件驱动**：基于 TranscriptReducer 处理各种语音事件
- **音频 URL 管理**：自动管理 Blob URL 的创建和释放，防止内存泄漏
- **历史记录**：维护对话历史，支持未读标记和历史记录面板

**章节来源**
- [playback-capture.ts:1-255](file://console/frontend/src/features/voice/audio/playback-capture.ts#L1-L255)
- [useBubbles.ts:1-259](file://console/frontend/src/features/voice/useBubbles.ts#L1-L259)
- [voice.ts:1-274](file://console/frontend/src/stores/voice.ts#L1-L274)

## 声音预计算与处理管道

### 声音预计算服务
新增了独立的 CPU-only 子进程来处理声音预计算任务，避免占用 GPU 资源：

- **并发控制**：通过信号量限制同时运行的预计算任务数量
- **进度跟踪**：实时报告预计算进度，支持超时和错误处理
- **文件格式验证**：验证输入音频文件的格式和时长要求
- **错误处理**：提供详细的错误代码和失败原因

```mermaid
flowchart TD
Input["参考音频文件"] --> Validate["文件验证"]
Validate --> Load["加载音频"]
Load --> Extract["提取特征"]
Extract --> Generate["生成 spk/rvq 文件"]
Generate --> Output["输出到 ref_cache_dir"]
Output --> Complete["预计算完成"]
```

**图表来源**
- [voice_precompute.py:57-102](file://console/backend/app/services/voice_precompute.py#L57-L102)

### 处理管道优化
- **CPU 隔离**：预计算任务在独立进程中运行，不占用主进程的 GPU 资源
- **异步处理**：使用 asyncio 实现非阻塞的预计算任务
- **资源管理**：自动管理子进程的生命周期和资源释放
- **进度反馈**：通过标准输出流实时传递预计算进度信息

**章节来源**
- [voice_precompute.py:1-140](file://console/backend/app/services/voice_precompute.py#L1-L140)

## 部署建议与资源使用
- Apple Silicon：优先使用 mlx-audio，默认 6bit 量化可在内存与音质间取得平衡；如需更高音质可选择 bf16
- CUDA/GPU：推荐使用 faster-qwen3-tts 的 ggml 后端，配合 BF16 或 Q8_0 量化；若需兼容性可使用 torch 后端
- 边缘设备：参考 edge-box-feasibility.md 中对不同硬件的可行性评估，注意 RTF 与 TTFA 的实际表现
- 资源清理：on_session_end 恢复初始声音与参考音频，cleanup 释放模型与缓存

**更新** 新增了前端部署注意事项：
- WebRTC 音频捕获需要 HTTPS 环境支持
- 不同浏览器的兼容性差异需要考虑
- 气泡管理需要足够的内存来维持响应式状态

**章节来源**
- [qwen3_tts_handler.py:1055-1085](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L1055-L1085)
- [edge-box-feasibility.md:1-509](file://docs/hardware/edge-box-feasibility.md#L1-L509)
- [playback-capture.ts:1-15](file://console/frontend/src/features/voice/audio/playback-capture.ts#L1-L15)

## 基准测试方法
benchmark_tts.py 提供了统一的 TTS 基准框架，支持 kokoro、qwen3、pocket_tts、kitten、chatTTS、facebookMMS、supertonic 等后端对比。对 qwen3 后端，默认使用 Base 模型与参考音频，并可传入 MLX 量化变体进行横向比较。

关键指标：
- warmup_time：初始化与预热时间
- inference_times：每次合成的耗时
- time_to_first_chunk：首块到达时间（TTFC）
- audio_durations：合成音频时长
- avg_rtf：平均实时因子

```mermaid
flowchart TD
Args["命令行参数"] --> BuildTargets["构建测试目标"]
BuildTargets --> RunBenchmark["逐个 handler 执行"]
RunBenchmark --> CollectMetrics["收集 TTFC/RTF/时长"]
CollectMetrics --> PrintResults["打印结果与排序"]
PrintResults --> SaveJSON["保存 JSON 报告"]
```

**图表来源**
- [benchmark_tts.py:91-229](file://scripts/benchmark_tts.py#L91-L229)
- [benchmark_tts.py:254-340](file://scripts/benchmark_tts.py#L254-L340)
- [benchmark_tts.py:342-416](file://scripts/benchmark_tts.py#L342-L416)

**章节来源**
- [benchmark_tts.py:1-416](file://scripts/benchmark_tts.py#L1-L416)

## 故障排查指南
常见问题与解决思路：
- GGUF 路径不匹配：确保 gguf_talker_path 与 gguf_codec_path 成对提供，且后端为 ggml
- 参考音频冲突：ref_audio 与 ref_spk/ref_rvq 互斥；ref_rvq 必须搭配 ref_spk 与 ref_text
- MLX 量化不支持：仅支持 bf16/4bit/6bit/8bit，其他值会抛出 ValueError
- 声音克隆失败：Base 模型需要提供参考音频或缓存引用；CustomVoice 需要 speaker；VoiceDesign 需要 instruct
- 首帧延迟过高：尝试减小 streaming_chunk_size、启用 non_streaming_mode、检查 GPU/CUDA 驱动与算子支持
- 实时因子大于 1：考虑降低量化精度、更换后端、或使用更小模型（如 0.6B）

**更新** 新增了前端相关的故障排查：
- WebRTC 音频捕获失败：检查浏览器是否支持 captureStream 和 MediaRecorder
- 气泡状态异常：确认 useBubbles 的状态机是否正确初始化
- 语音存储问题：检查 localStorage 权限和存储空间
- 预计算超时：调整 voice_precompute_timeout_s 配置参数

**章节来源**
- [qwen3_tts_handler.py:294-328](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L294-L328)
- [qwen3_tts_handler.py:329-341](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L329-L341)
- [qwen3_tts_handler.py:678-681](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L678-L681)
- [qwen3_tts_handler.py:999-1002](file://src/speech_to_speech/TTS/qwen3_tts_handler.py#L999-L1002)
- [playback-capture.ts:145-153](file://console/frontend/src/features/voice/audio/playback-capture.ts#L145-L153)
- [voice_precompute.py:88-100](file://console/backend/app/services/voice_precompute.py#L88-L100)

## 结论
Qwen3-TTS 在 speech-to-speech 管线中提供了灵活、可扩展的文本转语音能力。通过平台感知的后端选择、丰富的声音模式、精细的语言映射与流式优化，它能够在多种硬件环境下实现低延迟、高质量的语音合成。结合 benchmark_tts.py 与 edge-box-feasibility.md，用户可以系统性地评估性能、调优参数并制定部署策略。

**更新** 新增的前端交互层和后端预计算服务进一步增强了系统的完整性和用户体验。WebRTC 音频捕获功能提供了更好的调试和分析能力，气泡生命周期管理提升了界面的响应性，而声音预计算则优化了音色处理的性能。这些改进使得 Qwen3-TTS 不仅是一个强大的 TTS 引擎，更是一个完整的语音交互解决方案。