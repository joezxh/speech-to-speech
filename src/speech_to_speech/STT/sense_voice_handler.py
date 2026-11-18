from __future__ import annotations

import logging
import re
from time import perf_counter
from typing import Any, Iterator

import numpy as np
import torch

from speech_to_speech.pipeline.console import console
from speech_to_speech.pipeline.handler_types import STTIn, STTOut
from speech_to_speech.pipeline.messages import PartialTranscription, Transcription
from speech_to_speech.STT.base_stt_handler import BaseSTTHandler

logger = logging.getLogger(__name__)

# SenseVoice 把情感/音频事件作为副产品输出（如 😊/🎼），rich_transcription_postprocess
# 只清理标签不去掉这些 emoji。下游 TTS 会把 emoji 读成怪音或卡住，故在送入管线前
# 一并剥离。保留中日韩文字、拉丁字母、数字、空白与常见中英文标点。
_EMOJI_AND_SYMBOLS = re.compile(
    "["
    "\U0001F000-\U0001FAFF"  # emoji 主体（表情/音频事件/符号）
    "\U00002600-\U000027BF"  # 杂项符号与图形（☀✂ 等）
    "\U0001F1E6-\U0001F1FF"  # 区域旗帜
    "\U0000FE0F\U000020E3"  # variation selector / combining enclosing keycap
    "]"
)


_TAG_PATTERN = re.compile(r"<\|[^|]+\|>")


def _strip_emotion_symbols(text: str) -> str:
    """Remove SenseVoice's emotion/event emoji before the text reaches TTS."""
    return _EMOJI_AND_SYMBOLS.sub("", text).strip()


def _extract_raw_emotion(text: str) -> str:
    """Return the raw emotion token name from a SenseVoice rich-text string."""
    for tag in _TAG_PATTERN.findall(text or ""):
        name = tag[2:-2]
        if name in {"HAPPY", "SAD", "ANGRY", "NEUTRAL", "FEARFUL",
                    "DISGUSTED", "SURPRISED", "OTHER", "EMO_UNKNOWN"}:
            return name
    return "EMO_UNKNOWN"


def _has_laughter(text: str) -> bool:
    return "<|Laughter|>" in (text or "") or "😀" in (text or "")


