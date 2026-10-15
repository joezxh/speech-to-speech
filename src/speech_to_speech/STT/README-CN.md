> 🌐 Language / 语言：**中文版** · [English](./README.md)

# STT 概览

本文档汇总 `STT/` 目录中的语音转文本（STT）实现，包括语言支持、语言缩写，以及在 `s2s_pipeline.py` 中的用法。

## 可用的 STT 模式（`--stt`）

- `whisper` → `STT/whisper_stt_handler.py`
- `whisper-mlx` → `STT/lightning_whisper_mlx_handler.py`
- `mlx-audio-whisper` → `STT/mlx_audio_whisper_handler.py`
- `faster-whisper` → `STT/faster_whisper_handler.py`
- `parakeet-tdt` → `STT/parakeet_tdt_handler.py`
- `paraformer` → `STT/paraformer_handler.py`
- `openai` → `STT/openai_compatible_handler.py`

## 各处理器的语言支持

### 1) Whisper（`--stt whisper`）

- 处理器：`WhisperSTTHandler`
- 语言输入参数：`--language`（来自共享的 Whisper 参数）
- 支持固定语言（如 `en`）或 `auto`
- 内部支持的语言列表：
  - `en`、`fr`、`es`、`zh`、`ja`、`ko`、`hi`、`de`、`pt`、`pl`、`it`、`nl`
- 行为：
  - 从 token 输出检测语言
  - 若检测到的语言不在支持列表中，则回退到上一次的语言

### 2) Lightning Whisper MLX（`--stt whisper-mlx`）

- 处理器：`LightningWhisperSTTHandler`
- 使用与 Whisper 相同的共享 `--language` 参数
- 内部支持的语言列表：
  - `en`、`fr`、`es`、`zh`、`ja`、`ko`、`hi`、`de`、`pt`、`pl`、`it`、`nl`
- 行为：
  - 若为 `--language auto`，模型对每句话自动检测
  - 若检测到的语言不受支持，则回退到上一次支持的语言

### 3) MLX Audio Whisper（`--stt mlx-audio-whisper`）

- 处理器：`MLXAudioWhisperSTTHandler`
- 模型参数：`--mlx_audio_whisper_model_name`
- 语言仍来自共享的 `--language` 参数（在流水线中接入）
- 内部支持的语言列表：
  - `en`、`fr`、`es`、`zh`、`ja`、`ko`、`hi`、`de`、`pt`、`pl`、`it`、`nl`
- 行为：
  - 除非 `--language auto`，否则使用固定语言
  - 需要时回退到最近已知的受支持语言

### 4) Faster-Whisper（`--stt faster-whisper`）

- 处理器：`FasterWhisperSTTHandler`
- 语言参数：`--faster_whisper_stt_gen_language`
- 默认语言：`en`
- 注意：
  - 该处理器将生成参数字典直接传给 `faster_whisper.WhisperModel.transcribe(...)`
  - 实际语言覆盖取决于所选的 Faster-Whisper / OpenAI Whisper 模型

### 5) Parakeet TDT（`--stt parakeet-tdt`）

- 处理器：`ParakeetTDTSTTHandler`
- 语言参数：`--parakeet_tdt_language`（可选）
- 未指定语言时支持自动语言检测
- 声明支持的语言列表（25 种欧洲语言）：
  - `en`、`de`、`fr`、`es`、`it`、`pt`、`nl`、`pl`、`ru`、`uk`、`cs`、`sk`、`hu`、`ro`、`bg`、`hr`、`sl`、`sr`、`da`、`no`、`sv`、`fi`、`et`、`lv`、`lt`
- 后端行为：
  - 在 macOS / MPS 上：MLX（`mlx-community/parakeet-tdt-0.6b-v3`）
  - 在 CUDA / CPU 上：nano-parakeet（`nvidia/parakeet-tdt-0.6b-v3`）

### 6) Paraformer（`--stt paraformer`）

- 处理器：`ParaformerSTTHandler`
- 模型参数：`--paraformer_stt_model_name`
- 默认模型：`paraformer-zh`
- 当前参数类中没有专属的语言参数
- 实际支持：
  - 取决于所选的 FunASR 模型 checkpoint
  - 默认设置偏向中文（`zh`）

### 7) OpenAI 兼容端点（`--stt openai`）

- 处理器：`OpenAICompatibleSTTHandler`
- 端点：`POST /v1/audio/transcriptions`
- 上传：16 kHz 单声道 PCM16 WAV
- 支持 JSON（`{"text": "..."}`）和纯文本响应
- 每个流水线至多保留一个尽力而为的渐进式（progressive）请求在途，而最终请求独立提交；过期的轮次过滤仍然适用
- 参见 [OpenAI 兼容 STT](../../../docs/openai-compatible-stt-CN.md)

## 语言缩写（STT 处理器中出现的类 ISO 代码）

| 代码 | 语言 |
|---|---|
| `en` | 英语 English |
| `fr` | 法语 French |
| `es` | 西班牙语 Spanish |
| `zh` | 中文 Chinese |
| `ja` | 日语 Japanese |
| `ko` | 韩语 Korean |
| `hi` | 印地语 Hindi |
| `de` | 德语 German |
| `pt` | 葡萄牙语 Portuguese |
| `pl` | 波兰语 Polish |
| `it` | 意大利语 Italian |
| `nl` | 荷兰语 Dutch |
| `ru` | 俄语 Russian |
| `uk` | 乌克兰语 Ukrainian |
| `cs` | 捷克语 Czech |
| `sk` | 斯洛伐克语 Slovak |
| `hu` | 匈牙利语 Hungarian |
| `ro` | 罗马尼亚语 Romanian |
| `bg` | 保加利亚语 Bulgarian |
| `hr` | 克罗地亚语 Croatian |
| `sl` | 斯洛文尼亚语 Slovenian |
| `sr` | 塞尔维亚语 Serbian |
| `da` | 丹麦语 Danish |
| `no` | 挪威语 Norwegian |
| `sv` | 瑞典语 Swedish |
| `fi` | 芬兰语 Finnish |
| `et` | 爱沙尼亚语 Estonian |
| `lv` | 拉脱维亚语 Latvian |
| `lt` | 立陶宛语 Lithuanian |
| `auto` | 每句话自动语言检测 |

## 用法示例

### Whisper（Transformers）

```bash
speech-to-speech serve --stt whisper --language en
speech-to-speech serve --stt whisper --language auto
```

### Whisper MLX（LightningWhisperMLX）

```bash
speech-to-speech serve --stt whisper-mlx --language auto --device mps
```

### MLX Audio Whisper

```bash
speech-to-speech serve --stt mlx-audio-whisper \
  --mlx_audio_whisper_model_name mlx-community/whisper-large-v3-turbo \
  --language auto
```

### Faster-Whisper

```bash
speech-to-speech serve --stt faster-whisper \
  --faster_whisper_stt_model_name large-v3 \
  --faster_whisper_stt_gen_language en
```

### Parakeet TDT

```bash
speech-to-speech serve --stt parakeet-tdt --parakeet_tdt_device auto
speech-to-speech serve --stt parakeet-tdt --parakeet_tdt_language de
```

配合实时转写（MLX 或 CUDA / nano-parakeet 后端）：

```bash
speech-to-speech serve --stt parakeet-tdt \
  --enable_live_transcription \
  --live_transcription_update_interval 0.25
```

### Paraformer

```bash
speech-to-speech serve --stt paraformer --paraformer_stt_model_name paraformer-zh
```
