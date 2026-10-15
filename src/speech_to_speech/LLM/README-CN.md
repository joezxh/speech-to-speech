> 🌐 Language / 语言：**中文版** · [English](./README.md)

# LLM 概览

## 可用的 LLM 后端（`--llm_backend`）

`s2s_pipeline.py` 在运行时支持的取值：

- `transformers` → `language_model.py`（Transformers 后端）
- `mlx-lm` → `language_model.py`（MLX 后端）
- `responses-api` → `responses_api_language_model.py`

## 用法

### 1) Transformers（`--llm_backend transformers`）

- 处理器：`LanguageModelHandler`
- 典型用途：使用 Hugging Face Transformers 在本地 GPU / CPU 推理
- 后端专属参数前缀：`--llm_*`
- 共享参数（来自基类）：`--model_name`、`--chat_size`、`--init_chat_prompt`、`--enable_lang_prompt`

```bash
speech-to-speech serve \
  --llm_backend transformers \
  --model_name Qwen/Qwen3-4B-Instruct-2507 \
  --llm_device cuda \
  --llm_torch_dtype float16 \
  --llm_gen_max_new_tokens 128
```

常用选项：

- `--llm_gen_min_new_tokens`
- `--llm_gen_temperature`
- `--llm_gen_do_sample`
- `--chat_size`
- `--init_chat_prompt`

### 2) MLX-LM（`--llm_backend mlx-lm`）

- 处理器：`LanguageModelHandler`
- 典型用途：Apple Silicon 本地推理
- 后端专属参数前缀：与 Transformers 相同（`--llm_*`）

```bash
speech-to-speech serve \
  --llm_backend mlx-lm \
  --model_name mlx-community/Qwen3-4B-Instruct-2507-4bit \
  --llm_device mps \
  --llm_gen_max_new_tokens 128
```

常用选项：

- `--llm_gen_temperature`
- `--llm_gen_do_sample`
- `--chat_size`
- `--init_chat_prompt`

### 3) OpenAI 兼容 API（`--llm_backend responses-api`）

- 处理器：`ResponsesApiModelHandler`
- 典型用途：通过 OpenAI 兼容端点提供远程模型服务
- 后端专属参数前缀：`--responses_api_*`
- 共享参数（来自基类）：`--model_name`、`--chat_size`、`--init_chat_prompt`、`--enable_lang_prompt`

```bash
speech-to-speech serve \
  --llm_backend responses-api \
  --model_name gpt-5.6-terra \
  --responses_api_api_key YOUR_API_KEY \
  --responses_api_base_url https://api.example.com/v1 \
  --responses_api_stream true
```

常用选项：

- `--chat_size`
- `--init_chat_prompt`
- `--user_role`

## LLM 行为

当 STT 设置为语言自动检测（`--language auto`）时，LLM 处理器可以接收 `(text, language_code)`，并前置一条语言控制指令，例如：

- `Please reply to my message in <language>.`（请用 <language> 回复我的消息。）

这有助于助手以检测到的语言作答。该行为通过 `--enable_lang_prompt` 显式开启（跨所有后端共享）；默认为 `False`。

## 配置

### CUDA 配置

```bash
speech-to-speech serve \
  --llm_backend transformers \
  --model_name microsoft/Phi-3-mini-4k-instruct
```

### 本地 Mac 配置

```bash
speech-to-speech local \
  --mac-optimal-settings \
  --model_name mlx-community/Qwen3-4B-Instruct-2507-4bit
```

`--mac-optimal-settings` 会设置 `--llm_backend mlx-lm`，并在未被覆盖时默认模型为 `mlx-community/Qwen3-4B-Instruct-2507-4bit`。该命令会独立选择是只运行服务器，还是将其与音频客户端组合启动。

### Realtime（OpenAI 兼容）配置

先启动服务器，再用打包的音频客户端连接：

```bash
# 1. 启动流水线服务器
speech-to-speech serve \
  --llm_backend mlx-lm \
  --model_name mlx-community/Qwen3-4B-Instruct-2507-4bit \
  --host 0.0.0.0 \
  --port 8765

# 2. 用音频客户端连接
speech-to-speech talk --url ws://127.0.0.1:8765/v1/realtime
```

或在 Apple Silicon 上使用 `--mac-optimal-settings`：

```bash
speech-to-speech serve \
  --mac-optimal-settings \
  --host 0.0.0.0 \
  --port 8765
```

### 远程 API 配置

```bash
speech-to-speech serve \
  --llm_backend responses-api \
  --model_name gpt-5.6-terra \
  --responses_api_api_key YOUR_API_KEY
```
