"""Task 7（2026-11-17 原型对齐计划）——s2s-agent 采集器纯函数。

agent 进程本体不做端到端自动测试（验证步骤人工）；这里只测：
- usage_diff：正常递增 / 计数器归零（prev > cur → delta = cur）/ 首次（prev None）；
- tail_turn_latency：断点续读 / offset 回退容错（文件轮转后 offset 超界 → 回 0）。
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[4] / "src"
sys.path.insert(0, str(SRC))

from speech_to_speech.agent.collectors import (  # noqa: E402
    Usage,
    read_usage,
    tail_turn_latency,
    usage_diff,
)


def _log(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_usage_diff_normal_increment():
    prev = Usage(input_tokens=100, output_tokens=40, responses=2, audio_duration_s=10.0, window_s=30)
    cur = Usage(input_tokens=250, output_tokens=90, responses=5, audio_duration_s=30.0, window_s=30)
    delta = usage_diff(prev, cur)
    assert (delta.input_tokens, delta.output_tokens, delta.responses) == (150, 50, 3)
    assert delta.audio_duration_s == 20.0
    assert delta.window_s == 30  # 窗口配置透传，不做差分


def test_usage_diff_counter_reset_takes_absolute_value():
    prev = Usage(input_tokens=1000, output_tokens=400, responses=20, audio_duration_s=100.0, window_s=30)
    cur = Usage(input_tokens=50, output_tokens=10, responses=1, audio_duration_s=5.0, window_s=30)
    delta = usage_diff(prev, cur)
    assert (delta.input_tokens, delta.output_tokens, delta.responses) == (50, 10, 1)
    assert delta.audio_duration_s == 5.0


def test_usage_diff_first_sample_is_absolute():
    cur = Usage(input_tokens=120, output_tokens=60, responses=3, audio_duration_s=12.0, window_s=30)
    delta = usage_diff(None, cur)
    assert (delta.input_tokens, delta.output_tokens, delta.responses) == (120, 60, 3)


def test_usage_diff_backends_leafwise():
    prev = Usage(
        window_s=15,
        backends={
            "stt": {"calls": 4, "errors": 1, "ms_sum": 800},
            "llm": {"calls": 3, "errors": 0, "ms_sum": 1200},
            "tts": {"calls": 3, "errors": 0, "ms_sum": 600},
        },
    )
    cur = Usage(
        window_s=15,
        backends={
            "stt": {"calls": 6, "errors": 1, "ms_sum": 1500},
            "llm": {"calls": 5, "errors": 1, "ms_sum": 2000},
            "tts": {"calls": 5, "errors": 0, "ms_sum": 900},
        },
    )
    delta = usage_diff(prev, cur)
    assert delta.backends["stt"] == {"calls": 2, "errors": 0, "ms_sum": 700}
    assert delta.backends["llm"] == {"calls": 2, "errors": 1, "ms_sum": 800}
    assert delta.backends["tts"] == {"calls": 2, "errors": 0, "ms_sum": 300}


def test_usage_diff_backends_reset_and_legacy_pipeline():
    # 计数器归零（pipeline 重启）：本窗增量按累计值计
    prev = Usage(window_s=15, backends={"stt": {"calls": 100, "errors": 5, "ms_sum": 90000}})
    cur = Usage(window_s=15, backends={"stt": {"calls": 2, "errors": 0, "ms_sum": 1500}})
    delta = usage_diff(prev, cur)
    assert delta.backends["stt"] == {"calls": 2, "errors": 0, "ms_sum": 1500}

    # 旧版 pipeline 不带 backends 段：全零，不抛错
    delta = usage_diff(prev, Usage(window_s=15))
    assert delta.backends["stt"] == {"calls": 0, "errors": 0, "ms_sum": 0}


def test_read_usage_parses_backends_segment(monkeypatch):
    # read_usage 内部局部 import httpx，patch 模块本身的 get 才能拦截。
    import httpx  # noqa: PLC0415

    class _Response:
        def raise_for_status(self): ...
        def json(self):
            return {
                "input_tokens": 1,
                "output_tokens": 2,
                "responses_completed": 3,
                "audio_duration_s": 0.5,
                "window_s": 15,
                "backends": {
                    "stt": {"calls": 1, "errors": 0, "ms_sum": 120},
                    "llm": {"calls": 1, "errors": 0, "ms_sum": 900},
                    "tts": {"calls": 1, "errors": 1, "ms_sum": 400},
                },
            }

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Response())
    usage = read_usage()
    assert usage.backends["stt"] == {"calls": 1, "errors": 0, "ms_sum": 120}
    assert usage.backends["tts"] == {"calls": 1, "errors": 1, "ms_sum": 400}


def test_tail_turn_latency_resumes_from_offset(tmp_path):
    target = tmp_path / "pipeline-stdout.log"
    lines = [
        "2026-11-17T10:00:00Z INFO TURN_LATENCY {\"response_key\": \"r1\", \"e2e_s\": 2.0}",
        "2026-11-17T10:00:05Z INFO unrelated human line",
        "2026-11-17T10:00:10Z INFO TURN_LATENCY {\"response_key\": \"r2\", \"e2e_s\": 2.5, \"audio_duration_s\": 4.0}",
    ]
    _log(target, lines)

    offset, rows = tail_turn_latency(str(target), 0)
    assert offset > 0
    assert [row["response_key"] for row in rows] == ["r1", "r2"]
    assert rows[0]["e2e_ms"] == 2000
    # 行内时间戳进 logged_at（解析规则与 console 索引器一致）
    assert rows[0]["logged_at"] is not None and rows[0]["logged_at"].year == 2026

    # 断点续读：从上次的 offset 起，只拿到新增行
    lines.append("2026-11-17T10:00:20Z INFO TURN_LATENCY {\"response_key\": \"r3\", \"e2e_s\": 1.5}")
    _log(target, lines)
    new_offset, more = tail_turn_latency(str(target), offset)
    assert [row["response_key"] for row in more] == ["r3"]
    assert new_offset >= offset


def test_tail_turn_latency_tolerates_offset_beyond_file(tmp_path):
    target = tmp_path / "pipeline-stdout.log"
    _log(target, ["2026-11-17T10:00:00Z INFO TURN_LATENCY {\"response_key\": \"r9\"}"])
    # 轮转后文件变小：旧 offset 超界 → 回 0 重读，不抛错
    offset, rows = tail_turn_latency(str(target), 10_000)
    assert offset > 0
    assert [row["response_key"] for row in rows] == ["r9"]


def test_tail_turn_latency_missing_file_is_empty(tmp_path):
    offset, rows = tail_turn_latency(str(tmp_path / "nope.log"), 0)
    assert (offset, rows) == (0, [])
