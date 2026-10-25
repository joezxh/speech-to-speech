"""A.16's `includeTurnLatency`: the aggregate travels, the rows do not.

The summary is what lets the model answer "which stage was slow"; the rows would
be 2000 `response_key`s in the prompt, which is both a privacy leak and a waste
of the budget.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from app.config import console as console_settings
from app.repositories import turn_latency_repository as repo
from app.schemas.logs import AnalyzeRequest
from app.services import log_analysis_service

EMPTY_RESULT = {"errors": [], "critical": [], "rootCauses": [], "actions": []}


def _row(key: str, *, e2e_ms: int) -> dict:
    moment = datetime.now(UTC) - timedelta(minutes=1)
    return {
        "response_key": key,
        "turn_revision": 0,
        "turn_id": "t1",
        "source": "realtime",
        "status": "completed",
        "smart_status": None,
        "e2e_ms": e2e_ms,
        "stt_ms": 120,
        "llm_ms": 800,
        "tts_ttfa_ms": 300,
        "vad_decision_ms": 40,
        "hold_ms": None,
        "logged_at": moment,
        "raw_offset": 0,
        "ingested_at": moment,
    }


def _prepare_environment(monkeypatch, tmp_path, db_session):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "pipeline-stdout.log").write_text("TURN_LATENCY {}\n", encoding="utf-8")
    monkeypatch.setattr(console_settings, "log_dir", str(log_dir))
    repo.upsert_many(
        db_session,
        [_row("k1", e2e_ms=6260), _row("k2", e2e_ms=3180), _row("k3", e2e_ms=7940)],
    )


def _request(**overrides) -> AnalyzeRequest:
    moment = datetime.now(UTC)
    body = {
        "from": (moment - timedelta(minutes=10)).isoformat(),
        "to": (moment + timedelta(minutes=1)).isoformat(),
    }
    body.update(overrides)
    return AnalyzeRequest(**body)


def _capture(monkeypatch) -> dict:
    captured: dict = {}

    def _fake(prompt, model):
        captured["prompt"] = prompt
        return json.dumps(EMPTY_RESULT), {"model": "stub"}

    monkeypatch.setattr(log_analysis_service, "_call_loopback", _fake)
    return captured


def test_the_turn_summary_travels_and_the_row_keys_do_not(
    db_session, monkeypatch, tmp_path
):
    _prepare_environment(monkeypatch, tmp_path, db_session)
    captured = _capture(monkeypatch)
    log_analysis_service._limiter.reset()

    data = log_analysis_service.analyze(_request(), session=db_session)

    assert data["sent"]["turnRows"] == 3
    prompt = captured["prompt"]
    assert "慢在哪一段" in prompt
    assert "p95" in prompt
    # No per-row identity anywhere near the model.
    assert "response_key" not in prompt
    assert "k1" not in prompt


def test_the_summary_can_be_switched_off(db_session, monkeypatch, tmp_path):
    _prepare_environment(monkeypatch, tmp_path, db_session)
    captured = _capture(monkeypatch)
    log_analysis_service._limiter.reset()

    data = log_analysis_service.analyze(
        _request(includeTurnLatency=False), session=db_session
    )

    assert data["sent"]["turnRows"] == 0
    assert "慢在哪一段" not in captured["prompt"]
    assert "轮次摘要" not in captured["prompt"]
