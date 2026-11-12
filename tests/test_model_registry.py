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
    ModelWeightsMissingError,
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


def test_model_weights_missing_error_is_registry_error():
    assert issubclass(ModelWeightsMissingError, ModelRegistryError)
    assert issubclass(ModelWeightsMissingError, ValueError)
    assert not issubclass(ModelWeightsMissingError, ImportError)


def test_module_level_facades(monkeypatch):
    monkeypatch.setattr(mr, "MODEL_REGISTRY", ModelRegistry())
    mr.register_model(card(id="facade", status="planned", backend_name="future-tts"))
    assert [c.id for c in list_models(status="planned")] == ["facade"]
    assert mr.get_model("facade").status == "planned"
    validate_models()


def assert_no_handler_modules(module: str) -> None:
    code = (
        f"import sys, {module}; "
        "eager_backends = [k for k in sys.modules if "
        "k.startswith(('speech_to_speech.STT.', 'speech_to_speech.TTS.')) "
        "or (k.startswith('speech_to_speech.LLM.') and k.endswith('language_model'))]; "
        "assert not eager_backends, sorted(eager_backends)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_import_does_not_load_backend_handlers():
    assert_no_handler_modules("speech_to_speech.model_registry")


def test_builtin_catalog_status_counts_and_license_gate():
    from speech_to_speech.models.builtin import builtin_model_cards

    cards = builtin_model_cards()
    assert len(cards) == 9
    assert len({c.id for c in cards}) == 9
    assert sorted(c.id for c in cards if c.status == "available") == [
        "qwen3-asr-1.7b-hf",
        "qwen3-tts-1.7b-customvoice",
        "qwen3.5-4b-transformers",
    ]
    assert not [c.id for c in cards if c.status == "deprecated"]
    assert sum(c.status == "planned" for c in cards) == 6

    breeze = next(c for c in cards if c.id == "breeze-tts-2")
    assert breeze.status == "planned"
    assert "Research and Non-Commercial" in breeze.license
    assert "商用" in breeze.notes
    assert "商业授权" in breeze.notes
    assert breeze.min_vram_gb == 7.7

    qwen_llm = next(c for c in cards if c.id == "minicpm-homologous-qwen3-8b")
    assert qwen_llm.min_vram_gb == 16.0


def test_builtin_cards_bind_without_error():
    from speech_to_speech.models.builtin import builtin_model_cards

    reg = ModelRegistry()
    for item in builtin_model_cards():
        reg.register(item)
    reg.bind(
        {
            "stt": {"qwen3-asr": FakeSpec("stt"), "whisper": FakeSpec("stt")},
            "llm": {"transformers": FakeSpec("llm")},
            "tts": {"qwen3": FakeSpec("tts")},
        }
    )
    assert len(reg.list()) == 9


def test_backend_spec_has_default_models_field():
    from speech_to_speech.backend_registry import LLM_BACKENDS, STT_BACKENDS, TTS_BACKENDS

    for registry in (STT_BACKENDS, LLM_BACKENDS, TTS_BACKENDS):
        for spec in registry.values():
            assert spec.models == (), spec.name
    assert len(STT_BACKENDS) + len(LLM_BACKENDS) + len(TTS_BACKENDS) == 31


def test_importing_backend_registry_populates_global_catalog():
    from speech_to_speech import model_registry as mr
    from speech_to_speech.backend_registry import STT_BACKENDS  # noqa: F401

    assert len(mr.list_models()) == 9
    assert mr.get_model("breeze-tts-2").status == "planned"


def test_backend_registry_import_keeps_handler_lazy_loading():
    assert_no_handler_modules("speech_to_speech.backend_registry")


def _inline_registries(spec):
    return {
        "stt": {"qwen3-asr": FakeSpec("stt"), "whisper": FakeSpec("stt")},
        "llm": {"transformers": FakeSpec("llm")},
        "tts": {"qwen3": spec},
    }


def test_bind_model_cards_registers_inline_cards(monkeypatch):
    reg = ModelRegistry()
    monkeypatch.setattr(mr, "MODEL_REGISTRY", reg)
    inline = card(id="inline-tts", backend_name="qwen3")
    tts_spec = FakeSpec("tts")
    tts_spec.models = (inline,)
    mr.bind_model_cards(_inline_registries(tts_spec))
    assert "inline-tts" in {c.id for c in reg.list()}
    assert reg.get("inline-tts") is inline
    assert len(reg.list()) == 10


def test_bind_model_cards_rejects_inline_duplicate_of_builtin(monkeypatch):
    reg = ModelRegistry()
    monkeypatch.setattr(mr, "MODEL_REGISTRY", reg)
    duplicate = card(id="cosyvoice2", backend_name="qwen3")
    tts_spec = FakeSpec("tts")
    tts_spec.models = (duplicate,)
    with pytest.raises(ModelRegistryError, match="Duplicate"):
        mr.bind_model_cards(_inline_registries(tts_spec))
