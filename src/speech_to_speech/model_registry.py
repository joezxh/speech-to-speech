"""Static model metadata for ASR / LLM / TTS components.

Importing this module never imports a backend handler module.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, get_type_hints

ModelKind = Literal["stt", "llm", "tts"]
ModelStatus = Literal["available", "planned", "deprecated"]
WeightFormat = Literal["safetensors", "gguf", "mlx", "remote"]


class ModelRegistryError(ValueError):
    """Invalid model catalog state."""


class ModelNotAvailableError(ModelRegistryError):
    """A model whose adapter layer is not implemented was resolved."""


class ModelLicenseError(ModelRegistryError):
    """A commercial deployment selected a non-commercial weight."""


class ModelWeightsMissingError(ModelRegistryError):
    """权重目录缺失或缺少必备 checkpoint 组件"""


@dataclass(frozen=True)
class ModelCard:
    id: str
    name: str
    kind: ModelKind
    version: str
    provider: str
    weight_format: WeightFormat
    backend_name: str
    repo_id: str | None = None
    default_load_params: Mapping[str, Any] = field(default_factory=dict)
    min_vram_gb: float | None = None
    license: str | None = None
    status: ModelStatus = "available"
    notes: str = ""


class ModelRegistry:
    def __init__(self) -> None:
        self._cards: dict[str, ModelCard] = {}
        self._backend_index: dict[str, tuple[str, dict[str, Any]]] = {}

    def register(self, card: ModelCard) -> None:
        if card.id in self._cards:
            raise ModelRegistryError(f"Duplicate model id: {card.id!r}.")
        self._cards[card.id] = card

    def get(self, model_id: str) -> ModelCard:
        try:
            return self._cards[model_id]
        except KeyError:
            known = ", ".join(sorted(self._cards)) or "<none>"
            raise ModelRegistryError(f"Unknown model id {model_id!r}. Known ids: {known}.") from None

    def list(self, *, kind: ModelKind | None = None, status: ModelStatus | None = None) -> tuple[ModelCard, ...]:
        selected = (
            item
            for item in self._cards.values()
            if (kind is None or item.kind == kind) and (status is None or item.status == status)
        )
        return tuple(sorted(selected, key=lambda item: item.id))

    def by_backend(self, backend_name: str) -> tuple[ModelCard, ...]:
        return tuple(
            sorted(
                (item for item in self._cards.values() if item.backend_name == backend_name),
                key=lambda item: item.id,
            )
        )

    def bind(self, registries: Mapping[str, Mapping[str, Any]]) -> None:
        index: dict[str, tuple[str, dict[str, Any]]] = {}
        for kind, registry in registries.items():
            for name, spec in registry.items():
                hints = get_type_hints(spec.config_type)
                index[name] = (kind, hints)
        self._backend_index = index
        self.validate()

    def load_param_types(self, model_id: str) -> Mapping[str, Any]:
        card = self.get(model_id)
        entry = self._backend_index.get(card.backend_name)
        return entry[1] if entry else {}

    def validate(self) -> None:
        problems: list[str] = []
        for card in self._cards.values():
            entry = self._backend_index.get(card.backend_name)
            if entry is None:
                if card.status == "available":
                    problems.append(f"{card.id}: available card references unregistered backend {card.backend_name!r}.")
                continue
            kind, hints = entry
            if card.kind != kind:
                problems.append(f"{card.id}: kind {card.kind!r} != backend kind {kind!r}.")
            unknown = sorted(set(card.default_load_params) - set(hints))
            if unknown:
                problems.append(f"{card.id}: unknown load params {unknown} for backend {card.backend_name!r}.")
        if problems:
            raise ModelRegistryError("Model catalog validation failed:\n" + "\n".join(problems))


MODEL_REGISTRY = ModelRegistry()


def register_model(card: ModelCard) -> None:
    MODEL_REGISTRY.register(card)


def list_models(*, kind: ModelKind | None = None, status: ModelStatus | None = None) -> tuple[ModelCard, ...]:
    return MODEL_REGISTRY.list(kind=kind, status=status)


def get_model(model_id: str) -> ModelCard:
    return MODEL_REGISTRY.get(model_id)


def resolve_model(model_id: str) -> ModelCard:
    card = MODEL_REGISTRY.get(model_id)
    if card.status == "planned":
        raise ModelNotAvailableError(
            f"Model {card.id!r} is planned; its adapter layer is Spec B. "
            "See docs/model-integration-guide-CN.md section 3."
        )
    return card


def load_param_types(model_id: str) -> Mapping[str, Any]:
    return MODEL_REGISTRY.load_param_types(model_id)


def bind_model_cards(registries: Mapping[str, Mapping[str, Any]]) -> None:
    from speech_to_speech.models.builtin import builtin_model_cards

    for card in builtin_model_cards():
        MODEL_REGISTRY.register(card)
    for registry in registries.values():
        for spec in registry.values():
            for card in getattr(spec, "models", ()):
                MODEL_REGISTRY.register(card)
    MODEL_REGISTRY.bind(registries)


def validate_models() -> None:
    MODEL_REGISTRY.validate()
