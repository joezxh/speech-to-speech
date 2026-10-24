from app.services import validator_service


def test_unparseable_yaml_is_reported_not_raised():
    result = validator_service.validate("blocks: [", "prod", entries={})
    assert result["ok"] is False
    assert result["mode"] == "structural"
    assert result["checks"]["parse"] == "failed"


def test_a_sequence_top_level_is_refused():
    result = validator_service.validate("- a\n- b\n", "prod", entries={})
    assert result["ok"] is False
    assert "not a mapping" in result["errors"][0]["message"]


def test_missing_speech_to_speech_degrades_to_structural(monkeypatch):
    # §11.2: structural mode must be reported, never silently treated as a pass.
    monkeypatch.setattr(validator_service, "_runtime", lambda: None)
    result = validator_service.validate("schema_version: 1\n", "prod", entries={})
    assert result["mode"] == "structural"
    assert result["checks"]["load"].startswith("skipped")
