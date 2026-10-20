from __future__ import annotations

import logging
import re
from typing import Any, Iterator

import numpy as np
from rich.console import Console

from speech_to_speech.pipeline.handler_types import STTIn, STTOut
from speech_to_speech.pipeline.messages import PartialTranscription, Transcription
from speech_to_speech.STT.base_stt_handler import BaseSTTHandler

logger = logging.getLogger(__name__)
console = Console()

# SenseVoice prepends control tags such as <|zh|><|NEUTRAL|><|w|> to its output.
# These must be stripped before the transcript is forwarded to the LLM.
_TAG_PATTERN = re.compile(r"<\|[^|]*\|>")


class SenseVoiceSTTHandler(BaseSTTHandler):
    """
    Handles Speech-To-Text using Alibaba DAMO Academy's SenseVoice-Small model
    (FunASR). Supports Chinese, English, Cantonese, Japanese and Korean, and
    additionally emits emotion / event labels (e.g. <|HAPPY|>, <|BGM|>) which are
    stripped here so only the clean transcript reaches the LLM.

    The default for this model is set to multilingual auto-detection.
    This model was contributed for the Chinese / dialect deployment scenario.
    """

    def setup(
        self,
        model_name: str = "SenseVoiceSmall",
        device: str = "cuda",
        language: str = "auto",
        use_itn: bool = True,
        gen_kwargs: dict[str, Any] | None = None,
        **_ignored: Any,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.language = language
        self.use_itn = use_itn
        self.gen_kwargs = gen_kwargs or {}
        logger.info("Loading SenseVoice STT model: %s (language=%s)", model_name, language)
        try:
            from funasr import AutoModel
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "SenseVoice STT requires the optional 'sensevoice' extra. "
                "Install it with `pip install \"speech-to-speech[sensevoice]\"`."
            ) from exc
        # disable_update avoids phoning home to the FunASR model zoo at startup.
        self.model = AutoModel(model=model_name, device=device, disable_update=True)
        self.warmup()

    def warmup(self) -> None:
        logger.info(f"Warming up {self.__class__.__name__}")
        dummy = np.zeros(16000, dtype=np.float32)
        try:
            self.model.generate(
                input=dummy,
                cache={},
                language="auto",
                use_itn=True,
                batch_size=1,
            )
        except Exception as exc:  # pragma: no cover - non-fatal
            logger.warning("SenseVoice warmup failed (non-fatal): %s", exc)

    @staticmethod
    def _clean(text: str) -> str:
        return _TAG_PATTERN.sub("", text or "").strip()

    def process(self, vad_audio: STTIn) -> Iterator[STTOut]:
        logger.debug("infering sensevoice...")
        try:
            pred = self.model.generate(
                input=vad_audio.audio,
                cache={},
                language=self.language,
                use_itn=self.use_itn,
                batch_size=1,
                **self.gen_kwargs,
            )
        except Exception as exc:
            logger.error("SenseVoice inference failed: %s", exc)
            return
        pred_text = self._clean(pred[0]["text"]) if pred else ""
        logger.debug("finished sensevoice inference")
        console.print(f"[yellow]USER: {pred_text}")

        if vad_audio.mode == "progressive":
            yield PartialTranscription(
                text=pred_text,
                turn_id=vad_audio.turn_id,
                turn_revision=vad_audio.turn_revision,
            )
        else:
            yield Transcription(
                text=pred_text,
                language_code=None if self.language == "auto" else self.language,
                turn_id=vad_audio.turn_id,
                turn_revision=vad_audio.turn_revision,
                speech_stopped_at_s=vad_audio.created_at_s,
            )
