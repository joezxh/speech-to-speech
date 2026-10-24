from types import SimpleNamespace

import pytest

from app.core import exposure
from app.core.errors import ApiError


def test_secret_names_are_detected_by_their_tail():
    assert exposure.is_secret("llm.responses_api_api_key")
    assert exposure.is_secret("tts.token")
    assert not exposure.is_secret("vad.min_silence_ms")


def test_mask_replaces_only_non_empty_secrets():
    masked = exposure.mask({"llm.api_key": "sk-real", "stt.token": "", "vad.min_silence_ms": 700})
    assert masked == {"llm.api_key": "***", "stt.token": "", "vad.min_silence_ms": 700}


def test_operator_is_refused_on_expert_fields():
    known = {"stt.language": SimpleNamespace(exposure="expert")}
    with pytest.raises(ApiError) as caught:
        exposure.refuse_protected("operator", {"stt.language": "en"}, known)
    assert caught.value.code == "forbidden"
    assert caught.value.detail == [{"field": "stt.language", "exposure": "expert"}]


def test_admin_is_never_refused():
    known = {"stt.language": SimpleNamespace(exposure="expert")}
    exposure.refuse_protected("admin", {"stt.language": "en"}, known)


def test_profile_name_cannot_leave_the_config_dir():
    with pytest.raises(ApiError):
        exposure.validate_profile_name("../../etc/passwd")
    assert exposure.validate_profile_name("prod") == "prod"
