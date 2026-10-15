from dataclasses import dataclass, field


@dataclass
class SenseVoiceSTTHandlerArguments:
    sensevoice_stt_model_name: str = field(
        default="SenseVoiceSmall",
        metadata={
            "help": "SenseVoice model name passed to FunASR AutoModel. "
            "Defaults to 'SenseVoiceSmall' (multilingual: zh/en/yue/ja/ko, with emotion/event tags)."
        },
    )
    sensevoice_stt_device: str = field(
        default="cuda",
        metadata={"help": "Device for SenseVoice. Default is 'cuda'."},
    )
    sensevoice_stt_language: str = field(
        default="auto",
        metadata={
            "help": "Language hint for SenseVoice. 'auto' detects among zh/en/yue/ja/ko. "
            "Set to 'zh' to force Mandarin."
        },
    )
    sensevoice_stt_use_itn: bool = field(
        default=True,
        metadata={"help": "Enable inverse text normalization (numbers/dates → spoken form). Default True."},
    )
