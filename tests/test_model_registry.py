import subprocess
import sys
from dataclasses import FrozenInstanceError, dataclass

import pytest

from speech_to_speech import model_registry as mr
from speech_to_speech.model_registry import (
    ModelCard,
    ModelLicenseError,
    ModelNotAvailableError,
    ModelRegistry,
    ModelRegistryError,
    list_models,
    resolve_model,
    validate_models,
)


def card(**overrides):
    base = dict(
        id="test-tts",
        name="Test TTS",
        kind="tts",
        version="1",
        provider="Test",
        weight_format="safetensors",
        backend_name="fake-tts",
    )
    base.update(overrides)
    return ModelCard(**base)


@dataclass
class FakeArgs:
    model_name: str = "x"
    device: str = "cuda"


class FakeSpec:
    def __init__(self, kind, config_type=FakeArgs):
        self.kind = kind
        self.config_type = config_type


def registries():
    return {"stt": {}, "llm": {}, "tts": {"fake-tts": FakeSpec("tts")}}


def test_card_is_frozen():
    with pytest.raises(FrozenInstanceError):
        card().name = "changed"


def test_register_rejects_duplicate_id():
    reg = ModelRegistry()
    reg.register(card())
    with pytest.raises(ModelRegistryError, match="Duplicate"):
        reg.register(card())


def test_list_filters_and_sorts_by_id():
    reg = ModelRegistry()
    reg.register(card(id="z", status="planned"))
    reg.register(card(id="a", kind="stt"))
    assert [c.id for c in reg.list()] == ["a", "z"]
    assert [c.id for c in reg.list(kind="stt")] == ["a"]
    assert [c.id for c in reg.list(status="planned")] == ["z"]


def test_get_unknown_lists_known_ids():
    reg = ModelRegistry()
    reg.register(card())
    with pytest.raises(ModelRegistryError, match="test-tts"):
        reg.get("missing")


def test_by_backend():
    reg = ModelRegistry()
    reg.register(card())
    assert [c.id for c in reg.by_backend("fake-tts")] == ["test-tts"]


def test_bind_detects_kind_mismatch_and_missing_available_backend():
    reg = ModelRegistry()
    reg.register(card(kind="stt", status="available"))
    reg.register(card(id="ghost", status="available", backend_name="no-such-backend"))
    with pytest.raises(ModelRegistryError, match="validation failed"):
        reg.bind(registries())


def test_bind_allows_planned_card_with_unregistered_backend():
    reg = ModelRegistry()
    reg.register(card(status="planned", backend_name="future-tts"))
    reg.bind(registries())
    assert reg.get("test-tts").status == "planned"


def test_bind_rejects_unknown_load_param_and_exposes_types():
    reg = ModelRegistry()
    reg.register(card(default_load_params={"bogus": 1}))
    with pytest.raises(ModelRegistryError, match="unknown load params"):
        reg.bind(registries())
    reg2 = ModelRegistry()
    reg2.register(card())
    reg2.bind(registries())
    assert set(reg2.load_param_types("test-tts")) == {"model_name", "device"}


def test_resolve_model_planned_raises_and_deprecated_returns(monkeypatch):
    reg = ModelRegistry()
    reg.register(card(id="planned-model", status="planned"))
    reg.register(card(id="deprecated-model", status="deprecated"))
    monkeypatch.setattr(mr, "MODEL_REGISTRY", reg)
    with pytest.raises(ModelNotAvailableError, match="Spec B"):
        resolve_model("planned-model")
    assert resolve_model("deprecated-model").status == "deprecated"


def test_license_error_is_registry_error():
    assert issubclass(ModelLicenseError, ModelRegistryError)


def test_module_level_facades(monkeypatch):
    monkeypatch.setattr(mr, "MODEL_REGISTRY", ModelRegistry())
    mr.register_model(card(id="facade", status="planned", backend_name="future-tts"))
    assert [c.id for c in list_models(status="planned")] == ["facade"]
    assert mr.get_model("facade").status == "planned"
    validate_models()


def assert_no_handler_modules(module: str) -> None:
    code = (
        f"import sys, {module}; "
        "prefixes = ('speech_to_speech.STT.', 'speech_to_speech.TTS.', 'speech_to_speech.LLM.'); "
        "assert not [k for k in sys.modules if k.startswith(prefixes)], "
        "sorted(k for k in sys.modules if k.startswith(prefixes))"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_import_does_not_load_backend_handlers():
    assert_no_handler_modules("speech_to_speech.model_registry")
