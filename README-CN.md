> 🌐 Language / 语言：**中文版** · [English](./README.md)

<div align="center">
  <div>&nbsp;</div>
  <img src="https://raw.githubusercontent.com/huggingface/speech-to-speech/main/logo.png" width="600"/>

# Speech To Speech：用开源模型构建语音智能体

<p>
  <a href="https://trendshift.io/repositories/20645"><img src="https://img.shields.io/badge/GitHub%20Trending-%231%20Repository%20of%20the%20Day-7B2CBF?logo=github&amp;logoColor=white&amp;style=for-the-badge" alt="GitHub Trending: #1 Repository of the Day"></a>
</p>

[![PyPI](https://img.shields.io/pypi/v/speech-to-speech)](https://pypi.org/project/speech-to-speech/)
[![Python](https://img.shields.io/pypi/pyversions/speech-to-speech)](https://pypi.org/project/speech-to-speech/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](./LICENSE)

</div>

一个低延迟、完全模块化的语音智能体流水线：**VAD -> STT -> LLM -> TTS**，通过 **WebSocket 和 WebRTC 上的核心 OpenAI Realtime GA 事件集**对外暴露。每个组件都可替换。LLM 插槽讲 OpenAI 兼容协议，因此你可以把它指向托管提供方、[HF Inference Providers](https://huggingface.co/inference-providers)，或你自己的硬件上的 vLLM 或 llama.cpp 服务器，构成一个完全本地、完全开放的栈。

该流水线在数千台 [Reachy Mini](https://huggingface.co/blog/reachy-mini) 机器人的对话后端上投入生产运行。

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="./docs/assets/endpoint-swap-dark.gif">
    <source media="(prefers-color-scheme: light)" srcset="./docs/assets/endpoint-swap-light.gif">
    <img src="./docs/assets/endpoint-swap-light.gif" alt="把 OpenAI Realtime 客户端端点从托管 OpenAI 切换到自托管的 speech-to-speech 服务器" width="640">
  </picture>
</p>

## 快速开始

```bash
pip install speech-to-speech
export OPENAI_API_KEY=...
speech-to-speech serve
```

这会在 `ws://localhost:8765/v1/realtime` 启动一个 OpenAI Realtime 兼容的服务器，使用 Parakeet TDT 做本地 STT、一个 OpenAI 兼容的 LLM，以及 Qwen3-TTS 做本地语音输出。

从第二个终端与它对话：

```bash
speech-to-speech talk --url ws://127.0.0.1:8765/v1/realtime
```

要在一个命令中同时启动服务器和打包的麦克风 / 扬声器客户端：

```bash
speech-to-speech local
```

想让 LLM 留在你自己的机器上？用 llama.cpp 提供 Gemma 4 服务：

```bash
llama-server -hf ggml-org/gemma-4-E4B-it-GGUF -np 2 -c 65536 -fa on --swa-full
```

然后把 OpenAI 兼容的 LLM 后端指向它：

```bash
speech-to-speech serve \
    --model_name "ggml-org/gemma-4-E4B-it-GGUF" \
    --responses_api_base_url "http://127.0.0.1:8080/v1" \
    --responses_api_api_key ""
```

使用已实现的核心 Realtime 事件集的客户端可以连接。官方 OpenAI Agents SDK 在两种现成传输上都经过测试；测试过的接口见 [Realtime API](#realtime-api)，提供方和本地服务器选项见 [LLM 后端](#llm-backends)。

## 目录

* [工作原理](#工作原理)
* [安装](#安装)
* [离线运行](#离线运行)
* [支持的组件](#支持的组件)
* [命令](#命令)
* [Realtime API](#realtime-api)
* [LLM 后端](#llm-backends)
* [多语言支持](#多语言支持)
* [OmniVoice](#omnivoice)
* [Pocket TTS](#pocket-tts)
* [CLI 参考](#cli-参考)
* [贡献](#贡献)
* [Star 历史](#star-历史)
* [引用](#引用)

## 工作原理

该流水线是一个四级组件的级联，每个组件运行在它自己的线程中，并通过队列连接：

1. **语音活动检测（VAD）**：[Silero VAD v5](https://github.com/snakers4/silero-vad) 检测语音边界和轮次切换。
2. **语音转文本（STT）**：转写用户的轮次，带可选的实时局部转写。
3. **语言模型（LLM）**：生成响应，流式输出文本和工具调用。
4. **文本转语音（TTS）**：合成音频并流式回传给客户端。

每个阶段都有多个可互换的后端，通过 CLI 标志选择。代码设计便于修改，重点关注通过 Transformers 和 Hugging Face Hub 可用的模型。

## 安装

需要 Python 3.10+。

```bash
pip install speech-to-speech
```

默认安装覆盖标准的实时路径：

- 用于 STT 的 Parakeet TDT
- 用于语言模型的 OpenAI 兼容 API
- 用于语音输出的 Qwen3-TTS，在非 macOS 平台上默认使用 GGML 后端，在 Apple Silicon 上使用 `mlx-audio`
- 本地音频和实时服务器模式

macOS 和非 macOS 的依赖通过 `pyproject.toml` 中的平台标记自动解析。

### Qwen3-TTS 的 CUDA 说明

在 Linux 上，Qwen3-TTS 的 GGML 后端来自 `faster-qwen3-tts[ggml]`。它在 PyPI 上的默认 `qwentts-cpp-python` wheel 针对 CUDA 12.8 和 `manylinux_2_39`（例如 Ubuntu 24.04）。如果你的 CUDA 运行时或 glibc 较旧，在安装 `speech-to-speech` 之前，从 Hugging Face wheelhouse 安装匹配的 wheel：

```bash
# CUDA 13.x
pip install "qwentts-cpp-python==0.3.1+cu130" \
  -f https://huggingface.co/datasets/andito/qwentts-cpp-python-wheels/tree/main/whl/cu130

# CUDA 12.4
pip install "qwentts-cpp-python==0.3.1+cu124" \
  -f https://huggingface.co/datasets/andito/qwentts-cpp-python-wheels/tree/main/whl/cu124

# 纯 CPU 回退
pip install "qwentts-cpp-python==0.3.1+cpu" \
  -f https://huggingface.co/datasets/andito/qwentts-cpp-python-wheels/tree/main/whl/cpu

pip install speech-to-speech
```

要使用之前的 CUDA-graphs 实现而非 GGML，传入 `--qwen3_tts_backend torch`。

### 可选组件

可选组件通过 pip extras 安装：

```bash
pip install "speech-to-speech[kokoro]"          # 非 macOS 上的 Kokoro-82M TTS
pip install "speech-to-speech[pocket]"          # Pocket TTS
pip install "speech-to-speech[chattts]"         # ChatTTS
pip install "speech-to-speech[omnivoice]"       # OmniVoice TTS（CUDA、Intel XPU 或 Apple Silicon）
pip install "speech-to-speech[faster-whisper]"  # Faster Whisper STT
pip install "speech-to-speech[whisper-mlx]"     # macOS 上的 Lightning Whisper MLX STT
pip install "speech-to-speech[paraformer]"      # 通过 FunASR 的 Paraformer STT
pip install "speech-to-speech[mlx-lm]"          # macOS 上用于视觉模型的 mlx-vlm 支持
```

已弃用的实现（包括 MeloTTS）位于 [`archive/`](./archive)，不再接入 CLI。

**关于 DeepFilterNet 的说明：** 用于 VAD 中可选音频增强的 DeepFilterNet 需要 `numpy<2`，并与需要 `numpy>=2` 的 Pocket TTS 冲突。只在你未使用 Pocket TTS 的环境中手动安装它。

### 从源码安装

```bash
git clone https://github.com/huggingface/speech-to-speech.git
cd speech-to-speech
uv sync
```

这以可编辑模式安装包，并使 `speech-to-speech` CLI 可用。

## 支持的组件

| 组件 | 后端 | 平台 | 安装 |
|---|---|---|---|
| VAD | [Silero VAD v5](https://github.com/snakers4/silero-vad) | 全部 | 内置 |
| STT | [Parakeet TDT](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)（默认） | 通过 nano-parakeet 的 CUDA / CPU，通过 MLX 的 Apple Silicon | 内置 |
| STT | [Whisper](https://huggingface.co/docs/transformers/en/model_doc/whisper)（通过 Transformers） | CUDA / CPU | 内置 |
| STT | [Faster Whisper](https://github.com/SYSTRAN/faster-whisper) | CUDA / CPU | `faster-whisper` |
| STT | [Lightning Whisper MLX](https://github.com/mustafaaljadery/lightning-whisper-mlx) | Apple Silicon | `whisper-mlx` |
| STT | [MLX Audio Whisper](https://github.com/huggingface/mlx-audio) | Apple Silicon | macOS 上内置 |
| STT | [Paraformer](https://github.com/modelscope/FunASR) | CUDA / CPU | `paraformer` |
| STT | OpenAI 兼容的 `/v1/audio/transcriptions` 端点 | 本地或远程 HTTP 服务器 | 内置 |
| LLM | OpenAI 兼容 API（`responses-api`、`chat-completions`） | 托管提供方或自托管服务器 | 内置 |
| LLM | [Transformers](https://huggingface.co/models?pipeline_tag=text-generation&sort=trending) | CUDA / CPU | 内置 |
| LLM | [mlx-lm](https://github.com/ml-explore/mlx-lm) | Apple Silicon | macOS 上内置 |
| TTS | [Qwen3-TTS](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)（默认） | Linux 上的 GGML / CUDA，macOS 上的 mlx-audio | 内置 |
| TTS | [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) | CUDA / CPU，Apple Silicon | 非 macOS 上为 `kokoro`；macOS 上为内置 |
| TTS | [Pocket TTS](https://github.com/kyutai-labs/pocket-tts) | CPU / CUDA | `pocket` |
| TTS | [ChatTTS](https://github.com/2noise/ChatTTS) | CUDA / CPU | `chattts` |
| TTS | [OmniVoice](https://huggingface.co/k2-fsa/OmniVoice) | CUDA / Intel XPU / Apple Silicon | `omnivoice` |
| TTS | [MMS TTS](https://huggingface.co/docs/transformers/model_doc/mms) | CUDA / CPU | 内置 |
| TTS | OpenAI 兼容的 `/v1/audio/speech` 端点 | 本地或远程 HTTP 服务器 | 内置 |

使用 `--stt`、`--llm_backend` 和 `--tts` 选择实现。CLI 只为你所选择的后端构建配置；未激活后端的已知选项出于兼容性仍被接受，但会带警告忽略。JSON 配置同样可以包含额外的未激活后端键，这些键会被忽略。运行 `speech-to-speech serve -h` 查看默认值，或在 `-h` 之前传入选择器以查看其他组合的、后端特定的标志（例如 `speech-to-speech serve --stt mlx-audio-whisper -h`）。

对于仅客户端的、配合 vLLM-Omni 或其他兼容服务器的 TTS 服务，见 [OpenAI 兼容 TTS](./docs/openai-compatible-tts-CN.md)。

对于仅客户端的、配合 vLLM、OpenAI 托管 Transcription API 或其他兼容服务器的语音识别，见 [OpenAI 兼容 STT](./docs/openai-compatible-stt-CN.md)。

## 命令

| 命令 | 行为 | 在以下场景使用 |
|---|---|---|
| `serve` | 通过 OpenAI Realtime WebSocket 和 WebRTC 运行流水线服务器。 | 你正在基于该 API 构建应用或设备。 |
| `talk --url <完整实时 URL>` | 运行打包的麦克风 / 扬声器客户端。 | 你想与一个已有的 Realtime 服务器对话。 |
| `local` | 在回环上进程内组合 `serve` 和 `talk`。 | 你想用一个命令运行服务器并与之对话。 |

`serve` 默认绑定到 `127.0.0.1`；要暴露到网络，显式传入 `--host 0.0.0.0`。`local` 总是绑定到回环，并在 `ws://127.0.0.1:<port>/v1/realtime` 连接同一个打包的客户端。

打包的 `local` 客户端在使用 OpenAI 兼容 TTS 后端时缓冲 196 ms 的接收音频，以吸收来自 HTTP 语音推理的短暂送达间隙。其他 `local` 后端和 `talk` 默认立即开始播放。使用 `--playback-buffer-ms <毫秒>` 覆盖任一默认：较大的值更能抵抗卡顿，但会延迟每个响应的开始，而较小的值开始得更早，但对抖动更敏感。该设置只控制打包的 Python 客户端的扬声器；浏览器和其他 Realtime 客户端管理它们自己的播放缓冲。

打包的客户端可以通过 `talk --tool-module <模块>` 或 `local --tool-module <模块>` 选择加入本地 Python 工具。模块契约、编程式 API 以及一个 Serper 网络搜索示例记录在 [工具调用设计](./src/speech_to_speech/api/openai_realtime/README-CN.md#打包的-python-客户端工具)。

### 从 `--mode` 迁移

`--mode` 已弃用，并将很快停止工作。在这个迁移窗口期间，`speech-to-speech --mode realtime` 运行 `speech-to-speech serve`，`speech-to-speech --mode local` 运行 `speech-to-speech local`；两者都会打印警告。所有其他 mode 值已被移除，并退出并提示使用新命令。

### Realtime 服务器

```bash
export OPENAI_API_KEY=...
speech-to-speech serve
```

这等价于：

```bash
speech-to-speech serve \
    --thresh 0.6 \
    --stt parakeet-tdt \
    --llm_backend responses-api \
    --tts qwen3 \
    --qwen3_tts_model_name Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice \
    --qwen3_tts_speaker Aiden \
    --qwen3_tts_language auto \
    --qwen3_tts_backend ggml \
    --qwen3_tts_non_streaming_mode True \
    --qwen3_tts_mlx_quantization 6bit \
    --model_name gpt-5.6-terra \
    --chat_size 30 \
    --responses_api_stream \
    --enable_live_transcription
```

默认模型是 `gpt-5.6-terra`，通过 OpenAI Responses API，推理强度（reasoning effort）为 `none`，保留了先前默认模型的、偏向延迟的推理行为。用 `--model_name` 覆盖模型，用 `--responses_api_reasoning_effort` 覆盖强度，并设置 `--responses_api_base_url` 以指向另一个 OpenAI 兼容的提供方或服务器。

### 本地 Mac

```bash
speech-to-speech local --mac-optimal-settings
```

可选地配合特定 LLM：

```bash
speech-to-speech local \
    --mac-optimal-settings \
    --model_name mlx-community/Qwen3-4B-Instruct-2507-4bit
```

该设置：

- 对受支持的模型组件使用 MPS 默认。
- 设置 Parakeet TDT 用于 STT。
- 设置 MLX LM 作为 LLM 后端。
- 设置 Qwen3-TTS 用于 TTS，默认使用带 `6bit` MLX 变体的 `mlx-audio`。

该预设只作为默认值提供：显式的 `--device`、像 `--qwen3_tts_device` 这样的组件设备标志，以及 `--stt`、`--llm_backend`、`--model_name` 和 `--tts` 都优先。`serve` 而非 `local` 时使用它，当你想暴露服务器而不启动麦克风 / 扬声器客户端时。

`--tts pocket`、`--tts kokoro` 和 `--tts omnivoice` 在 macOS 上也有效。

要在本地比较 MLX 量化变体：

```bash
python scripts/benchmark_tts.py \
    --handlers qwen3 \
    --iterations 3 \
    --qwen3_mlx_quantizations bf16 4bit 6bit 8bit
```

### Docker

安装 [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)，然后：

```bash
docker compose up
```

该 compose 文件启动一个带有 Gemma 4 的 llama.cpp 服务器和 Realtime 服务器，暴露端口 `8080` 和 `8765`。

## Realtime API

Realtime 模式通过 WebSocket 和 WebRTC 支持 OpenAI Realtime 协议，带有实时转写和低延迟轮次切换。WebSocket 客户端在 `/v1/realtime` 连接：

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8765/v1",
    websocket_base_url="ws://localhost:8765/v1",
    api_key="not-needed",
)

with client.realtime.connect(model="local") as conn:
    conn.send(
        {
            "type": "session.update",
            "session": {
                "type": "realtime",
                "instructions": "You are a helpful assistant.",
                "audio": {
                    "input": {
                        "turn_detection": {
                            "type": "server_vad",
                            "interrupt_response": True,
                        }
                    }
                },
            },
        }
    )

    for event in conn:
        print(event.type)
```

该服务器实现了核心的 Realtime 事件集：入站的 `input_audio_buffer.append`、`session.update`、`conversation.item.create`、`conversation.item.truncate`、`response.create` 和 `response.cancel`；出站的语音开始 / 停止、流式转写、音频增量、工具调用和 `response.done`。CI 通过 SDK 现成的 WebSocket 和 WebRTC 传输连接固定的 `@openai/agents` `RealtimeSession` 实例。这是一个经过测试的核心子集，而非声明完整的 OpenAI Realtime API 等价性。事件矩阵、架构和设计细节位于 [Realtime 引擎 README](./src/speech_to_speech/api/openai_realtime/README-CN.md)。

### LLM 代理

使用 `--enable_llm_proxy`，实时服务器还把它所配置的远程 LLM 作为一个普通的 OpenAI 兼容端点暴露，以便客户端可以运行旁路任务（摘要、标题、后台智能体），带有工具和流式，完全与语音对话并发，且从不会被新的语音打断：

* 运行 `--llm_backend chat-completions` 时：`POST /v1/chat/completions`
* 运行 `--llm_backend responses-api` 时：`POST /v1/responses`

该服务器自身不进行认证，也不进行节流。只在可信网络上启用代理，或将服务器部署在一个负责访问控制的网关之后。s2s-endpoint 计算副本就是这样一个网关：它只向用 HF 令牌创建会话的客户端开放这些路径，针对该令牌检查 API 密钥，并对每个用户施加速率限制。把你与之对话的任何主机指向现成的 OpenAI SDK；该服务器忽略 API 密钥（前方的网关决定它必须是什么）：

```python
from openai import OpenAI

llm = OpenAI(base_url="http://localhost:8765/v1", api_key="unused")
completion = llm.chat.completions.create(
    model="anything",  # 被忽略：服务器强制使用其配置的 --model_name
    messages=[{"role": "user", "content": "Summarize the conversation so far: ..."}],
)
```

请求是无状态的（每次发送完整的消息列表），并被代理到所配置的、由服务器持有密钥的上游，该密钥永远不会到达客户端。`model` 字段总是被服务器配置的 `--model_name` 覆盖。代理默认关闭，需要一个远程后端（`chat-completions` 或 `responses-api`），否则以 501 和原因作答。

## LLM 后端

LLM 是流水线中计算最密集、延迟最高的组件。一个大模型的一次前向传播可能主导端到端的响应时间，因此为你的硬件和延迟预算选择正确的后端很重要。该流水线支持：

- **本地推理**：在 CUDA / CPU 上的 `transformers`，以及在 Apple Silicon 上的 `mlx-lm`。
- **自托管服务器**：`responses-api` 和 `chat-completions` 可以指向本地的 [vLLM](https://github.com/vllm-project/vllm) 或 [lla.cpp](https://github.com/ggerganov/llama.cpp) 服务器。
- **提供方 API**：相同的后端适用于 OpenAI、[HF Inference Providers](https://huggingface.co/inference-providers)、[OpenRouter](https://openrouter.ai) 和其他 OpenAI 兼容的提供方。

有两个可用的 API 后端，共享相同的 `--responses_api_*` 连接标志：

- `--llm_backend responses-api`（默认）指向 `/v1/responses`。
- `--llm_backend chat-completions` 指向 `/v1/chat/completions`。

### 直接音频输入（无 STT）

使用 `--stt none --llm_backend chat-completions` 把每个完成的 VAD 音频片段直接发送给一个音频输入模型。直接音频模式不支持 `--llm_backend responses-api`：一个模型可能通过 `/v1/chat/completions` 接受音频而不支持 `/v1/responses`，包括 OpenAI 的 [`gpt-audio-1.5`](https://developers.openai.com/api/docs/models/gpt-audio-1.5)。

你必须显式设置 `--model_name` 为一个接受音频的模型：默认的 `gpt-5.6-terra` 接受文本和图像输入，但不接受音频。在启用此模式之前，请查阅提供方的模型文档和端点支持。对于 OpenAI，见 [GPT-5.6 Terra 模型卡](https://developers.openai.com/api/docs/models/gpt-5.6-terra)和 [音频输入指南](https://developers.openai.com/api/docs/guides/audio#add-audio-to-your-existing-application)。

```bash
speech-to-speech serve \
    --stt none \
    --llm_backend chat-completions \
    --model_name "YOUR_AUDIO_CAPABLE_MODEL" \
    --responses_api_base_url "https://provider.example/v1" \
    --responses_api_api_key "$PROVIDER_API_KEY"
```

OpenAI 兼容的服务器以不同方式表示输入音频。使用 `--responses_api_audio_content_type input_audio`（默认）对应内嵌的 WAV base64，或使用 `--responses_api_audio_content_type audio_url` 对应一个 base64 data URL。

下面的示例把用于本地 STT 的 Parakeet TDT 和用于本地 TTS 的 Qwen3-TTS 与不同的 LLM 后端配对。

### Responses API 后端

适用于任何实现 OpenAI Responses API 的提供方或服务器。把 `--responses_api_base_url` 指向端点，并相应地设置 `--model_name`：

| 提供方 / 服务器 | `--responses_api_base_url` | `--responses_api_api_key` |
|---|---|---|
| OpenAI | 省略，使用 OpenAI 默认 | `$OPENAI_API_KEY` |
| HF Inference Providers | `https://router.huggingface.co/v1` | `$HF_TOKEN` |
| OpenRouter | `https://openrouter.ai/api/v1` | `$OPENROUTER_API_KEY` |
| vLLM | `http://localhost:8000/v1` | 省略或任意字符串 |
| llama.cpp | `http://127.0.0.1:8080/v1` | 空字符串 |

```bash
# OpenAI
speech-to-speech local \
    --stt parakeet-tdt \
    --llm_backend responses-api \
    --tts qwen3 \
    --qwen3_tts_mlx_quantization 6bit \
    --model_name "gpt-4o-mini" \
    --responses_api_api_key "$OPENAI_API_KEY" \
    --responses_api_stream \
    --enable_live_transcription
```

```bash
# HF Inference Providers：通过 Together 的 Qwen3.5-9B
speech-to-speech local \
    --stt parakeet-tdt \
    --llm_backend responses-api \
    --tts qwen3 \
    --qwen3_tts_mlx_quantization 6bit \
    --model_name "Qwen/Qwen3.5-9B:together" \
    --responses_api_base_url "https://router.huggingface.co/v1" \
    --responses_api_api_key "$HF_TOKEN" \
    --responses_api_stream \
    --enable_live_transcription
```

```bash
# HF Inference Providers：通过 Groq 的 GPT-oss-20B
speech-to-speech serve \
    --stt parakeet-tdt \
    --llm_backend responses-api \
    --tts qwen3 \
    --qwen3_tts_mlx_quantization 6bit \
    --model_name "openai/gpt-oss-20b:groq" \
    --responses_api_base_url "https://router.huggingface.co/v1" \
    --responses_api_api_key "$HF_TOKEN" \
    --responses_api_stream \
    --enable_live_transcription
```

### Chat Completions 后端

与 `responses-api` 配置相同，复用相同的 `--responses_api_*` 连接标志，但对话的是 `/v1/chat/completions` 而非 `/v1/responses`。在以下情况优先使用：

- 提供方在 Responses 路径上忽略 `chat_template_kwargs.enable_thinking` 并需要一个 `reasoning_effort` 旋钮来抑制推理，或
- 服务器的 Responses 流式工具调用路径不可靠，而其 Chat Completions 工具调用流式是稳固的。这对某些 vLLM 构建很有用；见 [#312](https://github.com/huggingface/speech-to-speech/issues/312)。

在提供方上添加 `--responses_api_reasoning_effort none` 以在聊天模板标志无效时禁用推理：

```bash
# vLLM 提供带工具调用的 Qwen 模型
speech-to-speech serve \
    --stt parakeet-tdt \
    --llm_backend chat-completions \
    --tts qwen3 \
    --model_name "Qwen/Qwen3-4B-Instruct-2507" \
    --responses_api_base_url "http://localhost:8000/v1" \
    --responses_api_stream
```

```bash
# 通过 Cerebras 的 HF 路由器提供 Gemma 4 31B，禁用推理以获得低语音延迟
speech-to-speech serve \
    --stt parakeet-tdt \
    --llm_backend chat-completions \
    --tts qwen3 \
    --model_name "google/gemma-4-31B-it:cerebras" \
    --responses_api_base_url "https://router.huggingface.co/v1" \
    --responses_api_api_key "$HF_TOKEN" \
    --responses_api_reasoning_effort none \
    --responses_api_stream
```

### 完全本地

如 [Reachy Mini 本地对话指南](https://huggingface.co/blog/local-reachy-mini-conversation) 所述，在独立的 llama.cpp 进程中运行 LLM，以获得摩擦最小的完全本地设置：

对于带有浏览器 demo、Realtime 轮次修订和打断的完全本地原生音频设置，见经过测试的 [Apple Silicon 上的 Gemma 4 12B 语音到语音示例](./examples/gemma4-12b-macos/README-CN.md)。

```bash
# 终端 1：用 llama.cpp 提供 Gemma 4
llama-server -hf ggml-org/gemma-4-E4B-it-GGUF -np 2 -c 65536 -fa on --swa-full
```

```bash
# 终端 2：使用那个本地 LLM 服务器的 speech-to-speech
speech-to-speech serve \
    --stt parakeet-tdt \
    --llm_backend responses-api \
    --tts qwen3 \
    --model_name "ggml-org/gemma-4-E4B-it-GGUF" \
    --responses_api_base_url "http://127.0.0.1:8080/v1" \
    --responses_api_api_key "" \
    --responses_api_stream \
    --enable_live_transcription
```

当你想运行同一个服务器并通过托管它的机器对话时，使用 `speech-to-speech local`。在 Apple Silicon 上可通过 `--llm_backend mlx-lm` 或在 CUDA / CPU 上通过 `--llm_backend transformers` 使用进程内本地后端。

## 离线运行

在所选组件的依赖和模型资源在本地安装后，该流水线可以在没有互联网访问的情况下运行。在断开连接之前，先在线启动一次确切的配置，以便它可以缓存所需的 STT、LLM、TTS、Silero VAD、NLTK 和 Smart Turn 资源。

对于摩擦最小的完全本地 LLM 设置，如 [完全本地](#完全本地) 所述在机器上运行 llama.cpp。一旦 llama.cpp 和流水线资源在本地可用，在启动 speech-to-speech 时设置 `HF_HUB_OFFLINE=1` 以防止 Hugging Face Hub 请求：

```bash
HF_HUB_OFFLINE=1 speech-to-speech serve \
    --model_name "ggml-org/gemma-4-E4B-it-GGUF" \
    --responses_api_base_url "http://127.0.0.1:8080/v1" \
    --responses_api_api_key ""
```

如果没有本地基础 URL 覆盖，默认的 `responses-api` LLM 后端会调用远程服务。或者，使用进程内本地后端，例如 `transformers` 或 `mlx-lm`。每个所选模型必须已经缓存，或通过其后端支持的本地路径提供。

Smart Turn 使用一个单独的 ONNX checkpoint。一个缓存的 checkpoint 在 `HF_HUB_OFFLINE=1` 下工作；对于显式的、与缓存无关的 setup，传入 `--smart_turn_model_path /path/to/smart-turn-v3.2-cpu.onnx`。如果 checkpoint 不可用，传入 `--no_smart_turn` 以禁用 Smart Turn。

## 多语言支持

语言覆盖取决于你选择的 STT 和 TTS 后端，而非流水线本身：

| 组件 | 后端 | 语言 |
|---|---|---|
| STT | Parakeet TDT（默认） | 25 种欧洲语言 |
| STT | Whisper / Whisper MLX / Faster Whisper | 广泛的多语言覆盖，取决于所选的 Whisper checkpoint |
| STT | Paraformer | 取决于所选的 FunASR checkpoint；默认偏向中文 |
| TTS | Qwen3-TTS（默认） | 多语言，默认 `--qwen3_tts_language auto` |
| TTS | Kokoro | 多种语言 / voice 映射，取决于后端可用性 |
| TTS | ChatTTS | 英语和中文 |
| TTS | MMS TTS | 通过 MMS checkpoint 的广泛多语言覆盖 |

确保你配对的 STT、LLM 和 TTS 都覆盖你的目标语言。两种使用模式：

- **单一语言**：把 `--language` 设置为目标语言代码。默认是 `en`。
- **语言切换**：设置 `--language auto`。STT 检测每个口语提示的语言，并将其转发给 LLM。可选地添加 `--enable_lang_prompt` 以附加一条 "Please reply to my message in ..."（请用……回复我的消息）指令。它默认为 `False`；大型 LLM 通常从上下文推断语言，但显式指令可以帮助较小的模型。

自动语言检测：

```bash
speech-to-speech serve \
    --stt parakeet-tdt \
    --language auto \
    --llm_backend mlx-lm \
    --model_name "mlx-community/Qwen3-4B-Instruct-2507"
```

单一非英语语言，本例为中文：

```bash
speech-to-speech serve \
    --stt whisper-mlx \
    --stt_model_name large-v3 \
    --language zh \
    --llm_backend mlx-lm \
    --model_name mlx-community/Qwen3-4B-Instruct-2507-4bit
```

两个命令也适用于 `--mac-optimal-settings`；显式的 `--stt` 标志覆盖它设置的默认值。

## OmniVoice

OmniVoice 提供 voice 克隆、voice 设计和跨 600+ 语言的自动 voice 选择。安装它的可选依赖，并提供一段参考音频及其转写以进行 voice 克隆。本示例使用 Linux 或 Windows 上的 CUDA；在 Apple Silicon 上使用 `--omnivoice_device mps`，或在启用了 Intel XPU 的 PyTorch 安装上使用 `--omnivoice_device xpu`：

```bash
pip install "speech-to-speech[omnivoice]"
speech-to-speech serve \
    --tts omnivoice \
    --omnivoice_device cuda \
    --omnivoice_ref_audio /path/to/reference.wav \
    --omnivoice_ref_text "Transcript of the reference clip."
```

该处理器把 OmniVoice 完成的 24 kHz 浮点输出转换为流水线的 16 kHz `int16` 块。OmniVoice 当前不通过 `generate()` 暴露增量音频，因此第一个块只有在整个语句合成完成后才可用。有关保存的提示、voice 设计、设备、延迟和所有后端标志，见 [TTS 组件指南](./src/speech_to_speech/TTS/README-CN.md#7-omnivoice---tts-omnivoice)。

`omnivoice` 扩展在 Linux、Windows 和 macOS 上受支持。在非 macOS 平台上，OmniVoice 和内置 Qwen3 后端都通过 `faster-qwen3-tts>=0.4.0` 共享 Transformers 5，因此安装此扩展会保留默认的 Qwen3 路径可用。Linux 默认使用 Qwen3 的 GGML 扩展；如果其 CUDA 12.8 / `manylinux_2_39` 原生 wheel 与你的宿主机不匹配，见 [CUDA 说明](#qwen3-tts-的-cuda-说明)。

> [!WARNING]
> OmniVoice 的代码是 Apache-2.0，但其预训练权重是 CC-BY-NC，未获授权用于商业用途。只有在获得授权和同意的情况下才使用 voice 克隆；不要将其用于 impersonation、欺诈、诈骗或其他非法或不道德的活动。

## Pocket TTS

来自 Kyutai Labs 的 Pocket TTS 提供带 voice 克隆的流式 TTS：

```bash
speech-to-speech serve \
    --tts pocket \
    --pocket_tts_voice jean \
    --pocket_tts_device cpu
```

可用的 voice 预设：`alba`、`marius`、`javert`、`jean`、`fantine`、`cosette`、`eponine`、`azelma`。自定义 voice 文件和 Hugging Face 路径也有效。

## CLI 参考

流水线 CLI 参数的参考位于 [参数类](./src/speech_to_speech/arguments_classes)，以及 `speech-to-speech serve -h`。客户端参数由 `speech-to-speech talk -h` 列出。

### 模块级参数

见 [ModuleArguments](./src/speech_to_speech/arguments_classes/module_arguments.py)。它允许设置：

- 一个通用的 `--device`，如果每个部分都应在同一设备上运行
- macOS 模型 / 设备默认值（`--mac-optimal-settings`）
- STT 实现（`--stt`）
- LLM 后端（`--llm_backend`：`transformers`、`mlx-lm`、`responses-api` 或 `chat-completions`）
- TTS 实现（`--tts`）
- 日志级别
- 实时流水线池大小（`--num_pipelines`）

### VAD 参数

见 [VADHandlerArguments](./src/speech_to_speech/arguments_classes/vad_arguments.py)。值得注意的选项：

- `--thresh`：触发语音活动检测的阈值。
- `--min_speech_ms`：被认为是语音的、检测到的语音活动的最短持续时间。
- `--min_speech_continuation_ms`：用于延续一个可在重开窗口内重新打开的、未提交的软结束轮次的、持续语音的持续条滞回阈值。默认和推荐的配对是 `--min_speech_ms 384 --min_speech_continuation_ms 192`。
- `--min_silence_ms`：用于切分语音的静音间隔最短长度。默认是 64 ms。
- `--short_segment_merge_ms`：用于拼接各自短于 `--min_speech_ms` 的相邻 VAD 片段的可选合并窗口。
- `--speculative_reopen_ms`：在软结束轮次之后延迟响应提交 800 ms，以便立即恢复的语音可以重新打开它。
- `--unanswered_reopen_ms`：一个尚未收到任何助手输出的软结束推测轮次保持可重新打开的时长的理智上限。启用 Smart Turn 时，它被钳制到至少 `--smart_turn_max_wait_ms`，以便一个轮次在其完整的宽限期内保持可重新打开。

### Smart Turn 端点检测

[Smart Turn v3.2](https://huggingface.co/pipecat-ai/smart-turn-v3) 可以使用当前轮次的内容和韵律来验证 Silero 的句末决策。Silero 完成片段切分，STT / LLM 工作可以推测式地开始。完整的轮次立即开始处理，并在提交输出之前使用 `--speculative_reopen_ms`（默认 800 ms）。不完整的轮次等待 `--smart_turn_incomplete_delay_ms`（默认 600 ms）才开始 STT / LLM 工作，而它们的输出仍受 `--smart_turn_max_wait_ms`（默认 2 秒）的门控。如果语音在任何延迟期间恢复，现有的轮次作为较新的修订被重新打开，累积的音频被重新发出，而来自前一修订的工作在到达用户之前被丢弃。

基础包包含量化的 CPU 运行时，并默认启用 Smart Turn：

```bash
pip install speech-to-speech
speech-to-speech serve
```

最新支持的 v3.2 CPU checkpoint 在首次使用时从 Hugging Face Hub 下载。传入 `--smart_turn_model_path /path/to/model.onnx` 以使用本地模型，或 `--no_smart_turn` 以禁用 Smart Turn。Smart Turn 对服务器会话和打包的本地客户端默认启用。

用 `--smart_turn_threshold`（默认 `0.5`）调优完成截断点。较高的阈值使模糊的停顿更可能使用较长的推测式响应宽限。

### STT、LLM 和 TTS 参数

`model_name`、`torch_dtype` 和 `device` 对每个 STT、LLM 和 TTS 实现都暴露。STT 和 TTS 参数使用处理器前缀，例如 `--stt_model_name` 或 `--qwen3_tts_device`。LLM 模型选择和聊天设置通过无前缀的标志跨后端共享，例如 `--model_name` 和 `--chat_size`；后端特定的标志对 `responses-api` 和 `chat-completions` 后端使用 `responses_api_` 前缀，对本地后端使用 `llm_` 前缀。

例如：

```bash
# 本地 transformers/mlx-lm 后端
--model_name google/gemma-2b-it

# OpenAI 兼容后端
--llm_backend responses-api --model_name deepseek-chat --responses_api_base_url https://api.deepseek.com
```

### 生成参数

其他生成参数可以使用处理器前缀加 `_gen_` 设置，例如 `--stt_gen_max_new_tokens 128` 或 `--llm_gen_temperature 0.7`。尚未暴露的参数可以添加到相关的参数类。

## 贡献

问题和 PR 都欢迎。好的起点是 [开放问题](https://github.com/huggingface/speech-to-speech/issues)。对于较大的更改，先开一个问题来讨论方案。

对于本地开发：

```bash
uv sync
pytest
ruff check
```

## Star 历史

[![Star History Chart](assets/star-history.svg)](https://github.com/huggingface/speech-to-speech/stargazers)

## 引用

如果你使用此流水线，也请引用你运行的组件模型。默认值是：

### Silero VAD

```bibtex
@misc{SileroVAD,
  author = {Silero Team},
  title = {Silero VAD: pre-trained enterprise-grade Voice Activity Detector (VAD), Number Detector and Language Classifier},
  year = {2021},
  publisher = {GitHub},
  journal = {GitHub repository},
  howpublished = {\url{https://github.com/snakers4/silero-vad}},
  email = {hello@silero.ai}
}
```

### Parakeet TDT

```bibtex
@misc{parakeet-tdt,
  author = {NVIDIA},
  title = {Parakeet TDT 0.6B v3},
  publisher = {Hugging Face},
  howpublished = {\url{https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3}}
}
```

### Qwen3-TTS

```bibtex
@misc{qwen3-tts,
  author = {Qwen Team},
  title = {Qwen3-TTS},
  publisher = {Hugging Face},
  howpublished = {\url{https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice}}
}
```

可选后端（如 Kokoro、Pocket TTS、ChatTTS、Whisper 变体、Paraformer 和 MMS）的引用位于各自的 [组件 README](./src/speech_to_speech) 中。
