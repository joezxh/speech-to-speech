# API 参考

## Python 接口

class VoxCPM(*voxcpm\_model\_path*, *zipenhancer\_model\_path='iic/speech\_zipenhancer\_ans\_multiloss\_16k\_base'*, *enable\_denoiser=True*, *optimize=True*, *device=None*, *lora\_config=None*, *lora\_weights\_path=None*)
:   从本地模型目录初始化 VoxCPM。

    模型架构（`voxcpm` 或 `voxcpm2`）会根据 `config.json` 中的 `architecture` 字段自动检测。

    参数:
    :   - **voxcpm\_model\_path** (*str*) -- 包含权重、配置与分词器文件的本地模型目录路径。
        - **zipenhancer\_model\_path** (*str**|**None*) -- ModelScope 降噪模型 id 或本地路径。设为 `None` 可完全跳过降噪器。
        - **enable\_denoiser** (*bool*) -- 是否初始化 ZipEnhancer 降噪流水线。
        - **optimize** (*bool*) -- 启用 `torch.compile` 加速。若用于调试或处于不受支持的平台，请关闭该选项。此优化主要对 CUDA 场景有意义。
        - **device** (*str**|**None*) -- 运行时设备。使用 `None` 或 `"auto"` 可启用自动回退（`cuda -> mps -> cpu`），也可以显式指定 `"cpu"`、`"mps"`、`"cuda"` 或 `"cuda:0"`。显式指定时若不可用会直接报错，而不是静默回退。
        - **lora\_config** (*LoRAConfig**|**None*) -- LoRA 配置。若只提供 `lora_weights_path` 而未提供此项，将自动创建默认配置（`enable_lm=True`、`enable_dit=True`）。
        - **lora\_weights\_path** (*str**|**None*) -- 预训练 LoRA 权重路径（`.pth` 文件，或包含 `lora_weights.ckpt` 的目录）。

    ```
    model = VoxCPM(
        voxcpm_model_path="/path/to/VoxCPM2",
        enable_denoiser=False,
        device="auto",
    )
    ```

