from dataclasses import dataclass, field


@dataclass
class CosyVoiceTTSHandlerArguments:
    cosyvoice_tts_model_name: str = field(
        default="iic/CosyVoice2-0.5B",
        metadata={
            "help": "CosyVoice2 model id (ModelScope, e.g. 'iic/CosyVoice2-0.5B') or a local model directory."
        },
    )
    cosyvoice_tts_device: str = field(
        default="cuda",
        metadata={"help": "Device for CosyVoice. Default is 'cuda'."},
    )
    cosyvoice_tts_speaker: str = field(
        default="中文女",
        metadata={
            "help": "Preset CosyVoice2 speaker. One of: 中文女, 中文男, 英文女, 英文男, 日语男."
        },
    )
    cosyvoice_tts_instruct: str = field(
        default="",
        metadata={
            "help": "Free-text instruct prompt for dialect/emotion control, e.g. "
            "'用四川话说这句话' or '用悲伤的语气说'. Empty = neutral preset voice."
        },
    )
    cosyvoice_tts_stream: bool = field(
        default=False,
        metadata={"help": "Stream CosyVoice output. Default False (non-streaming)."},
    )
    cosyvoice_tts_load_jit: bool = field(
        default=False,
        metadata={"help": "Load CosyVoice JIT graph. Default False."},
    )
    cosyvoice_tts_load_trt: bool = field(
        default=False,
        metadata={"help": "Load CosyVoice TensorRT engine. Default False."},
    )
    cosyvoice_tts_fp16: bool = field(
        default=True,
        metadata={"help": "Use fp16 inference for CosyVoice. Default True."},
    )
    cosyvoice_tts_chunk_size: int = field(
        default=512,
        metadata={"help": "PCM chunk size (samples) yielded to the pipeline. Default 512 (16 kHz)."},
    )
