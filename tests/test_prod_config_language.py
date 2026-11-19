"""TDD: the prod config keeps the assistant answering in the user's language.

Two independent guards: the language instruction injected by
`enable_lang_prompt` (which only fires when the STT backend reports a
language) and a Chinese session prompt. The English prompt used to be enough
for the model to answer in English, so the Chinese one is the safety net.
"""
from __future__ import annotations

from pathlib import Path

import yaml

CONFIG = Path(__file__).resolve().parents[1] / "config" / "prod.yaml"


def _llm_settings() -> dict:
    document = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    blocks = document["blocks"]
    llm_block = next(block for block in blocks.values() if block["kind"] == "llm")
    return llm_block["settings"]


def _has_chinese(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def test_lang_prompt_is_enabled():
    assert _llm_settings()["enable_lang_prompt"] is True


def test_session_prompt_is_chinese():
    prompt = _llm_settings()["init_chat_prompt"]
    assert _has_chinese(prompt), prompt


def test_session_prompt_still_asks_for_short_spoken_replies():
    prompt = _llm_settings()["init_chat_prompt"]
    assert "两句话" in prompt or "简短" in prompt

def test_language_lock_reaches_the_system_prompt():
    """The full chain, offline: STT reports "zh" -> the LLM is told to answer in Chinese.

    `enable_lang_prompt` only injects the instruction when the STT backend
    reports a language, and the SenseVoice handler reports the language
    SenseVoice tagged the audio with. This test pins the join of the two.
    """
    from speech_to_speech.LLM.utils import resolve_auto_language
    from speech_to_speech.LLM.voice_prompt import build_voice_system_prompt

    _, lang_name = resolve_auto_language("zh")
    system = build_voice_system_prompt(_llm_settings()["init_chat_prompt"], language_name=lang_name)

    assert lang_name == "chinese"
    assert "Please reply to my message in chinese." in system