"""A.15's reader: cursors, rotation, level inference, and the budget.

A log panel that loses lines on rotation, or that invents a level bucket, is
worse than no panel: the operator reads it as evidence.
"""

from __future__ import annotations

import pytest

from app.services import log_service

SCAN_LINE = '{"time":"2026-10-24T10:00:00Z","level":"error","msg":"boom"}'


def test_infers_error_level_from_a_json_field(tmp_path):
    (tmp_path / "pipeline-stderr.log").write_text(SCAN_LINE + "\n", encoding="utf-8")
    page = log_service.read(log_dir=tmp_path, process=["pipeline"])
    assert page["lines"][0]["level"] == "ERROR"
    assert page["lines"][0]["stream"] == "stderr"


def test_warning_and_info_levels_have_no_unknown_bucket(tmp_path):
    (tmp_path / "console-stdout.log").write_text("WARNING slow\nrouter started\n", encoding="utf-8")
    page = log_service.read(log_dir=tmp_path, process=["console"])
    assert [line["level"] for line in page["lines"]] == ["WARN", "INFO"]


def test_cursor_returns_only_new_bytes(tmp_path):
    path = tmp_path / "pipeline-stdout.log"
    path.write_text("one\n", encoding="utf-8")
    first = log_service.read(log_dir=tmp_path, process=["pipeline"])
    path.write_text("one\ntwo\n", encoding="utf-8")
    second = log_service.read(log_dir=tmp_path, process=["pipeline"], after=first["nextCursor"])
    assert [line["text"] for line in second["lines"]] == ["two"]
    assert second["reset"] is False


def test_rotated_file_resets_and_rereads(tmp_path):
    path = tmp_path / "pipeline-stdout.log"
    path.write_text("old\n", encoding="utf-8")
    cursor = log_service.read(log_dir=tmp_path, process=["pipeline"])["nextCursor"]
    path.unlink()
    path.write_text("new\n", encoding="utf-8")
    page = log_service.read(log_dir=tmp_path, process=["pipeline"], after=cursor)
    assert page["reset"] is True
    assert [line["text"] for line in page["lines"]] == ["new"]


def test_limit_truncates_and_says_so(tmp_path):
    (tmp_path / "pipeline-stdout.log").write_text("\n".join(f"l{i}" for i in range(50)) + "\n", encoding="utf-8")
    page = log_service.read(log_dir=tmp_path, process=["pipeline"], limit=10)
    assert len(page["lines"]) == 10
    assert page["truncated"] is True


def test_missing_log_dir_raises_logs_unavailable(tmp_path):
    with pytest.raises(log_service.LogsUnavailable):
        log_service.read(log_dir=tmp_path / "nope", process=["pipeline"])