class SenseVoiceSTTHandler(BaseSTTHandler):
    """Transcribe VAD segments with FunASR's SenseVoiceSmall checkpoint."""

    def setup(
        self,
        model_name: str = "FunAudioLLM/SenseVoiceSmall",
        device: str = "cuda",
        language: str = "auto",
        gen_kwargs: dict[str, Any] | None = None,
    ) -> None:
        try:
            from funasr import AutoModel
            from funasr.utils.postprocess_utils import rich_transcription_postprocess
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "SenseVoice STT requires the optional 'sensevoice' extra. "
                'Install it with `pip install "speech-to-speech[sensevoice]"`.'
            ) from exc

        self.device = device
        self.language = language
        self.gen_kwargs = dict(gen_kwargs or {})
        self._postprocess = rich_transcription_postprocess
        self.model = AutoModel(model=model_name, hub="hf", device=device, disable_update=True)
        self._install_emotion_hook()
        self.warmup()

    def _install_emotion_hook(self) -> None:
        """Hook ctc.ctc_lo to capture rich-info logits for SER confidence.

        SenseVoice's decoder logits are produced by ``ctc.ctc_lo(encoder_out)``;
        position 1 carries the emotion token.  We keep the last output in
        ``self._last_logits`` (detached, CPU) for :meth:`recognize`.
        """
        self._last_logits = None
        try:
            inner = getattr(self.model, "model", None)
            ctc = getattr(inner, "ctc", None)
            ctc_lo = getattr(ctc, "ctc_lo", None)
            if ctc_lo is None:
                logger.warning("SenseVoice ctc.ctc_lo not found; SER confidence unavailable")
                return

            def _capture(_module, _inputs, output):
                tensor = output[0] if isinstance(output, (tuple, list)) else output
                if hasattr(tensor, "detach"):
                    self._last_logits = tensor.detach().cpu().numpy()
                elif isinstance(tensor, np.ndarray):
                    self._last_logits = tensor

            self._emotion_hook_handle = ctc_lo.register_forward_hook(_capture)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not install SenseVoice emotion hook: %s", exc)

    def _generate_raw(self, audio: np.ndarray) -> tuple[str, str | None]:
        """Return (postprocessed text, original rich-tag text)."""
        result = self.model.generate(
            audio,
            cache={},
            language=self.language,
            use_itn=True,
            **self.gen_kwargs,
        )
        raw = result[0]["text"] if isinstance(result, list) and result else ""
        return self._postprocess(raw).strip(), raw

    def _generate(self, audio: np.ndarray) -> str:
        text, _ = self._generate_raw(audio)
        # Also strip residual <|...|> tags so fake postprocessors / raw passthrough
        # never leak rich tags into TTS or transcription output.
        return _strip_emotion_symbols(_TAG_PATTERN.sub("", text)).strip()

    def _generate_with_emotion(self, audio: np.ndarray) -> tuple[str, str | None]:
        """Return clean transcript and an optional emotion text for the LLM."""
        text, raw = self._generate_raw(audio)
        clean = _strip_emotion_symbols(_TAG_PATTERN.sub("", text)).strip()
        emotion_name = _extract_raw_emotion(raw)
        if emotion_name in ("EMO_UNKNOWN", "OTHER", ""):
            return clean, None
        from speech_to_speech.STT.sense_voice_emotion import emotion_to_text, map_emotion

        try:
            label = map_emotion(emotion_name, laughter=_has_laughter(raw))
        except Exception:
            return clean, None
        return clean, emotion_to_text(label, laughter=_has_laughter(raw))

    def recognize(self, audio: np.ndarray) -> dict:
        """Return raw emotion label + laughter + confidence/margin for SER endpoint."""
        _, raw = self._generate_raw(audio)
        logits = getattr(self, "_last_logits", None)
        conf, margin = 0.0, 0.0
        if logits is not None:
            try:
                from speech_to_speech.STT.sense_voice_emotion import (
                    emotion_token_ids,
                    probs_from_logits,
                    slice_emotion_logits,
                )

                conf, margin, _ = probs_from_logits(
                    slice_emotion_logits(logits), emotion_token_ids()
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("SER logits decode failed: %s", exc)
        return {
            "raw": _extract_raw_emotion(raw),
            "laughter": _has_laughter(raw),
            "confidence": conf,
            "margin": margin,
        }

    def warmup(self) -> None:
        logger.info("Warming up %s", self.__class__.__name__)
        self._generate(np.zeros(16000, dtype=np.float32))

    def _empty_cache(self) -> None:
        if isinstance(self.device, str) and self.device.startswith("cuda") and torch.cuda.is_available():
            torch.cuda.empty_cache()
        elif self.device == "mps" and torch.backends.mps.is_available():
            torch.mps.empty_cache()

    def process(self, vad_audio: STTIn) -> Iterator[STTOut]:
        started_at_s = perf_counter()
        pred_text, emotion_text = self._generate_with_emotion(vad_audio.audio)
        self._empty_cache()
        console.print(f"[yellow]USER: {pred_text}")

        if vad_audio.mode == "progressive":
            yield PartialTranscription(
                text=pred_text,
                emotion=emotion_text,
                turn_id=vad_audio.turn_id,
                turn_revision=vad_audio.turn_revision,
            )
            return

        self._record_final_stt(vad_audio, perf_counter() - started_at_s)
        yield Transcription(
            text=pred_text,
            emotion=emotion_text,
            turn_id=vad_audio.turn_id,
            turn_revision=vad_audio.turn_revision,
            speech_stopped_at_s=vad_audio.speech_end_at_s,
        )
