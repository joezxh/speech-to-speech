from __future__ import annotations

import logging
from threading import Event
from typing import Any, Iterator

import librosa
import numpy as np
import torch
from rich.console import Console

from speech_to_speech.baseHandler import BaseHandler
from speech_to_speech.pipeline.cancel_scope import CancelScope
from speech_to_speech.pipeline.handler_types import TTSIn, TTSOut
from speech_to_speech.pipeline.messages import AUDIO_RESPONSE_DONE, EndOfResponse
from speech_to_speech.pipeline.speculative_turns import SpeculativeTurnTracker

logger = logging.getLogger(__name__)
console = Console()

# CosyVoice2 synthesises at 24 kHz; the pipeline consumes 16 kHz int16 PCM.
COSYVOICE_SR = 24000
PIPELINE_SR = 16000

# Default reference audio for zero-shot voice cloning. It is bundled with the
# official CosyVoice source (copied into the image at /opt/cosyvoice-src) and
# provides a stable Chinese voice. Override with --cosyvoice_tts_prompt_wav.
DEFAULT_PROMPT_WAV = "/opt/cosyvoice-src/asset/zero_shot_prompt.wav"


class CosyVoiceTTSHandler(BaseHandler[TTSIn, TTSOut]):
    """
    Handles Text-to-Speech using Alibaba DAMO Academy's CosyVoice2 model.

    CosyVoice2 supports Chinese / English / Japanese / Korean and — crucially for
    this deployment — dialect and emotion control via the ``instruct`` prompt
    (e.g. "用四川话说这句话" or "用悲伤的语气说"). The voice timbre is cloned from a
    reference audio (``prompt_wav``) via zero-shot, so no preset-speaker embeddings
    (spk2info.pt) are required.

    The official CosyVoice source must be available on PYTHONPATH (it is not pip
    installable as a normal package); the Docker image copies it to
    /opt/cosyvoice-src and sets PYTHONPATH accordingly. CosyVoice2 itself auto-
    selects the CUDA device when available.
    """

    def setup(
        self,
        should_listen: Event,
        model_name: str = "iic/CosyVoice2-0.5B",
        device: str = "cuda",
        speaker: str = "中文女",
        instruct: str = "",
        prompt_wav: str | None = None,
        stream: bool = False,
        load_jit: bool = False,
        load_trt: bool = False,
        fp16: bool = False,
        chunk_size: int = 512,
        cancel_scope: CancelScope | None = None,
        speculative_turns: SpeculativeTurnTracker | None = None,
        gen_kwargs: dict[str, Any] | None = None,
        **_ignored: Any,
    ) -> None:
        self.should_listen = should_listen
        self.cancel_scope = cancel_scope
        self.speculative_turns = speculative_turns
        self.device = device
        self.speaker = speaker
        self.instruct = instruct or ""
        self.stream = stream
        self.chunk_size = chunk_size
        self.gen_kwargs = gen_kwargs or {}
        self.prompt_wav = prompt_wav or DEFAULT_PROMPT_WAV
        model_dir = self._resolve_model_dir(model_name)
        logger.info(
            "Loading CosyVoice TTS model: %s (dir=%s, prompt_wav=%s, instruct=%r)",
            model_name,
            model_dir,
            self.prompt_wav,
            self.instruct,
        )
        try:
            from cosyvoice.cli.cosyvoice import CosyVoice2
        except ImportError as exc:
            raise ImportError(
                "CosyVoice TTS requires the official CosyVoice source on PYTHONPATH. "
                "Rebuild the image with the 'cosyvoice' extra."
            ) from exc
        # CosyVoice2 chooses CUDA automatically when available; fp16 kept off for
        # maximum stability on first bring-up.
        self.model = CosyVoice2(model_dir, load_jit=load_jit, load_trt=load_trt, fp16=fp16)
        self.warmup()

    @staticmethod
    def _resolve_model_dir(model_name: str) -> str:
        from pathlib import Path

        if Path(model_name).exists():
            return model_name
        try:
            from modelscope import snapshot_download

            logger.info("Downloading CosyVoice model %s via ModelScope", model_name)
            return snapshot_download(model_name)
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("CosyVoice ModelScope download failed: %s", exc)
            return model_name

    def warmup(self) -> None:
        logger.info(f"Warming up {self.__class__.__name__}")
        try:
            for _ in self._generate("你好。"):
                pass
            logger.info(f"{self.__class__.__name__} warmed up")
        except Exception as exc:  # pragma: no cover - non-fatal
            logger.warning("CosyVoice warmup failed (non-fatal): %s", exc)

    def process(self, tts_input: TTSIn) -> Iterator[TTSOut]:
        speculative_turns = getattr(self, "speculative_turns", None)
        if isinstance(tts_input, EndOfResponse):
            if speculative_turns and not speculative_turns.is_latest_after_reopen_grace(
                tts_input.turn_id,
                tts_input.turn_revision,
            ):
                if tts_input.response_key is None:
                    return
                tts_input.cleanup_only = True
            yield AUDIO_RESPONSE_DONE
            return

        if speculative_turns and not speculative_turns.is_latest_after_reopen_grace(
            tts_input.turn_id,
            tts_input.turn_revision,
        ):
            logger.debug(
                "Dropping stale TTS input for turn=%s rev=%s",
                tts_input.turn_id,
                tts_input.turn_revision,
            )
            return
        if speculative_turns:
            speculative_turns.commit(tts_input.turn_id, tts_input.turn_revision)

        text = tts_input.text
        console.print(f"[green]ASSISTANT: {text}")
        _cancel_gen = self.cancel_scope.generation if self.cancel_scope else None

        for audio_chunk in self._stream(self._generate(text), _cancel_gen):
            yield audio_chunk

    def _generate(self, text: str) -> Iterator[np.ndarray]:
        try:
            results = self.model.inference_instruct2(
                tts_text=text,
                instruct_text=self.instruct,
                prompt_wav=self.prompt_wav,
                zero_shot_spk_id="",
                stream=self.stream,
                **self.gen_kwargs,
            )
        except Exception as exc:
            logger.error("CosyVoice inference failed: %s", exc)
            return
        for out in results:
            tts_speech = out["tts_speech"]
            audio = tts_speech.squeeze().cpu().float().numpy()
            yield np.asarray(audio, dtype=np.float32)

    def _stream(self, gen: Iterator[np.ndarray], cancel_gen: Any) -> Iterator[np.ndarray]:
        leftover = np.array([], dtype=np.int16)
        for audio in gen:
            if (
                cancel_gen is not None
                and self.cancel_scope is not None
                and self.cancel_scope.is_stale(cancel_gen)
            ):
                logger.info("TTS generation cancelled (interruption)")
                return
            if audio is None or audio.size == 0:
                continue
            audio_16k = librosa.resample(
                audio.astype(np.float32), orig_sr=COSYVOICE_SR, target_sr=PIPELINE_SR
            )
            chunk = (audio_16k * 32768).astype(np.int16)
            audio_chunk = np.concatenate([leftover, chunk])
            n = (len(audio_chunk) // self.chunk_size) * self.chunk_size
            for i in range(0, n, self.chunk_size):
                yield audio_chunk[i : i + self.chunk_size]
            leftover = audio_chunk[n:]
        if len(leftover) > 0:
            yield np.pad(leftover, (0, self.chunk_size - len(leftover)))

    def on_session_end(self) -> None:
        logger.debug("CosyVoice TTS session state reset")

    def cleanup(self) -> None:
        try:
            del self.model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("CosyVoice TTS handler cleaned up")
        except Exception as exc:  # pragma: no cover
            logger.warning("Cleanup error: %s", exc)
