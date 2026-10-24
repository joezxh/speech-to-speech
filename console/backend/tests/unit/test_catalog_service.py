from pathlib import Path
import json

import pytest

from app.services import catalog_service

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parameter-catalog.min.yaml"


def test_load_reads_the_fixture():
    loaded = catalog_service.load(FIXTURE)
    assert loaded.available is True
    assert loaded.schema == "s2s-parameter-catalog-v1"
    assert loaded.generated_from == "tests@fixture"
    # Six parameters plus the one `stage: env` entry the publish tests need to
    # prove the `.env` gate (A.5).
    assert len(loaded.entries) == 7
    assert loaded.by_key()["vad.min_silence_ms"].default == 700


def test_exposure_ladder_is_cumulative():
    loaded = catalog_service.load(FIXTURE)
    assert [e.key for e in loaded.filtered(exposure="basic")] == ["vad.min_silence_ms"]
    assert [e.key for e in loaded.filtered(exposure="advanced")] == [
        "vad.min_silence_ms",
        "vad.speech_pad_ms",
    ]
    assert len(loaded.filtered(exposure="ops")) == 7


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


def test_non_finite_defaults_survive_the_json_boundary():
    """`vad.max_speech_ms` 的默认值是 `inf`（YAML `.inf`），JSON 没有无穷大。

    原值直接进 `JSONResponse` 会 500（`Out of range float values are not JSON
    compliant`），所以边界上把非有限浮点折成 `null`——与 parameter-catalog.md
    的「`inf`（YAML `null` 等价）」口径一致。
    """
    entry = catalog_service.Entry(
        stage="vad",
        backend=None,
        name="max_speech_ms",
        type="float",
        default=float("inf"),
        choices=(float("nan"), 900),
    )

    payload = entry.as_json()

    assert payload["default"] is None
    assert payload["choices"] == [None, 900]
    json.dumps(payload)
