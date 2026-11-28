import json
from dataclasses import fields

from speech_to_speech.arguments_classes.qwen3_asr_stt_arguments import Qwen3ASRSTTHandlerArguments
from speech_to_speech.backend_registry import STT_BACKENDS, normalize_dataclass_config
from speech_to_speech.s2s_pipeline import parse_arguments


def _argument_fields():
    return {config_field.name: config_field for config_field in fields(Qwen3ASRSTTHandlerArguments)}


def test_qwen3_asr_gen_num_beams_defaults_to_one_and_is_int():
    num_beams = _argument_fields()["qwen3_asr_gen_num_beams"]

    assert num_beams.default == 1
    assert num_beams.type is int
    assert isinstance(Qwen3ASRSTTHandlerArguments().qwen3_asr_gen_num_beams, int)


def test_qwen3_asr_gen_num_beams_is_parsed_from_cli():
    args = parse_arguments(["--stt", "qwen3-asr", "--qwen3_asr_gen_num_beams", "3"])

    assert args.stt_backend.name == "qwen3-asr"
    assert args.stt_backend.config["gen_kwargs"]["num_beams"] == 3


def test_qwen3_asr_gen_num_beams_is_parsed_from_json_config(tmp_path):
    config = tmp_path / "pipeline.json"
    config.write_text(json.dumps({"stt": "qwen3-asr", "qwen3_asr_gen_num_beams": 3}))

    args = parse_arguments([str(config)])

    assert args.stt_backend.name == "qwen3-asr"
    assert args.stt_backend.config["gen_kwargs"]["num_beams"] == 3


def test_qwen3_asr_registry_normalization_maps_gen_num_beams_into_gen_kwargs():
    config = Qwen3ASRSTTHandlerArguments(qwen3_asr_gen_num_beams=3)

    normalized = normalize_dataclass_config(config, "qwen3_asr")

    assert normalized["gen_kwargs"]["num_beams"] == 3


def test_qwen3_asr_default_gen_kwargs_keep_existing_semantics():
    args = parse_arguments(["--stt", "qwen3-asr"])

    # The normalizer keeps defaults (no filtering), so num_beams=1 is always
    # forwarded; 1 is also HF generate's own default, so the effective behavior
    # is unchanged from the pre-beam status quo.
    assert args.stt_backend.config["gen_kwargs"] == {"max_new_tokens": 256, "num_beams": 1}
    assert STT_BACKENDS["qwen3-asr"].config_prefix == "qwen3_asr"
