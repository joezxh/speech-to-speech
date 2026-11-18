"""SenseVoice emotion extraction helpers for the in-process SER endpoint.

SenseVoice emits emotion as *discrete tokens* (``<|HAPPY|>`` ...) rather than a
probability vector.  This module maps raw logits captured from the decoder into
a 7-class probability distribution (confidence + top1/top2 margin), maps the 7
tokens onto the platform's 6-label set (happy added as the 6th class), and
produces structured 409 rejection bodies.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

# Default thresholds — can be overridden via env by the endpoint layer.
DEFAULT_MIN_CONFIDENCE = 0.55
DEFAULT_MIN_MARGIN = 0.15

# SenseVoice rich-info token layout: [lang, emotion, event, itn].
# Verified against funasr 1.4.27 `ctc.ctc_lo` hook: position 1 carries the
# emotion logits (top1 token == the <|...EMO...|> in generate()'s text output).
EMOTION_LOGIT_POSITION = 1

_EMOTION_TOKENS = (
    "HAPPY",
    "SAD",
    "ANGRY",
    "NEUTRAL",
    "FEARFUL",
    "DISGUSTED",
    "SURPRISED",
    "OTHER",
    "EMO_UNKNOWN",
)
_EXTRA_TOKENS = ("Laughter",)


@dataclass
class SERRejection(Exception):
    """Raised when an utterance must be refused (409) with a structured reason."""

    reason: str
    detail: str = ""

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"{self.reason}: {self.detail}".strip()


def _default_tokens_path() -> Path:
    return Path(__file__).resolve().parents[3] / "cache" / "sensevoice-small" / "tokens.json"


_emotion_token_ids_cache: dict[str, int] | None = None


def emotion_token_ids(tokens_path: Path | None = None) -> dict[str, int]:
    """Return token-id map for the 9 emotion tokens plus Laughter.

    ``tokens.json`` is a flat list where the list index is the token id.  We
    cache the default lookup so the endpoint does not re-read the ~25k list per
    request.  A custom path bypasses the cache (used by tests).
    """
    global _emotion_token_ids_cache
    if tokens_path is None and _emotion_token_ids_cache is not None:
        return dict(_emotion_token_ids_cache)
    path = tokens_path or _default_tokens_path()
    tokens = json.loads(Path(path).read_text(encoding="utf-8"))
    wanted = set(_EMOTION_TOKENS) | set(_EXTRA_TOKENS)
    result: dict[str, int] = {}
    for idx, token in enumerate(tokens):
        if not isinstance(token, str) or not token.startswith("<|") or not token.endswith("|>"):
            continue
        name = token[2:-2]
        if name in wanted:
            result[name] = idx
    missing = wanted - set(result)
    if missing:
        raise RuntimeError(f"SenseVoice tokens.json missing emotion tokens: {sorted(missing)}")
    if tokens_path is None:
        _emotion_token_ids_cache = dict(result)
    return result


def slice_emotion_logits(logits: "np.ndarray") -> "np.ndarray":
    """Slice the emotion position from a full decoder/logits tensor.

    ``ctc.ctc_lo`` emits ``[B, T, vocab]``; the emotion token occupies
    ``T == EMOTION_LOGIT_POSITION`` (1).  Returns a 1-D ``[vocab]`` vector.
    """
    arr = np.asarray(logits)
    if arr.ndim == 3:
        arr = arr[0]
    if arr.ndim != 2:
        raise ValueError(f"expected [B,T,vocab] or [T,vocab] logits, got {arr.shape}")
    return arr[EMOTION_LOGIT_POSITION]


def probs_from_logits(
    emo_logits: "np.ndarray",
    ids: dict[str, int],
) -> tuple[float, float, str]:
    """Compute (confidence, margin, raw_label) over the emotion token columns.

    Args:
        emo_logits: 1-D ``[vocab]`` float vector at the emotion position (see
            :func:`slice_emotion_logits`).
        ids: token-id map from :func:`emotion_token_ids`.

    Returns:
        confidence (top1 probability), margin (top1 - top2) and the raw label
        name of the top1 emotion token.
    """
    arr = np.asarray(emo_logits, dtype=np.float32).reshape(-1)
    names = [name for name in _EMOTION_TOKENS if name in ids]
    cols = [ids[name] for name in names]
    selected = arr[cols]
    selected = selected - selected.max()
    probs = np.exp(selected)
    probs = probs / probs.sum()
    order = np.argsort(-probs)
    top1, top2 = int(order[0]), int(order[1])
    return float(probs[top1]), float(probs[top1] - probs[top2]), names[top1]


def map_emotion(raw_label: str, laughter: bool = False) -> str:
    """Map a raw SenseVoice emotion token to the platform's 6-label set.

    Raises :class:`SERRejection` for unknown/rejected labels (409).
    """
    label = (raw_label or "").strip().upper().removeprefix("<|").removesuffix("|>")
    if label in ("EMO_UNKNOWN", "OTHER", "UNKNOWN", "", "GARBAGE"):
        raise SERRejection("REJECTED_LABEL", f"raw_label={raw_label!r}")
    mapping = {
        "HAPPY": "happy",
        "SAD": "anxious",
        "ANGRY": "anger",
        "NEUTRAL": "calm",
        "FEARFUL": "anxious",
        "DISGUSTED": "agitated",
        "SURPRISED": "agitated",
    }
    result = mapping.get(label)
    if result is None:
        raise SERRejection("REJECTED_LABEL", f"unmapped label {raw_label!r}")
    return result


def threshold_gate(
    confidence: float,
    margin: float,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    min_margin: float = DEFAULT_MIN_MARGIN,
) -> None:
    """Reject low-confidence / ambiguous predictions with a structured reason."""
    if confidence < min_confidence:
        raise SERRejection("LOW_CONFIDENCE", f"confidence={confidence:.3f}")
    if margin < min_margin:
        raise SERRejection("LOW_MARGIN", f"margin={margin:.3f}")


def ser_error_body(code: str, reason: str = "") -> dict[str, Any]:
    """Build the structured 409/429 error body expected by the platform."""
    return {"error": {"code": code, "stage": "SER", "reason": reason}}


def emotion_to_text(emotion: str, laughter: bool = False) -> str:
    """Render an emotion as the text injected into the LLM user message."""
    suffix = "（笑声）" if laughter and emotion == "happy" else ""
    return f"[情绪：{emotion}{suffix}]"


__all__ = [
    "SERRejection",
    "EMOTION_LOGIT_POSITION",
    "emotion_token_ids",
    "slice_emotion_logits",
    "probs_from_logits",
    "map_emotion",
    "threshold_gate",
    "ser_error_body",
    "emotion_to_text",
]
