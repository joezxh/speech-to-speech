> 🌐 Language / 语言：**中文版** · [English](./README.md)

# 在 Apple Silicon 上运行 Gemma 4 12B 语音到语音

本示例在 Mac 上完整本地运行实时语音循环：

```text
麦克风 -> 浏览器 demo -> Realtime 服务器 -> VAD -> Gemma 4 12B（原生音频）
扬声器   <- 音频增量 <-                  Qwen3-TTS <- 助手响应
```

没有独立的语音转文本模型。每个完成的 VAD 片段都通过 llama.cpp 的 OpenAI 兼容 Chat Completions 端点发送给 Gemma。speech-to-speech 服务器与麦克风客户端通过 OpenAI Realtime 兼容的 WebSocket API 通信，因此轮次修订、取消和打断（barge-in）与其他 Realtime 客户端使用相同的路径。

## 要求

- 一台 Apple Silicon Mac。Q4 模型约 7.2 GB；建议搭配 Qwen3-TTS 时具备 24 GB 或更多的统一内存，以获得舒适的余量。
- 一个较新的、支持 Gemma 4 统一多模态的 llama.cpp 构建。
- 一个包含 PR #298 的源码检出。
- `uv`、Homebrew 和一个现代浏览器。

安装或更新 llama.cpp：

```bash
brew install llama.cpp
brew upgrade llama.cpp
llama-server --version
```

较旧的构建可能加载语言模型，但会因多模态投影器（projector）而失败，报 `unknown projector type: gemma4uv`。如果发生这种情况，请升级 llama.cpp。

从仓库根目录安装 speech-to-speech 环境：

```bash
uv sync
```

首次运行会下载 Gemma GGUF、其多模态投影器和本地的 MLX Qwen3-TTS 模型。

## 终端 1：用 llama.cpp 提供 Gemma 服务

```bash
llama-server \
    -hf ggml-org/gemma-4-12B-it-GGUF:Q4_0 \
    -c 16384 \
    -np 1 \
    -fa on \
    --host 127.0.0.1 \
    --port 8080
```

`-hf` 会下载并加载 Q4 模型及其多模态投影器。在启动流水线之前，等到服务器打印出以下两条消息：

```text
loaded multimodal model
listening on http://127.0.0.1:8080
```

关于音频输入为实验性的警告来自 llama.cpp，属于预期行为。

## 终端 2：启动实时语音流水线

```bash
uv run speech-to-speech serve \
    --stt none \
    --llm_backend chat-completions \
    --tts qwen3 \
    --model_name "ggml-org/gemma-4-12B-it-GGUF" \
    --responses_api_base_url "http://127.0.0.1:8080/v1" \
    --responses_api_api_key "" \
    --responses_api_audio_content_type input_audio \
    --responses_api_stream \
    --qwen3_tts_mlx_quantization 6bit \
    --min_silence_ms 300
```

等到服务器在 `ws://127.0.0.1:8765/v1/realtime` 上监听。

## 终端 3：启动浏览器 demo

```bash
SPEECH_TO_SPEECH_URL="ws://localhost:8765/v1/realtime" \
STARTUP_GREETING="" \
uv run --with-requirements demo/requirements.txt \
    uvicorn --app-dir demo server:app --port 7860
```

打开 <http://localhost:7860>，点击球体（orb），并允许麦克风访问。正常说话并用停顿来结束轮次。测试打断时请使用耳机，以免 TTS 播放反馈到麦克风。在 demo 和服务器终端中按 `Ctrl-C` 停止。

该 demo 默认使用 WebSocket，也就是本示例所用的路径。由于后端 URL 已固定，它也在 **Settings -> Transport** 中显示 WebRTC。要尝试 WebRTC，先用 `uv sync --extra webrtc` 安装其后端依赖。否则，保持传输方式为 WebSocket。

浏览器 UI 显示对话历史、用户和助手的轮次状态、可回放的用户音频、voice 和指令设置，以及打断。将 `STARTUP_GREETING` 设为空值，可以让这个原生音频测试专注于首个口语轮次。

重要的选项有：

- `--stt none`：绕过 STT，将捕获的 WAV 直接转发给 Gemma。
- `--llm_backend chat-completions`：使用 llama.cpp 的 `/v1/chat/completions` 端点，它接受原生音频。
- `--responses_api_audio_content_type input_audio`：使用当前 llama.cpp 构建支持的负载形态。
- `serve`：运行该 API，具备推测式轮次修订、响应取消，以及标准的 Realtime 事件生命周期。
- `--min_silence_ms 300`：避免把词与词之间非常短的停顿当作已完成的轮次，同时保持端点检测（endpointing）的响应性。

## 无头客户端替代方案

要在没有浏览器 demo 的情况下测试，用打包的麦克风 / 扬声器客户端替换终端 3：

```bash
uv run speech-to-speech talk \
    --url ws://127.0.0.1:8765/v1/realtime
```

## 故障排除

- **`unknown projector type: gemma4uv`**：升级 llama.cpp，然后确认 `llama-server --version` 已变化。
- **`unsupported content[].type`**：保持 `--responses_api_audio_content_type input_audio`；受测试的 llama.cpp 端点不接受 `audio_url`。
- **没有麦克风输入**：在浏览器中允许麦克风访问。如果之前被拒绝，在 **System Settings -> Privacy & Security -> Microphone** 中为浏览器启用它，然后重新加载页面。
- **UI 无法连接**：确认 speech-to-speech 服务器正在端口 `8765` 上监听，且 demo 是用上述精确的 `SPEECH_TO_SPEECH_URL` 启动的。
- **WebRTC 返回 501**：保持 demo 使用默认的 WebSocket 传输，或在启动后端之前安装 `webrtc` 扩展。
- **助手听到自己的声音**：使用耳机。测试打断时不要传入 `--block_mic_during_playback`，因为该选项会故意在无头客户端播放期间暂停麦克风捕获。
- **轮次结束过早**：将 `--min_silence_ms` 提高到 `500` 或 `700`。较大的值会在用户停止后增加相同的端点检测延迟。
- **内存压力**：停止其他本地模型。保持 `-np 1`，如果 6-bit TTS 模型留下的余量太少，使用 `--qwen3_tts_mlx_quantization 4bit`。
