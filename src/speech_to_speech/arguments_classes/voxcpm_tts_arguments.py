from dataclasses import dataclass, field


@dataclass
class VoxCPMTTSHandlerArguments:
    voxcpm_tts_model_name: str = field(
        default="openbmb/VoxCPM2",
        metadata={
            "help": (
                "VoxCPM checkpoint to use (HuggingFace Hub ID or local path). "
                "Options: 'openbmb/VoxCPM2' (2B, 48 kHz), 'openbmb/VoxCPM1.5' (~0.8B, 44.1 kHz), "
                "'openbmb/VoxCPM-0.5B' (~0.5B, 16 kHz). Default is 'openbmb/VoxCPM2'."
            )
        },
    )
    voxcpm_tts_device: str = field(
        default="auto",
        metadata={"help": "Device for VoxCPM inference: 'auto', 'cuda', 'mps' or 'cpu'. Default is 'auto'."},
    )
    voxcpm_tts_dtype: str = field(
        default="auto",
        metadata={
            "help": "Data type for VoxCPM inference. Options: 'auto', 'float16', 'bfloat16', 'float32'. Default is 'auto'."
        },
    )
    voxcpm_tts_cfg_value: float = field(
        default=2.0,
        metadata={"help": "Classifier-free guidance scale for VoxCPM. Official range is 1.0-3.0. Default is 2.0."},
    )
    voxcpm_tts_inference_timesteps: int = field(
        default=10,
        metadata={"help": "Diffusion sampling steps for VoxCPM. Range is 1-100. Default is 10."},
    )
    voxcpm_tts_normalize: bool = field(
        default=True,
        metadata={"help": "Apply VoxCPM text normalization before synthesis. Default is true."},
    )
    voxcpm_tts_denoise: bool = field(
        default=False,
        metadata={"help": "Enable VoxCPM sampling-time denoising. Default is false."},
    )
    voxcpm_tts_load_denoiser: bool = field(
        default=False,
        metadata={"help": "Load the VoxCPM denoiser at startup (extra VRAM). Default is false."},
    )
    voxcpm_tts_seed: int | None = field(
        default=None,
        metadata={"help": "Optional random seed for reproducible VoxCPM sampling. Default is unset."},
    )
    voxcpm_tts_ref_audio: str | None = field(
        default=None,
        metadata={"help": "Optional reference audio path for VoxCPM voice cloning / voice design."},
    )
    voxcpm_tts_prompt_text: str | None = field(
        default=None,
        metadata={"help": "Transcript of the reference audio. Requires voxcpm_tts_ref_audio."},
    )
    voxcpm_tts_streaming: bool = field(
        default=True,
        metadata={"help": "Stream VoxCPM audio chunks while synthesizing. Default is true."},
    )
