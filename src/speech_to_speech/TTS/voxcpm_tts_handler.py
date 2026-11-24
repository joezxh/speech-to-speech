"""VoxCPM (openbmb) text-to-speech backend.

One handler serves VoxCPM2 (2B), VoxCPM1.5 (~0.8B) and VoxCPM-0.5B; the
checkpoint differs, the API does not. Output is resampled from the model's
native rate to the pipeline contract: 16 kHz, mono, int16, 512-sample blocks.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from math import isfinite
from pathlib import Path
from threading import Event
from typing import Any

import numpy as np
import soxr

from speech_to_speech.model_registry import ModelWeightsMissingError
from speech_to_speech.pipeline.cancel_scope import CancelScope
from speech_to_speech.pipeline.console import console
from speech_to_speech.pipeline.handler_types import TTSIn, TTSOut
from speech_to_speech.pipeline.messages import AUDIO_RESPONSE_DONE, EndOfResponse
from speech_to_speech.pipeline.speculative_turns import SpeculativeTurnTracker
from speech_to_speech.TTS.base_tts_handler import BaseTTSHandler
from speech_to_speech.TTS.pcm_blocks import PCMBlockBuffer
from speech_to_speech.utils.utils import TORCH_DEVICES, resolve_device, validate_device

logger = logging.getLogger(__name__)

PIPELINE_SAMPLE_RATE = 16000
BLOCKSIZE = 512
DEFAULT_MODEL_NAME = "openbmb/VoxCPM2"
DEFAULT_NATIVE_SAMPLE_RATE = 48000
SUPPORTED_DTYPES = ("auto", "float16", "bfloat16", "float32")
# Official VoxCPM language coverage (Whisper-style codes). Language is inferred
# from the text, so these codes only describe capability to clients.
VOXCPM_LANGUAGE_CODES = frozenset(
    {
        "ar",
        "my",
        "zh",
        "da",
        "nl",
        "en",
        "fi",
        "fr",
        "de",
        "el",
        "he",
        "hi",
        "id",
        "it",
        "ja",
        "km",
        "ko",
        "lo",
        "ms",
        "no",
        "pl",
        "pt",
        "ru",
        "es",
        "sw",
        "sv",
        "tl",
        "th",
        "tr",
        "vi",
    }
)


class VoxCPMTTSHandler(BaseTTSHandler):
    def setup(
        self,
        should_listen: Event,
        model_name: str = DEFAULT_MODEL_NAME,
        device: str = "auto",
        dtype: str = "auto",
        cfg_value: float = 2.0,
        inference_timesteps: int = 10,
        normalize: bool = True,
        denoise: bool = False,
        load_denoiser: bool = False,
        seed: int | None = None,
        ref_audio: str | None = None,
        prompt_text: str | None = None,
        streaming: bool = True,
        cancel_scope: CancelScope | None = None,
        speculative_turns: SpeculativeTurnTracker | None = None,
        **_kwargs: object,
    ) -> None:
        self._validate(
            model_name=model_name,
            device=device,
            dtype=dtype,
            cfg_value=cfg_value,
            inference_timesteps=inference_timesteps,
            ref_audio=ref_audio,
            prompt_text=prompt_text,
        )

        self.should_listen = should_listen
        self.model_name = model_name
        self.device = device
        self.dtype = dtype
        self.streaming = bool(streaming)
        self.cancel_scope = cancel_scope
        self.speculative_turns = speculative_turns
        self._kwargs_fallback_used = False

        try:
            from voxcpm import VoxCPM
        except ImportError as exc:
            raise ImportError(
                "The VoxCPM package is not installed. Install it with "
                '`pip install "speech-to-speech[voxcpm]"` (voxcpm requires Python 3.10-3.12).'
            ) from exc

        self.model = self._load_model(VoxCPM, model_name, load_denoiser)
        self.sample_rate = self._detect_sample_rate(DEFAULT_NATIVE_SAMPLE_RATE)
        self._apply_device_and_dtype()

        self.gen_params: dict[str, Any] = {
            "cfg_value": cfg_value,
            "inference_timesteps": inference_timesteps,
            "normalize": normalize,
            "denoise": denoise,
        }
        if seed is not None:
            self.gen_params["seed"] = int(seed)
        if ref_audio:
            self.gen_params["prompt_wav_path"] = ref_audio
        if prompt_text:
            self.gen_params["prompt_text"] = prompt_text

        logger.info(
            "Loaded VoxCPM TTS model=%s device=%s dtype=%s sample_rate=%d streaming=%s denoiser=%s",
            model_name,
            getattr(self, "resolved_device", device),
            dtype,
            self.sample_rate,
            self.streaming,
            bool(load_denoiser),
        )

    # ── setup helpers ──────────────────────────────────────────────────
    @staticmethod
    def _validate(
        *,
        model_name: str,
        device: str,
        dtype: str,
        cfg_value: float,
        inference_timesteps: int,
        ref_audio: str | None,
        prompt_text: str | None,
    ) -> None:
        if not isinstance(model_name, str) or not model_name.strip():
            raise ValueError("voxcpm_tts_model_name must be a non-empty HuggingFace repo id or local path")
        if not isfinite(cfg_value) or cfg_value <= 0:
            raise ValueError(f"voxcpm_tts_cfg_value must be finite and > 0, got {cfg_value!r}")
        if not 1 <= inference_timesteps <= 100:
            raise ValueError(f"voxcpm_tts_inference_timesteps must be between 1 and 100, got {inference_timesteps!r}")
        if dtype not in SUPPORTED_DTYPES:
            raise ValueError(f"voxcpm_tts_dtype must be one of {', '.join(SUPPORTED_DTYPES)}; got {dtype!r}")
        validate_device(device, TORCH_DEVICES, "VoxCPM TTS")
        if ref_audio and not Path(ref_audio).expanduser().is_file():
            raise ValueError(f"voxcpm_tts_ref_audio does not exist: {ref_audio}")
        if prompt_text and not ref_audio:
            raise ValueError("voxcpm_tts_prompt_text requires voxcpm_tts_ref_audio")

    def _load_model(self, model_class: Any, model_name: str, load_denoiser: bool) -> Any:
        if _looks_like_local_path(model_name) and not Path(model_name).expanduser().exists():
            raise ModelWeightsMissingError(
                f"VoxCPM weights not found at {model_name!r}. "
                f"Download them with `huggingface-cli download {DEFAULT_MODEL_NAME}` "
                "or point voxcpm_tts_model_name at an existing checkpoint directory."
            )
        try:
            return model_class.from_pretrained(model_name, load_denoiser=load_denoiser)
        except TypeError:
            # Older voxcpm releases do not accept load_denoiser.
            logger.warning("VoxCPM.from_pretrained rejected load_denoiser; retrying with defaults")
            try:
                return model_class.from_pretrained(model_name)
            except Exception as exc:  # noqa: BLE001
                raise _download_error(model_name, exc) from exc
        except Exception as exc:  # noqa: BLE001
            raise _download_error(model_name, exc) from exc

    def _detect_sample_rate(self, default: int) -> int:
        for source in (self.model, getattr(self.model, "tts_model", None)):
            value = getattr(source, "sample_rate", None)
            if isinstance(value, int) and value > 0:
                return value
        value = getattr(self.model, "output_sample_rate", None)
        if isinstance(value, int) and value > 0:
            return value
        return default

    def _apply_device_and_dtype(self) -> None:
        try:
            self.resolved_device = resolve_device(self.device, TORCH_DEVICES, "VoxCPM TTS")
        except ValueError as exc:
            logger.warning("VoxCPM device resolution failed (%s); falling back to cpu", exc)
            self.resolved_device = "cpu"

        if not hasattr(self.model, "to"):
            return
        try:
            self.model.to(self.resolved_device)
        except Exception as exc:  # noqa: BLE001
            logger.warning("VoxCPM could not move to %s (%s); using the library default", self.resolved_device, exc)
            return
        if self.dtype == "auto":
            return
        try:
            import torch

            self.model.to(dtype=getattr(torch, self.dtype))
        except Exception as exc:  # noqa: BLE001
            logger.warning("VoxCPM could not apply dtype %s (%s); using the library default", self.dtype, exc)

    # ── synthesis ──────────────────────────────────────────────────────
    def _iter_model_audio(self, text: str, params: Mapping[str, Any]) -> Iterator[Any]:
        generate = self.model.generate_streaming if self.streaming else self.model.generate
        if self.streaming:
            yield from generate(text=text, **params)
        else:
            yield generate(text=text, **params)

    def _synthesize_chunks(self, text: str) -> Iterator[Any]:
        emitted = False
        try:
            for chunk in self._iter_model_audio(text, self.gen_params):
                emitted = True
                yield chunk
        except TypeError as exc:
            if emitted or not self.gen_params or self._kwargs_fallback_used:
                raise
            self._kwargs_fallback_used = True
            logger.warning("VoxCPM rejected generation kwargs (%s); retrying with text only", exc)
            yield from self._iter_model_audio(text, {})

    def process(self, tts_input: TTSIn) -> Iterator[TTSOut]:
        if isinstance(tts_input, EndOfResponse):
            if self._gate_end_of_response(tts_input):
                yield AUDIO_RESPONSE_DONE
            return

        if not self._admit_input(tts_input):
            return

        text = tts_input.text
        if not text.strip():
            return

        cancel_gen = self.cancel_scope.generation if self.cancel_scope else None
        console.print(f"[green]ASSISTANT: {text}")
        timer = self._latency_timer(tts_input, cancel_gen)

        resampler = (
            soxr.ResampleStream(self.sample_rate, PIPELINE_SAMPLE_RATE, 1, dtype="float32", quality="HQ")
            if self.sample_rate != PIPELINE_SAMPLE_RATE
            else None
        )
        blocks = PCMBlockBuffer(BLOCKSIZE)
        heard_audio = False

        def emit(samples: np.ndarray) -> Iterator[TTSOut]:
            for block in blocks.push(_to_pcm16(samples)):
                if self._is_stale(cancel_gen):
                    return
                timer.first_yield()
                yield block

        for chunk in self._synthesize_chunks(text):
            if self._is_stale(cancel_gen):
                logger.info("VoxCPM TTS output cancelled (interruption)")
                return
            samples = np.asarray(chunk, dtype=np.float32).reshape(-1)
            if samples.size == 0:
                continue
            if not heard_audio:
                heard_audio = True
                timer.first_provider_audio()
            converted = resampler.resample_chunk(samples) if resampler is not None else samples
            yield from emit(converted)

        if self._is_stale(cancel_gen):
            logger.info("VoxCPM TTS output cancelled (interruption)")
            return
        if not heard_audio:
            raise RuntimeError("VoxCPM returned no audio")

        if resampler is not None:
            yield from emit(resampler.resample_chunk(np.empty(0, dtype=np.float32), last=True))

        tail = next(blocks.flush(), None)
        if tail is not None:
            if tail.size < BLOCKSIZE:
                tail = np.pad(tail, (0, BLOCKSIZE - tail.size))
            timer.first_yield()
            yield tail


def _to_pcm16(samples: np.ndarray) -> np.ndarray:
    """Map mono float samples to the int16 range the pipeline expects."""
    pcm = np.clip(samples * 32767.0, -32768, 32767)
    return np.ascontiguousarray(pcm.astype(np.int16))


def _looks_like_local_path(model_name: str) -> bool:
    expanded = Path(model_name).expanduser()
    return expanded.is_absolute() or model_name.startswith((".", "~")) or "\\" in model_name


def _download_error(model_name: str, exc: BaseException) -> RuntimeError:
    return RuntimeError(
        f"VoxCPM could not load weights for {model_name!r}: {type(exc).__name__}: {exc}. "
        "Check the HuggingFace cache/network access, or pass a local checkpoint directory."
    )
