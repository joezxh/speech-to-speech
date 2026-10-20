> 🌐 Language / 语言：**中文版** · [English](./README.md)

# TTS 概览

## 可用的 TTS 模式（`--tts`）

`s2s_pipeline.py` 在运行时支持的取值：

- `chatTTS` → `chatTTS_handler.py`
- `facebookMMS` → `facebookmms_handler.py`
- `pocket` → `pocket_tts_handler.py`
- `kokoro` → `kokoro_handler.py`
- `omnivoice` → `omnivoice_handler.py`
- `qwen3` → `qwen3_tts_handler.py`
- `openai` → `openai_compatible_handler.py`
- `supertonic` → `supertonic_tts_handler.py`

已弃用的 TTS 实现（包括 MeloTTS）位于 [`../../../archive/TTS`](../../../archive/TTS)，且不再接入 `s2s_pipeline.py`。

## 用法

### 1) ChatTTS（`--tts chatTTS`）

主要参数前缀：`--chat_tts_*`

```bash
speech-to-speech serve \
  --tts chatTTS \
  --chat_tts_device cuda \
  --chat_tts_stream true \
  --chat_tts_chunk_size 512
```

### 2) Facebook MMS（`--tts facebookMMS`）

主要参数前缀：`--facebook_mms_*` 加 `--tts_language`

```bash
speech-to-speech serve \
  --tts facebookMMS \
  --facebook_mms_device cuda \
  --tts_language en
```

该处理器将 STT 语言代码（如 `en`、`fr`、`es`）映射到 MMS 模型后缀（如 `eng`、`fra`、`spa`），并在语言变化时重新加载模型。

### 3) Pocket TTS（`--tts pocket`）

主要参数前缀：`--pocket_tts_*`

```bash
speech-to-speech serve \
  --tts pocket \
  --pocket_tts_voice jean \
  --pocket_tts_device cpu \
  --pocket_tts_sample_rate 16000
```

可用的预设 voice 包括：
`alba`、`marius`、`javert`、`jean`、`fantine`、`cosette`、`eponine`、`azelma`。

### 4) Kokoro（`--tts kokoro`）

主要参数前缀：`--kokoro_*`

```bash
speech-to-speech serve \
  --tts kokoro \
  --kokoro_device auto \
  --kokoro_voice bm_fable \
  --kokoro_lang_code b
```

行为：

- 在 Apple Silicon 上使用 MLX 后端（`mlx-community/Kokoro-82M-bf16`）
- 在其他情况下使用原生 kokoro pipeline（`hexgrad/Kokoro-82M`）
- 可根据 STT 语言代码映射自动切换 voice / 语言

### 5) Qwen3-TTS（`--tts qwen3`）

主要参数前缀：`--qwen3_tts_*`

```bash
speech-to-speech serve \
  --tts qwen3 \
  --qwen3_tts_model_name Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice \
  --qwen3_tts_device cuda \
  --qwen3_tts_backend ggml \
  --qwen3_tts_speaker Aiden \
  --qwen3_tts_language auto \
  --qwen3_tts_non_streaming_mode True
```

行为：

- 在非 macOS 平台上使用 `faster-qwen3-tts`，默认 GGML 后端。传入 `--qwen3_tts_backend torch` 以改用 CUDA-graphs 后端。
- 通过 `--qwen3_tts_ggml_quantization BF16|Q8_0|Q4_K_M|F32` 支持 GGML 量化选择。
- 通过 `--qwen3_tts_gguf_talker_path` 和 `--qwen3_tts_gguf_codec_path` 接受本地 talker / codec 的 GGUF 对。
- 当 GGML voice 克隆使用原始参考音频时，自动缓存 `.spk` 和 `.rvq` voice 引用。设置 `--qwen3_tts_ref_cache_dir` 以覆盖默认的 `~/.cache/faster-qwen3-ts/qwentts_refs` 位置。
- 通过 `--qwen3_tts_ref_spk` 和可选的 `--qwen3_tts_ref_rvq` 复用预计算的 GGML 引用。
- 在 Apple Silicon 上使用 `mlx-audio`，并自动将 `Qwen/...` 模型 ID 映射到 `mlx-community/...`，除非模型名已固定后缀，否则默认 `6bit` MLX 变体。
- 在 Apple Silicon 上通过 `--qwen3_tts_mlx_quantization bf16|4bit|6bit|8bit` 支持 MLX 量化覆盖。
- 保持现有的 voice 克隆 / 自定义 voice / voice 设计处理器流程不变。
- 默认使用 CustomVoice 模型，说话人 `Aiden`，因此不需要参考音频。Voice 克隆 / 基础模型仍可使用 `--qwen3_tts_ref_audio`。

