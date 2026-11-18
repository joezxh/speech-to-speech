"""Contract tests for the in-process SenseVoice SER helpers (TDD RED first)."""
from __future__ import annotations

import numpy as np
import pytest

from speech_to_speech.STT import sense_voice_emotion as sve


EMO_TOKENS = [
    "<|HAPPY|>",
    "<|SAD|>",
    "<|ANGRY|>",
    "<|NEUTRAL|>",
    "<|FEARFUL|>",
    "<|DISGUSTED|>",
    "<|SURPRISED|>",
    "<|OTHER|>",
    "<|EMO_UNKNOWN|>",
]


def test_emotion_token_ids_match_local_vocab():
    ids = sve.emotion_token_ids()
    assert ids["HAPPY"] == 25001
    assert ids["NEUTRAL"] == 25004
    assert ids["EMO_UNKNOWN"] == 25009
    assert ids["Laughter"] == 24997


def test_softmax_confidence_and_margin_over_emotion_logits():
    # SenseVoice rich-info layout: pos0=lang, pos1=emotion, pos2=event, pos3=itn.
    # The hook slices position 1 ([B, vocab]) before calling probs_from_logits.
    ids = sve.emotion_token_ids()
    assert sve.EMOTION_LOGIT_POSITION == 1
    vocab = max(ids.values()) + 1
    emo_logits = np.full(vocab, -30.0, dtype=np.float32)
    emo_logits[ids["HAPPY"]] = 5.0
    emo_logits[ids["NEUTRAL"]] = 2.0
    conf, margin, label = sve.probs_from_logits(emo_logits, ids)
    assert label == "HAPPY"
    assert 0.9 < conf < 1.0
    assert 0.8 < margin < 1.0


def test_slice_emotion_logits_from_full_decoder_output():
    ids = sve.emotion_token_ids()
    vocab = max(ids.values()) + 1
    full = np.zeros((1, 6, vocab), dtype=np.float32)
    full[0, sve.EMOTION_LOGIT_POSITION, ids["ANGRY"]] = 9.0
    sliced = sve.slice_emotion_logits(full)
    assert sliced.shape == (vocab,)
    conf, margin, label = sve.probs_from_logits(sliced, ids)
    assert label == "ANGRY"


def test_map_surprised_and_disgusted_to_agitated():
    assert sve.map_emotion("SURPRISED", laughter=False) == "agitated"
    assert sve.map_emotion("DISGUSTED", laughter=False) == "agitated"


def test_map_fearful_and_sad_to_anxious():
    assert sve.map_emotion("FEARFUL", laughter=False) == "anxious"
    assert sve.map_emotion("SAD", laughter=False) == "anxious"


def test_happy_maps_to_happy_not_calm():
    assert sve.map_emotion("HAPPY", laughter=False) == "happy"
    assert sve.map_emotion("HAPPY", laughter=True) == "happy"


def test_neutral_and_angry_mapping():
    assert sve.map_emotion("NEUTRAL", laughter=False) == "calm"
    assert sve.map_emotion("ANGRY", laughter=False) == "anger"


def test_unknown_and_other_are_rejected():
    for raw in ("EMO_UNKNOWN", "OTHER", "UNKNOWN", "garbage"):
        with pytest.raises(sve.SERRejection) as exc:
            sve.map_emotion(raw, laughter=False)
        assert exc.value.reason in ("REJECTED_LABEL",)


def test_low_confidence_is_rejected_with_structured_reason():
    with pytest.raises(sve.SERRejection) as exc:
        sve.threshold_gate(confidence=0.42, margin=0.3)
    assert exc.value.reason == "LOW_CONFIDENCE"


def test_low_margin_is_rejected_with_structured_reason():
    with pytest.raises(sve.SERRejection) as exc:
        sve.threshold_gate(confidence=0.95, margin=0.02)
    assert exc.value.reason == "LOW_MARGIN"


def test_rejection_error_body_is_structured():
    body = sve.ser_error_body("LOW_MARGIN", "top1-top2 too close")
    assert body["error"]["code"] == "LOW_MARGIN"
    assert body["error"]["stage"] == "SER"
    assert body["error"]["reason"] == "top1-top2 too close"
