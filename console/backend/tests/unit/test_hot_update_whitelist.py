from __future__ import annotations

from app.services.hot_update_service import prune


def test_prune_keeps_the_four_allowed_paths():
    clean, rejected = prune(
        {
            "instructions": "be brief",
            "audio": {
                "input": {
                    "turn_detection": {"interrupt_response": False},
                    "transcription": {"language": "zh"},
                }
            },
            "extensions": {"speech_to_speech": {"input_audio_transcription": {"snapshot": True}}},
        }
    )
    assert rejected == []
    assert clean["instructions"] == "be brief"
    assert clean["audio"]["input"]["turn_detection"] == {"interrupt_response": False}
    assert clean["audio"]["input"]["transcription"] == {"language": "zh"}
    assert "extensions" in clean


def test_prune_names_model_and_voice_instead_of_dropping_them():
    clean, rejected = prune(
        {"instructions": "hi", "model": "gpt-4o", "audio": {"output": {"voice": "alloy"}}}
    )
    # Silent drops are how an operator ends up believing `voice` was updated.
    assert sorted(rejected) == ["audio.output.voice", "model"]
    assert clean == {"instructions": "hi"}


def test_prune_rejects_a_scalar_where_an_object_belongs():
    clean, rejected = prune({"audio": {"input": {"transcription": "zh"}}})
    assert rejected == ["audio.input.transcription"]
    assert clean == {}
