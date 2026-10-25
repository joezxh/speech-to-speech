"""A.16's guard rails: redaction, the sent budget, single-flight, throttling.

The analysis is an LLM call the operator pays for and reads as advice, so the
parts that must be provably right are the ones that decide *what leaves the
container* and *how often*.
"""

from __future__ import annotations

import math

import pytest

from app.services import log_analysis_service


def test_redacts_authorization_and_sk_keys():
    text = log_analysis_service.redact(
        "Authorization: Bearer abc.def.ghi\nkey=sk-1234567890\ntoken: hf_abcdef"
    )
    assert "sk-1234567890" not in text
    assert "hf_abcdef" not in text
    assert text.count("***") >= 3


def test_sent_stats_report_estimate_and_drops():
    lines = [log_analysis_service.LogLineStub(text="x" * 400, level="ERROR", ts="")] * 20
    sent, payload = log_analysis_service.prepare(lines, max_lines=5)
    assert sent["lines"] == 5
    assert sent["droppedLines"] == 15
    assert sent["truncated"] is True
    assert sent["estimatedTokens"] == math.ceil(len(payload) / 4)


def test_second_concurrent_call_is_busy():
    with log_analysis_service._exclusive():
        with pytest.raises(log_analysis_service.AnalysisBusy):
            with log_analysis_service._exclusive():
                pass


def test_rate_limit_allows_six_in_five_minutes():
    limiter = log_analysis_service.RateLimiter(limit=6, window_s=300)
    for _ in range(6):
        limiter.hit()
    with pytest.raises(log_analysis_service.AnalysisRateLimited):
        limiter.hit()


def test_window_over_24h_is_too_large():
    with pytest.raises(log_analysis_service.WindowTooLarge):
        log_analysis_service.validate_window("2026-10-23T00:00:00Z", "2026-10-24T01:00:00Z")
