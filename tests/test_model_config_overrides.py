import json
import subprocess
import sys
from pathlib import Path

import pytest

from speech_to_speech.config import ConfigurationError, load_config, resolve_config
from speech_to_speech.model_registry import resolve_model

EXAMPLE = Path(__file__).resolve().parents[1] / "example_configs" / "models-overrides.yaml"


def test_example_yaml_resolves_model_overrides():
    config = resolve_config(load_config(EXAMPLE), environ={"BREEZE_REPO": "/models/Breeze-TTS-2"})
    pipeline = config.pipelines["prod"]
    assert pipeline.model_cards["qwen3-tts-1.7b-customvoice"].repo_id == "/models/qwen3-tts"
    assert pipeline.model_cards["qwen3-tts-1.7b-customvoice"].default_load_params == {"qwen3_tts_device": "cpu"}
    assert pipeline.model_cards["minicpm-homologous-qwen3-8b"].repo_id == "/models/Breeze-TTS-2"
    assert resolve_model("qwen3-tts-1.7b-customvoice").repo_id != "/models/qwen3-tts"


def test_overrides_are_pipeline_local():
    document = load_config(EXAMPLE)
    document.data["pipelines"]["second"] = {
        "stages": dict(document.data["pipelines"]["prod"]["stages"]),
        "num_pipelines": 1,
    }
    config = resolve_config(document, environ={"BREEZE_REPO": "/models/Breeze-TTS-2"})
    first = config.pipelines["prod"].model_cards["qwen3-tts-1.7b-customvoice"]
    second = config.pipelines["second"].model_cards["qwen3-tts-1.7b-customvoice"]
    assert first is not second
    assert first.repo_id == second.repo_id == "/models/qwen3-tts"
    assert resolve_model("qwen3-tts-1.7b-customvoice").repo_id != "/models/qwen3-tts"


def test_unknown_model_id_is_rejected(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        EXAMPLE.read_text(encoding="utf-8").replace("qwen3-tts-1.7b-customvoice:", "no-such-model:", 1),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="registered model id"):
        resolve_config(load_config(path), environ={"BREEZE_REPO": "/models/Breeze-TTS-2"})


def test_unknown_load_param_is_rejected(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        EXAMPLE.read_text(encoding="utf-8").replace("qwen3_tts_device: cpu", "bogus: cpu", 1), encoding="utf-8"
    )
    with pytest.raises(ConfigurationError, match="Unknown load param"):
        resolve_config(load_config(path), environ={"BREEZE_REPO": "/models/Breeze-TTS-2"})


def test_missing_env_reference_is_rejected(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(EXAMPLE.read_text(encoding="utf-8").replace("BREEZE_REPO", "UNSET_MODEL_REPO", 1), encoding="utf-8")
    with pytest.raises(ConfigurationError):
        resolve_config(load_config(path), environ={})


def test_models_section_rejects_unknown_key(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        EXAMPLE.read_text(encoding="utf-8").replace("repo_id: /models/qwen3-tts", "unexpected: value", 1),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="Unknown field"):
        resolve_config(load_config(path), environ={"BREEZE_REPO": "/models/Breeze-TTS-2"})


def test_deprecated_non_commercial_card_cannot_be_configured(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        EXAMPLE.read_text(encoding="utf-8").replace("minicpm-homologous-qwen3-8b:", "breeze-tts-2:", 1),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="Deprecated non-commercial"):
        resolve_config(load_config(path), environ={"BREEZE_REPO": "/models/Breeze-TTS-2"})


def _models_list(*args):
    result = subprocess.run(
        [sys.executable, "-m", "speech_to_speech.cli", "models", "list", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result


def test_models_list_json_contains_status_counts():
    result = _models_list("--json")
    rows = json.loads(result.stdout)
    cards = [row for row in rows if row["status"] != "unregistered"]
    assert sum(row["status"] == "available" for row in cards) == 3
    assert sum(row["status"] == "planned" for row in cards) == 5
    assert sum(row["status"] == "deprecated" for row in cards) == 1
    assert sum(row["status"] == "unregistered" for row in rows) == 27
    breeze = next(row for row in rows if row["id"] == "breeze-tts-2")
    assert breeze["status"] == "deprecated"
    assert "Research and Non-Commercial" in breeze["license"]
    assert "商用" in result.stderr


def test_models_list_kind_filter():
    rows = json.loads(_models_list("--json", "--kind", "tts").stdout)
    assert all(row["kind"] == "tts" for row in rows if row["status"] != "unregistered")


def test_integration_guide_has_all_nine_sections():
    text = (
        Path(__file__).resolve().parents[1] / "docs" / "model-integration-guide-CN.md"
    ).read_text(encoding="utf-8")
    assert "## 1." in text and "## 9." in text
    for keyword in (
        "ModelCard",
        "BackendSpec",
        "BaseHandler",
        "16 kHz",
        "512 samples",
        "AUDIO_RESPONSE_DONE",
        "ModelWeightsMissingError",
        "ModelLicenseError",
        "路径 L",
        "路径 R",
        "ruff check",
    ):
        assert keyword in text, keyword
