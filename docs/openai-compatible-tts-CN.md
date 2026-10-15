> 🌐 Language / 语言：**中文版** · [English](./openai-compatible-tts.md)

# OpenAI 兼容 TTS 端点

`openai` TTS 后端在 speech-to-speech 内部保留轮次、会话、对话状态和响应处理，而把合成工作委托给一个外部服务器：

```text
LLM 文本 -> POST /v1/audio/speech -> 16 kHz 的 PCM16
```

## 通过 vLLM-Omni 使用 Qwen3-TTS

在独立的 vLLM-Omni 进程中运行 Qwen3-TTS。保持已安装的 vLLM 与 vLLM-Omni 版本一致：

```bash
uv pip install vllm==0.24.0 --torch-backend=auto
uv pip install vllm-omni

vllm serve Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice \
  --deploy-config vllm_omni/deploy/qwen3_tts.yaml \
  --omni \
  --port 8091 \
  --trust-remote-code \
  --enforce-eager
```

在启动流水线之前检查服务器：

```bash
curl http://localhost:8091/v1/audio/voices
```

然后选择远程 TTS 后端。STT 和 LLM 参数仅作示例，可以指向任何受支持的后端。

```bash
speech-to-speech local \
  --stt parakeet-tdt \
  --llm_backend responses-api \
  --tts openai \
  --openai_tts_base_url http://localhost:8091/v1 \
  --openai_tts_model Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice \
  --openai_tts_voice aiden \
  --openai_tts_sample_rate 24000 \
  --openai_tts_stream true
```

Qwen3-TTS 产生 24 kHz 音频。客户端将其原始 PCM16 响应增量转换为流水线的单声道、有符号 int16、16 kHz、512 样本的块。如果某个服务器需要显式的语言，传入它期望的值，例如 Qwen3-TTS 使用 `--openai_tts_language English`。该值随每个语音请求原样转发；TTS 处理器不会从流水线推断它。

## OpenAI 及标准兼容服务器

标准的 OpenAI 兼容端点不需要 vLLM 的流式扩展。例如，在设置 `OPENAI_API_KEY` 后：

```bash
speech-to-speech local \
  --tts openai \
  --openai_tts_base_url https://api.openai.com/v1 \
  --openai_tts_model gpt-4o-mini-tts \
  --openai_tts_voice alloy \
  --openai_tts_response_format pcm \
  --openai_tts_sample_rate 24000
```

默认请求使用标准的 `stream_format=audio` 字段，并增量消费 HTTP 响应体。它不发送非标准的 `stream` 字段。

## 播放缓冲

有时首批音频块到达不均匀：初始突发之后，在稳定成稳定流之前可能有一个短暂的间隔。如果立即开始播放，可能因此清空扬声器队列并导致短暂卡顿。启动缓冲区在开始播放之前保留少量音频，以便吸收这种早期的抖动。如果之后播放追上了传入流，客户端在重启前也会使用同一个缓冲区。

该缓冲区通常为 0 ms，因此其他本地 TTS 后端和 `speech-to-speech talk` 在音频到达时立即开始播放。当块均匀送达时，这能将延迟降到最低。`talk` 客户端无法选择后端特定的默认值，因为它连接到一个 Realtime 端点，却不知道是哪个 TTS 后端产生的音频。

对于 `speech-to-speech local --tts openai`，默认值改为 196 ms。OpenAI 兼容后端通过一个独立的 HTTP 连接到 `/audio/speech` 端点接收合成音频，首批块可能比进程内 TTS 有更明显的送达抖动。这份额外的缓冲以较小的启动延迟换取更平滑的播放。

缓冲区位于 TTS 的下游，不会更改 TTS 请求、合成、重采样或服务器部署。

使用 `--playback-buffer-ms` 覆盖任一命令的默认值。显式的 `0` 即使对 `local --tts openai` 也会禁用缓冲。较大的值提高了对送达抖动的容忍度，代价是每次响应的启动更晚；较小的值减少了该启动延迟，但增加了欠载（underrun）风险。例如：

```bash
speech-to-speech local \
  --playback-buffer-ms 256 \
  --tts openai \
  --openai_tts_base_url https://api.openai.com/v1
```

短于所配置缓冲区的响应，在音频响应完成时立即播放。浏览器、WebRTC 和第三方 Realtime 客户端使用它们自己的播放行为，不受此选项影响。

## 认证与兼容性

当端点需要 bearer 认证时，设置 `--openai_tts_api_key`。当省略时，处理器会使用 `OPENAI_API_KEY`（若已存在）。

后端在启动期间执行一次简短的合成请求。因此无效的端点、认证、模型、voice、请求和音频响应配置会在 Realtime 服务器接受会话之前就失败。

客户端接受：

- 配置了 `--openai_tts_sample_rate` 的原始有符号 PCM16；或
- 在 `--openai_tts_stream false` 且 `--openai_tts_response_format wav` 时的 WAV 响应。

两种格式都会被解码、重采样，并在 HTTP 响应体到达时增量转发。

`stream_format=audio` 字段是标准请求形态的一部分。`stream=true` 是 vLLM-Omni 的扩展，默认禁用；当服务器支持时，用 `--openai_tts_stream true` 显式启用。

取消是尽力而为的：打断（barge-in）和会话拆除会关闭客户端的活动 HTTP 响应，并在本地阻止进一步的音频发布。标准的 `/v1/audio/speech` 接口没有可移植的服务器端取消操作，因此断开连接的客户端不能保证端点上的计算会立即停止。
