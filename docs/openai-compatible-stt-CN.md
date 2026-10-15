> 🌐 Language / 语言：**中文版** · [English](./openai-compatible-stt.md)

# OpenAI 兼容 STT 端点

`openai` STT 后端在 speech-to-speech 内部保留 VAD、轮次（turn）、会话、对话状态和响应处理，而把识别工作委托给一个外部服务器：

```text
VAD 音频 -> POST /v1/audio/transcriptions
```

每个请求上传一段内存中的单声道 PCM16 WAV（16 kHz），并接受带字符串 `text` 字段的 JSON 或纯文本响应。启用实时转写时，渐进式更新会再次上传已累积的话语（utterance），从而增加请求量和提供方的用量。

## 通过 vLLM 使用 Qwen3-ASR

在 vLLM 后运行一个受支持的 ASR 模型。在提供 STT 服务的机器上，将 vLLM 安装到它自己的环境中；它无需位于本仓库内部。

```bash
pip install "vllm[audio]"
vllm serve Qwen/Qwen3-ASR-1.7B --port 8000
```

检查服务器，然后选择远程后端。LLM 和 TTS 参数可以指向任何其他受支持的后端。

```bash
curl http://localhost:8000/v1/models

speech-to-speech local \
  --stt openai \
  --openai_stt_base_url http://localhost:8000/v1 \
  --openai_stt_model Qwen/Qwen3-ASR-1.7B
```

## OpenAI 托管的转写

同一个后端可以调用 OpenAI 托管的 [Transcription API](https://developers.openai.com/api/docs/guides/speech-to-text)。导出一个 API 密钥并选择一个转写模型：

```bash
export OPENAI_API_KEY=...

speech-to-speech local \
  --stt openai \
  --openai_stt_base_url https://api.openai.com/v1 \
  --openai_stt_model gpt-transcribe \
  --openai_stt_response_format json
```

LLM 和 TTS 后端仍可独立配置；为 STT 使用 OpenAI 并不要求流水线的其余部分也使用它。

## 认证与兼容性

当端点需要 bearer 认证时，设置 `--openai_stt_api_key`。当基础 URL 为 `https://api.openai.com/v1` 且省略该参数时，处理器会使用 `OPENAI_API_KEY`（若已存在）。其他端点永远不会隐式获取该环境凭据。

请求与响应的形态遵循 OpenAI 的 Audio API。特别地，`gpt-transcribe` 使用官方复数 `languages[]` 字段发送语言提示，并从复数 `languages` 响应中读取首个检测到的语言代码。较旧的模型和兼容服务器继续使用单数 `language` 字段。

客户端接受 JSON 和文本响应。对纯文本服务器使用 `--openai_stt_response_format text`。传输层和 HTTP 错误在被呈现给 Realtime 客户端之前会经过清理，失败的最终请求不会创建 LLM 工作。

在初始化期间，处理器会通过所配置的端点转写一秒钟的合成静音。因此，端点、认证、模型或响应格式方面的失败会阻止 Realtime 服务器接受会话。

渐进式请求是尽力而为的。每个流水线至多保留一个渐进式请求在途，并在它运行时丢弃更新的渐进式更新。最终请求是独立提交的，因此它不必等待在途的渐进式请求；过期的渐进式结果会被丢弃。
