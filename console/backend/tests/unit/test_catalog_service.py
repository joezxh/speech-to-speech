from pathlib import Path

import pytest

from app.services import catalog_service

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parameter-catalog.min.yaml"


def test_load_reads_the_fixture():
    loaded = catalog_service.load(FIXTURE)
    assert loaded.available is True
    assert loaded.schema == "s2s-parameter-catalog-v1"
    assert loaded.generated_from == "tests@fixture"
    assert len(loaded.entries) == 6
    assert loaded.by_key()["vad.min_silence_ms"].default == 700


def test_exposure_ladder_is_cumulative():
    loaded = catalog_service.load(FIXTURE)
    assert [e.key for e in loaded.filtered(exposure="basic")] == ["vad.min_silence_ms"]
    assert [e.key for e in loaded.filtered(exposure="advanced")] == [
        "vad.min_silence_ms",
        "vad.speech_pad_ms",
    ]
    assert len(loaded.filtered(exposure="ops")) == 6


def test_unknown_exposure_is_refused():
    loaded = catalog_service.load(FIXTURE)
    with pytest.raises(catalog_service.CatalogError):
        loaded.filtered(exposure="secret")


def test_variant_keys_name_the_backend_shared_keys():
    loaded = catalog_service.load(FIXTURE)
    assert loaded.variant_keys == ["llm.model_name"]
    assert [e.backend for e in loaded.entries_for("llm.model_name")] == [
        "chat-completions",
        "responses-api",
    ]


def test_missing_file_is_unavailable_not_an_exception(tmp_path):
    loaded = catalog_service.load(tmp_path / "nope.yaml")
    assert loaded.available is False
    assert loaded.hint