Linux GGML 安装说明：

- 默认的 PyPI `qwentts-cpp-python` wheel 针对 CUDA 12.8 和 `manylinux_2_39`（例如 Ubuntu 24.04）。
- 如果该 wheel 与你的 CUDA 运行时或 glibc 不匹配，在安装 `speech-to-speech` 之前安装 Hugging Face wheelhouse 的某个构建。

```bash
pip install "qwentts-cpp-python==0.3.1+cu130" \
  -f https://huggingface.co/datasets/andito/qwentts-cpp-python-wheels/tree/main/whl/cu130
pip install speech-to-speech
```

可用的 wheelhouse 目录包括 `cu124`、`cu128`、`cu130` 和 `cpu`。

从公共模型解析器选择一个量化 GGUF：

```bash
speech-to-speech serve \
  --tts qwen3 \
  --qwen3_tts_backend ggml \
  --qwen3_tts_model_name Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice \
  --qwen3_tts_ggml_quantization Q4_K_M \
  --qwen3_tts_speaker Aiden
```

通过同时提供 talker 和 codec 路径加载本地 GGUF 文件。保持模型名与本地 talker 的模型类型一致，以便处理器选择正确的生成模式：

```bash
speech-to-speech serve \
  --tts qwen3 \
  --qwen3_tts_backend ggml \
  --qwen3_tts_model_name Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign \
  --qwen3_tts_gguf_talker_path /models/qwen-talker-1.7b-voicedesign-Q4_K_M.gguf \
  --qwen3_tts_gguf_codec_path /models/qwen-tokenizer-12hz-BF16.gguf \
  --qwen3_tts_instruct "Warm, confident narrator"
```

对于 GGML voice 克隆，原始参考在首次使用时被缓存：

```bash
speech-to-speech serve \
  --tts qwen3 \
  --qwen3_tts_backend ggml \
  --qwen3_tts_model_name Qwen/Qwen3-TTS-12Hz-1.7B-Base \
  --qwen3_tts_ref_audio /voices/freeman.wav \
  --qwen3_tts_ref_text "The transcript for the reference audio." \
  --qwen3_tts_ref_cache_dir /voices/cache
```

自动缓存条目对其 `.spk`、`.rvq` 和 `.json` 文件名使用相同的 SHA-256 缓存键。检查缓存目录中匹配的键，并将下面的 `CACHE_KEY` 替换为该文件名的主干。然后你可以单独传入它的 `.spk` 用于仅说话人条件化，或将它与对应的 `.rvq` 码和转写一起用于 ICL 条件化：

```bash
speech-to-speech serve \
  --tts qwen3 \
  --qwen3_tts_backend ggml \
  --qwen3_tts_model_name Qwen/Qwen3-TTS-12Hz-1.7B-Base \
  --qwen3_tts_ref_spk /voices/cache/CACHE_KEY.spk \
  --qwen3_tts_ref_rvq /voices/cache/CACHE_KEY.rvq \
  --qwen3_tts_ref_text "The transcript for the reference audio."
```

原始 `--qwen3_tts_ref_audio` 与缓存的 `--qwen3_tts_ref_spk` / `--qwen3_tts_ref_rvq` 输入互斥。`.rvq` 输入需要同时提供 `.spk` 和参考文本。

Apple Silicon 使用默认 6-bit MLX 变体的示例：

```bash
speech-to-speech serve \
  --tts qwen3 \
  --qwen3_tts_model_name Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice \
  --qwen3_tts_speaker Aiden
```

你可以覆盖默认并显式选择 `bf16`、`4bit` 或 `8bit`：

```bash
speech-to-speech serve \
  --tts qwen3 \
  --qwen3_tts_model_name Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice \
  --qwen3_tts_mlx_quantization 4bit \
  --qwen3_tts_speaker Aiden
```

要并排对 Apple Silicon 的 MLX 变体做基准测试：

```bash
.venv/bin/python benchmark_tts.py \
  --handlers qwen3 \
  --iterations 3 \
  --qwen3_mlx_quantizations bf16 4bit 6bit 8bit
```

这将为 `qwen3[bf16]`、`qwen3[4bit]`、`qwen3[6bit]` 和 `qwen3[8bit]` 分别运行基准条目。

### 6) OpenAI 兼容端点（`--tts openai`）

该处理器把文本发送到 `POST /v1/audio/speech`。它支持流式原始 PCM16 和完整的 WAV 响应，将它们重采样到流水线的 16 kHz 格式，并在响应生成被取消时关闭活动传输。默认设置面向 vLLM-Omni 上的 Qwen3-TTS。

服务器命令和所有相关参数见 [OpenAI 兼容 TTS](../../../docs/openai-compatible-tts-CN.md)。

