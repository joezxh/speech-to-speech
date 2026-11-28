"""流量延迟统计：P95 TTFT、错误率、top 错误实例、实例级 TTFT/RTF。

数据源：turn_latency（A5 上报的逐轮行，毫秒真值）与 param_instance_metric
（alloc 计数增量）。公式只在后端算；无数据一律 None/空，绝不编 0。
percentile 在 Python 侧算：SQLite 无 percentile_cont，跨库口径一致。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.param_instance_metric import ParamInstanceMetric
from app.models.turn_latency import TurnLatencyRow

_WINDOWS = {"5m": timedelta(minutes=5), "1h": timedelta(hours=1), "24h": timedelta(hours=24)}


def percentile(values: list[int], q: float) -> int | None:
    """线性插值分位数（q∈[0,1]）；空列表 None。"""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return int(ordered[0])
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return int(round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction))


def _range(window: str, now: datetime) -> tuple[datetime, datetime]:
    delta = _WINDOWS.get(window, _WINDOWS["1h"])
    return now - delta, now


def latency_stats(db: Session, window: str = "1h", *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    since, until = _range(window, now)

    # ── turn_latency：TTFT / RTF / 机器聚合 ──────────────────────
    rows = db.execute(
        select(
            TurnLatencyRow.tts_ttfa_ms,
            TurnLatencyRow.e2e_ms,
            TurnLatencyRow.audio_duration_s,
            TurnLatencyRow.machine_id,
            TurnLatencyRow.instance_id,
        ).where(TurnLatencyRow.logged_at >= since, TurnLatencyRow.logged_at < until)
    ).all()

    all_ttfts = [row[0] for row in rows if row[0] is not None]
    p95_ttft_ms = percentile(all_ttfts, 0.95)

    machine_buckets: dict[str, dict] = {}
    instance_buckets: dict[str, dict] = {}
    for ttfa, e2e, audio, machine_id, instance_id in rows:
        for bucket, key in ((machine_buckets, machine_id), (instance_buckets, instance_id)):
            if key is None:
                continue
            stats = bucket.setdefault(key, {"turns": 0, "ttfts": [], "rtfs": []})
            stats["turns"] += 1
            if ttfa is not None:
                stats["ttfts"].append(ttfa)
            if e2e and audio is not None and e2e > 0:
                stats["rtfs"].append(audio * 1000.0 / e2e)

    def _machine_row(machine_id: str, stats: dict) -> dict:
        return {
            "machine_id": machine_id,
            "turns": stats["turns"],
            "avg_ttft_ms": round(sum(stats["ttfts"]) / len(stats["ttfts"]), 1) if stats["ttfts"] else None,
            "p95_ttft_ms": percentile(stats["ttfts"], 0.95),
            "rtf": round(sum(stats["rtfs"]) / len(stats["rtfs"]), 3) if stats["rtfs"] else None,
        }

    by_machine_ttft = [
        _machine_row(machine_id, stats)
        for machine_id, stats in sorted(machine_buckets.items())
    ]

    # ── instance_metric：错误率 / top 错误实例 ────────────────────
    metric_rows = db.execute(
        select(
            ParamInstanceMetric.instance_id,
            ParamInstanceMetric.alloc_ok,
            ParamInstanceMetric.alloc_fail_no_instance,
            ParamInstanceMetric.alloc_fail_instance_503,
        ).where(
            ParamInstanceMetric.observed_at >= since,
            ParamInstanceMetric.observed_at < until,
        )
    ).all()

    per_instance: dict[str, dict[str, int]] = {}
    total_ok = 0
    total_fail = 0
    for instance_id, ok, fail_no, fail_503 in metric_rows:
        bucket = per_instance.setdefault(instance_id, {"ok": 0, "fail": 0})
        bucket["ok"] += int(ok or 0)
        bucket["fail"] += int(fail_no or 0) + int(fail_503 or 0)
        total_ok += bucket["ok"]
        total_fail += bucket["fail"]

    total = total_ok + total_fail
    err_rate = round(total_fail / total, 4) if total else None

    top_err_instance = None
    for instance_id, bucket in per_instance.items():
        attempts = bucket["ok"] + bucket["fail"]
        if not bucket["fail"]:
            continue
        rate = round(bucket["fail"] / attempts, 4) if attempts else None
        if top_err_instance is None or bucket["fail"] > top_err_instance["errors"]:
            top_err_instance = {
                "instance_id": instance_id,
                "errors": bucket["fail"],
                "err_rate": rate,
            }

    instances = []
    for instance_id, bucket in sorted(per_instance.items()):
        latency = instance_buckets.get(instance_id, {})
        attempts = bucket["ok"] + bucket["fail"]
        instances.append(
            {
                "instance_id": instance_id,
                "ttft_ms": percentile(latency.get("ttfts", []), 0.95),
                "rtf": (
                    round(sum(latency["rtfs"]) / len(latency["rtfs"]), 3)
                    if latency.get("rtfs")
                    else None
                ),
                "err_rate": round(bucket["fail"] / attempts, 4) if attempts else None,
            }
        )

    return {
        "p95_ttft_ms": p95_ttft_ms,
        "by_machine_ttft": by_machine_ttft,
        "err_rate": err_rate,
        "top_err_instance": top_err_instance,
        "instances": instances,
    }