classmethod VoxCPM.from\_pretrained(*hf\_model\_id='openbmb/VoxCPM2'*, *load\_denoiser=True*, *zipenhancer\_model\_id='iic/speech\_zipenhancer\_ans\_multiloss\_16k\_base'*, *cache\_dir=None*, *local\_files\_only=False*, *optimize=True*, *device=None*, *lora\_config=None*, *lora\_weights\_path=None*, *\*\*kwargs*)
:   从 Hugging Face Hub 快照实例化 `VoxCPM`。首次使用时会自动下载模型权重。

    参数:
    :   - **hf\_model\_id** (*str*) -- Hugging Face 仓库 id（例如 `"openbmb/VoxCPM2"`）或本地目录路径。
        - **load\_denoiser** (*bool*) -- 是否初始化降噪流水线。
        - **zipenhancer\_model\_id** (*str*) -- 降噪模型 id 或本地路径。当 `load_denoiser=False` 时忽略。
        - **cache\_dir** (*str**|**None*) -- 快照下载的自定义缓存目录。
        - **local\_files\_only** (*bool*) -- 若为 `True`，仅使用本地文件，不尝试下载。
        - **optimize** (*bool*) -- 启用 `torch.compile` 加速。这主要是一项面向 CUDA 的优化。
        - **device** (*str**|**None*) -- 运行时设备。`None` / `"auto"` 会使用自动回退。显式指定 `"cpu"`、`"mps"`、`"cuda"`、`"cuda:0"` 等值时会进行校验，且不会自动回退。
        - **lora\_config** (*LoRAConfig**|**None*) -- 微调模型的 LoRA 配置。
        - **lora\_weights\_path** (*str**|**None*) -- LoRA 权重路径。若提供，将在初始化后加载 LoRA。

    返回:
    :   已初始化的 VoxCPM 实例。

    返回类型:
    :   [VoxCPM](#VoxCPM "VoxCPM")

    抛出:
    :   **ValueError** -- 当 `hf_model_id` 为空时。

    ```
    model = VoxCPM.from_pretrained(
        "openbmb/VoxCPM2",
        load_denoiser=False,
        device="auto",
    )
    ```

VoxCPM.generate(*text*, *prompt\_wav\_path=None*, *prompt\_text=None*, *reference\_wav\_path=None*, *cfg\_value=2.0*, *inference\_timesteps=10*, *min\_len=2*, *max\_len=4096*, *normalize=False*, *denoise=False*, *retry\_badcase=True*, *retry\_badcase\_max\_times=3*, *retry\_badcase\_ratio\_threshold=6.0*)
:   从文本合成语音。

    参数:
    :   - **text** (*str*) -- 待合成的输入文本。用于 Voice Design 时，在括号中加入控制指令，例如：`"(warm female voice)Hello"`。
        - **prompt\_wav\_path** (*str**|**None*) -- 延续式克隆的 prompt 音频路径，须与 `prompt_text` 配对。Hi-Fi 克隆时可与 `reference_wav_path` 组合使用。
        - **prompt\_text** (*str**|**None*) -- prompt 音频的逐字转写，必须与 `prompt_wav_path` 同时提供。
        - **reference\_wav\_path** (*str**|**None*) -- 独立音色克隆的参考音频路径（**仅 VoxCPM 2**）。可单独使用，或与 `prompt_wav_path` + `prompt_text` 组合。
        - **cfg\_value** (*float*) -- 引导强度。数值越高越严格遵循条件；越低变化越大。建议 1.0–3.0。
        - **inference\_timesteps** (*int*) -- 扩散步数。步数越多细节越好、速度越慢。建议 4–30。
        - **min\_len** (*int*) -- 模型 token 意义上的最短音频长度。
        - **max\_len** (*int*) -- 生成时的最大 token 长度。输出很长时可增大。
        - **normalize** (*bool*) -- 生成前进行文本规范化（展开数字、日期等）。
        - **denoise** (*bool*) -- 生成前对 prompt/参考音频降噪。需已加载降噪器。
        - **retry\_badcase** (*bool*) -- 当生成音频时长异常偏短或偏长时自动重试。
        - **retry\_badcase\_max\_times** (*int*) -- 坏例重试的最大次数。
        - **retry\_badcase\_ratio\_threshold** (*float*) -- 坏例检测用的音频与文本时长比阈值。

    返回:
    :   一维波形数组（float32）。采样率见 `model.tts_model.sample_rate`。

    返回类型:
    :   numpy.ndarray

    抛出:
    :   - **ValueError** -- 当 `text` 为空时。
        - **ValueError** -- 当 `prompt_wav_path` 与 `prompt_text` 未同时提供或同时为 `None` 时。
        - **ValueError** -- 当在 VoxCPM 1.x 模型上使用 `reference_wav_path` 时。
        - **FileNotFoundError** -- 当音频文件路径不存在时。

    ```
    # Voice Design
    wav = model.generate(
        text="(warm female voice)Hello from VoxCPM!",
        cfg_value=2.0,
    )

    # Reference-only cloning (VoxCPM 2)
    wav = model.generate(
        text="Hello from VoxCPM!",
        reference_wav_path="speaker.wav",
    )

    # Hi-Fi cloning
    wav = model.generate(
        text="Hello from VoxCPM!",
        prompt_wav_path="speaker.wav",
        prompt_text="Exact transcript of speaker.wav.",
        reference_wav_path="speaker.wav",
    )
    ```

VoxCPM.generate\_streaming(*text*, *prompt\_wav\_path=None*, *prompt\_text=None*, *reference\_wav\_path=None*, *cfg\_value=2.0*, *inference\_timesteps=10*, *min\_len=2*, *max\_len=4096*, *normalize=False*, *denoise=False*, *retry\_badcase=True*, *retry\_badcase\_max\_times=3*, *retry\_badcase\_ratio\_threshold=6.0*)
:   接口与 [`generate()`](#VoxCPM.generate "VoxCPM.generate") 相同，但返回以增量方式产出音频块的生成器。

    所有参数与 [`generate()`](#VoxCPM.generate "VoxCPM.generate") 一致。

    返回:
    :   产出 float32 一维波形块的生成器。

    返回类型:
    :   Generator[numpy.ndarray, None, None]

    ```
    import numpy as np

    chunks = []
    for chunk in model.generate_streaming(text="Streaming output."):
        chunks.append(chunk)
    wav = np.concatenate(chunks)
    ```

VoxCPM.load\_lora(*lora\_weights\_path*)
:   从检查点文件或目录加载 LoRA 权重。

    参数:
    :   **lora\_weights\_path** (*str*) -- LoRA 权重路径（`.pth` 文件，或包含 `lora_weights.ckpt` 的目录）。

    返回:
    :   `(loaded_keys, skipped_keys)` — 已加载与已跳过参数名的列表。

    返回类型:
    :   tuple[list[str], list[str]]

    抛出:
    :   **RuntimeError** -- 当模型未以 LoRA 配置初始化时。

VoxCPM.unload\_lora()
:   将所有 LoRA 权重重置为初始状态（等效清零）。LoRA 层仍保留在模型中但不起作用。

VoxCPM.set\_lora\_enabled(*enabled*)
:   在不卸载权重的情况下启用或禁用 LoRA 层。

    参数:
    :   **enabled** (*bool*) -- `True` 启用 LoRA；`False` 仅使用基座模型。

VoxCPM.get\_lora\_state\_dict()
:   获取当前 LoRA 参数。

    返回:
    :   包含全部 `lora_A` 与 `lora_B` 参数的状态字典。

    返回类型:
    :   dict

VoxCPM.lora\_enabled: bool
:   若当前模型已加载 LoRA 配置则为 `True`。

---

## 命令行接口

`voxcpm` 命令提供三个子命令。默认模型：`openbmb/VoxCPM2`。

### 子命令

voxcpm design
:   无需参考音频，从文本生成语音。可选使用 `--control` 描述目标音色。

    ```
    voxcpm design --text "Hello world" --output out.wav
    voxcpm design --text "Hello world" --control "warm female voice" --output out.wav
    ```

voxcpm clone
:   使用参考音频，或带转写的 prompt 音频进行声音克隆。

    ```
    # Reference-only cloning (VoxCPM 2)
    voxcpm clone --text "Hello" --reference-audio ref.wav --output out.wav

    # Hi-Fi cloning
    voxcpm clone --text "Hello" \
        --prompt-audio ref.wav --prompt-text "Transcript of ref.wav" \
        --reference-audio ref.wav --output out.wav

    # With style control
    voxcpm clone --text "Hello" --reference-audio ref.wav \
        --control "speaking slowly" --output out.wav
    ```

voxcpm batch
:   处理文本文件，每行生成一个独立的输出 WAV（`output_001.wav`、`output_002.wav`、……）。

    ```
    voxcpm batch --input texts.txt --output-dir ./outs
    voxcpm batch --input texts.txt --output-dir ./outs --reference-audio ref.wav
    ```

### 参数说明

**生成**

--text, -t <TEXT>
:   待合成文本。

--control <INSTRUCTION>
:   音色设计或风格控制的指令（例如 `"warm female voice"`）。不可与 `--prompt-text` 同时使用。

--cfg-value <FLOAT>
:   CFG 引导强度。默认：`2.0`。建议：1.0–3.0。

--inference-timesteps <INT>
:   扩散步数。默认：`10`。建议：4–30。

--normalize
:   启用文本规范化（展开数字、日期等）。

**Prompt 与参考音频**

--prompt-audio, -pa <PATH>
:   延续模式下的 prompt 音频文件。需要 `--prompt-text` 或 `--prompt-file`。

--prompt-text, -pt <TEXT>
:   prompt 音频的文本转写。

--prompt-file <PATH>
:   包含 prompt 转写的文本文件（`--prompt-text` 的替代方式）。

--reference-audio, -ra <PATH>
:   独立音色克隆的参考音频（仅 VoxCPM 2）。

--denoise
:   生成前使用 ZipEnhancer 对 prompt/参考音频降噪。

**模型加载**

--model-path <PATH>
:   本地模型目录。若设置则忽略 `--hf-model-id`。

--hf-model-id <ID>
:   Hugging Face 仓库 id。默认：`openbmb/VoxCPM2`。

--device <DEVICE>
:   运行时设备选择。支持 `auto`、`cpu`、`mps`、`cuda`，以及像 `cuda:0` 这样的带索引 CUDA 设备。`auto` 会优先按 `cuda -> mps -> cpu` 选择。显式指定的值若不可用会直接报错，而不是静默回退。

--cache-dir <PATH>
:   Hub 下载的缓存目录。

--local-files-only
:   仅使用本地文件，不从 Hub 下载。

--no-denoiser
:   跳过加载降噪模型。

--no-optimize
:   禁用 `torch.compile` 加速。这通常适用于调试、不受支持的平台，以及非 CUDA 环境。

--zipenhancer-path <PATH>
:   自定义 ZipEnhancer 模型 id 或本地路径。

**LoRA**

--lora-path <PATH>
:   LoRA 权重目录路径。

--lora-r <INT>
:   LoRA 秩 r。默认：`32`。

--lora-alpha <INT>
:   LoRA alpha（缩放为 alpha / r）。默认：`16`。

--lora-dropout <FLOAT>
:   LoRA dropout 比率（0.0–1.0）。默认：`0.0`。

--lora-disable-lm
:   在 LM 层禁用 LoRA。

--lora-disable-dit
:   在 DiT 层禁用 LoRA。

--lora-enable-proj
:   在投影层启用 LoRA。

备注

旧版扁平 CLI（`voxcpm --text "..." --output out.wav`）仍可用但已弃用，建议改用子命令形式。