### 7) OmniVoice（`--tts omnivoice`）

主要参数前缀：`--omnivoice_*`

安装可选依赖，并选择你的 PyTorch 安装所支持的设备。本示例使用 Linux 或 Windows 上的 CUDA；在 Apple Silicon 上使用 `mps`，或在启用了 Intel XPU 的 PyTorch 安装上使用 `xpu`：

```bash
pip install "speech-to-speech[omnivoice]"
speech-to-speech serve \
  --tts omnivoice \
  --omnivoice_model_name k2-fsa/OmniVoice \
  --omnivoice_device cuda \
  --omnivoice_dtype float16 \
  --omnivoice_ref_audio /voices/reference.wav \
  --omnivoice_ref_text "Transcript of the reference clip."
```

参考在处理器设置期间被编码一次，生成的 voice 克隆提示被每个文本块复用。要在不重新编码参考的情况下复用上游的 `VoiceClonePrompt.save(...)` 文件，用以下两个参考参数替换：

```bash
--omnivoice_voice_clone_prompt /voices/saved-prompt.pt
```

Voice 设计省略克隆参数并提供一个指令：

```bash
speech-to-speech serve \
  --tts omnivoice \
  --omnivoice_device mps \
  --omnivoice_instruct "female, low pitch, British accent"
```

对于自动 voice，省略 `--omnivoice_ref_audio`、`--omnivoice_voice_clone_prompt` 和 `--omnivoice_instruct`。`--omnivoice_language` 固定一个语言名称或代码；当它未设置时，处理器转发每个流水线话语所携带的语言代码。`--omnivoice_num_steps` 控制扩散步数（默认 32），`--omnivoice_speed` 控制语速。

支持的上游设备值包括 CUDA（`cuda` 或 `cuda:0`）、Apple Silicon（`mps`）和 Intel GPU（`xpu`）。用 `--omnivoice_dtype` 根据设备支持选择 `float16`、`bfloat16` 或 `float32`。

`speech-to-speech[omnivoice]` 依赖集在 Linux、Windows 和 macOS 上都受支持。在非 macOS 平台上，`faster-qwen3-tts>=0.4.0` 和 OmniVoice 共享 Transformers 5，因此该扩展可以与内置 Qwen3 后端一起安装。Linux 默认使用 Qwen3 的 GGML 扩展；当默认的 CUDA 12.8 / `manylinux_2_39` wheel 与宿主机不匹配时，按上文安装匹配的 `qwentts-cpp-python` wheel。Intel XPU 需要匹配的 Intel PyTorch 构建。

OmniVoice 返回完整的 24 kHz 浮点数组。该处理器将它们下采样到 16 kHz，裁剪为 `int16`，然后发出固定大小的块。这是播放分块，而非模型流式：上游 `generate()` 是阻塞的，因此到首个音频的时间包含了整个话语的合成，生成期间的打断会在阻塞调用返回后丢弃结果。上游在其加速基准中报告的实时因子低至 0.025，但实际延迟取决于设备、dtype、扩散步数和文本长度。

> [!WARNING]
> [OmniVoice 代码](https://github.com/k2-fsa/OmniVoice) 是 Apache-2.0，但 [`k2-fsa/OmniVoice` 预训练权重](https://huggingface.co/k2-fsa/OmniVoice) 由于训练数据限制是 CC-BY-NC，且不获授权用于商业用途。Voice 克隆需要授权和同意。未经授权的克隆、 impersonation、欺诈、诈骗以及其他非法或不道德的使用都被上游模型的安全声明所禁止。

### 8) Supertonic（`--tts supertonic`）

主要参数前缀：`--supertonic_tts_*`

```bash
speech-to-speech serve \
  --tts supertonic \
  --supertonic_tts_voice M1 \
  --supertonic_tts_speed 1.0
```

行为：

- 使用 Supertone 的 ONNX runtime 模型支持实时文本转语音
- 将模型下载到本地 `~/.cache/supertonic3/`
- 支持 10 个内置 voice 模型：`M1`-`M5` 和 `F1`-`F5`
- 在支持时使用每话语语言代码，否则回退到 `--supertonic_tts_lang`
- 原生以 44.1kHz 输出，但在流水线中被下采样到 16kHz 以统一播放

用以下命令安装可选依赖：

```bash
pip install "speech-to-speech[supertonic]"
```

## 配置

### 低延迟 GPU 配置

```bash
speech-to-speech serve \
  --stt whisper \
  --tts pocket
```

### Apple Silicon 配置

```bash
speech-to-speech local \
  --mac-optimal-settings
```

`--tts pocket`、`--tts kokoro` 和 `--tts omnivoice` 在 macOS 上也是有效选项。
