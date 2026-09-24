"""
Model call monitoring for the speech-to-speech pipeline.

Provides a lightweight, dependency-tolerant monitor that records, for every
TTS / STT / LLM service call:

1. **Latency** - wall-clock duration of the model call.
2. **Resource usage** - GPU utilisation / VRAM, CPU % and RAM % sampled at a
   fixed interval *while the call runs* (so we capture peaks, not just the
   value at two instants).
3. **Input / output payloads** - a structured summary of what went in and what
   came out (truncated so we never log raw audio bytes or huge transcripts).

Two kinds of lines are written to a dedicated, rotating log file
(``model_metrics.log`` by default, configurable):

* ``MODEL_CALL_METRICS`` - one JSON line per individual model call (latency +
  resources + input/output). This is the raw feed for per-request analysis.
* ``MODEL_CALL_AGGREGATE`` - a periodic (default every 30s) roll-up per model
  category with call count, **error rate**, **throughput (QPS)**, and latency
  **p50 / p95 / max**. This is the feed for dashboards / alerting without
  having to post-process the raw lines.

The metrics logger is configured with ``propagate=False`` so these JSON lines
go *only* to ``model_metrics.log`` and never interleave with the human-readable
business logs.

GPU metrics use ``torch.cuda`` utilisation (via nvidia-smi when nvidia-ml-py is
absent); VRAM uses ``torch.cuda.memory_allocated``. ``psutil`` is used for
CPU/RAM and imported lazily so the module imports cleanly even when missing.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Optional

logger = logging.getLogger("speech_to_speech.model_monitor")

MODEL_MONITOR_MARKER = "MODEL_CALL_METRICS"
MODEL_AGGREGATE_MARKER = "MODEL_CALL_AGGREGATE"

# Log file configuration (env-overridable; also tunable via configure_model_monitor).
METRICS_LOG_PATH = os.environ.get("MODEL_METRICS_LOG", "model_metrics.log")
METRICS_LOG_MAX_BYTES = int(os.environ.get("MODEL_METRICS_LOG_MAX_BYTES", str(20 * 1024 * 1024)))
METRICS_LOG_BACKUPS = int(os.environ.get("MODEL_METRICS_LOG_BACKUPS", "5"))

# Optional dependencies -------------------------------------------------------
try:
    import psutil
except Exception:  # pragma: no cover - psutil is an optional extra
    psutil = None

try:
    import torch
except Exception:  # pragma: no cover - torch is always present at runtime
    torch = None


def _truncate(value: Any, max_len: int = 512) -> Any:
    """Keep logged strings small; never dump raw multi-KB payloads."""
    if isinstance(value, str) and len(value) > max_len:
        return value[:max_len] + f"...<{len(value) - max_len} chars omitted>"
    return value


def audio_summary(audio: Any) -> dict[str, Any]:
    """Compact, dependency-light description of an audio payload."""
    try:
        import numpy as np

        arr = np.asarray(audio)
        return {
            "dtype": str(arr.dtype),
            "shape": list(arr.shape),
            "nbytes": int(arr.nbytes),
        }
    except Exception:
        length = len(audio) if hasattr(audio, "__len__") else None
        return {"type": type(audio).__name__, "len": length}


def _percentile(xs: list[float], p: float) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return round(s[f], 4)
    return round(s[f] + (s[c] - s[f]) * (k - f), 4)


class _ResourceSampler:
    """Runs a daemon thread that polls system resources for the call duration."""

    def __init__(self, interval: float = 0.1) -> None:
        self.interval = max(0.02, float(interval))
        self._stop = threading.Event()
        self._gpu_util: list[int] = []
        self._vram_mb: list[float] = []
        self._cpu_pct: list[float] = []
        self._ram_pct: list[float] = []
        self._ram_mb: list[float] = []
        # GPU util % is expensive to query (needs nvidia-ml-py or nvidia-smi), so we
        # cache the nvidia-smi reading and refresh it at most every _SMI_THROTTLE_S.
        self._smi_cache: dict[int, int] = {}
        self._smi_cache_at: float = 0.0
        self._SMI_THROTTLE_S = 0.5
        self._thread = threading.Thread(target=self._run, name="model-monitor-sampler", daemon=True)

    def _smi_utilization(self) -> dict[int, int] | None:
        """Read per-device GPU utilisation via nvidia-smi (throttled)."""
        now = time.perf_counter()
        if now - self._smi_cache_at < self._SMI_THROTTLE_S and self._smi_cache:
            return self._smi_cache
        try:
            import shutil
            import subprocess

            smi = shutil.which("nvidia-smi")
            if not smi:
                return None
            out = subprocess.run(
                [smi, "--query-gpu=index,utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            ).stdout
            result: dict[int, int] = {}
            for line in out.strip().splitlines():
                parts = line.split(",")
                if len(parts) == 2:
                    result[int(parts[0].strip())] = int(parts[1].strip())
            if result:
                self._smi_cache = result
                self._smi_cache_at = now
            return result
        except Exception:
            return None

    def _sample_gpu(self) -> None:
        if torch is None or not torch.cuda.is_available():
            return
        try:
            # Ensure a CUDA context exists so memory queries work even before the
            # first tensor is allocated in this process.
            torch.cuda.init()
            # VRAM is cheap and reliable via torch.
            for i in range(torch.cuda.device_count()):
                self._vram_mb.append(torch.cuda.memory_allocated(i) / (1024 * 1024))
            # GPU utilisation: prefer torch (needs nvidia-ml-py), fall back to
            # nvidia-smi which is present in virtually every CUDA image.
            util_map: dict[int, int] = {}
            try:
                for i in range(torch.cuda.device_count()):
                    util_map[i] = int(torch.cuda.utilization(i))
            except Exception:
                smi = self._smi_utilization()
                if smi:
                    util_map = smi
            if util_map:
                self._gpu_util.extend(util_map.values())
        except Exception:
            pass

    def _run(self) -> None:
        # Prime psutil's internal counter so the first in-loop reading is valid.
        if psutil is not None:
            psutil.cpu_percent(interval=None)
        while not self._stop.is_set():
            tick_start = time.perf_counter()
            if psutil is not None:
                try:
                    self._cpu_pct.append(psutil.cpu_percent(interval=None))
                    vm = psutil.virtual_memory()
                    self._ram_pct.append(vm.percent)
                    self._ram_mb.append(vm.used / (1024 * 1024))
                except Exception:
                    pass
            self._sample_gpu()
            elapsed = time.perf_counter() - tick_start
            sleep_for = max(0.0, self.interval - elapsed)
            if sleep_for > 0:
                self._stop.wait(sleep_for)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)

    def summary(self) -> dict[str, Any]:
        gpu_util = list(self._gpu_util)
        vram = list(self._vram_mb)
        cpu = list(self._cpu_pct)
        ram_pct = list(self._ram_pct)
        ram_mb = list(self._ram_mb)

        def _peak(xs: list[float]) -> Optional[float]:
            return max(xs) if xs else None

        def _avg(xs: list[float]) -> Optional[float]:
            return round(sum(xs) / len(xs), 2) if xs else None

        return {
            "gpu_available": torch is not None and torch.cuda.is_available(),
            "gpu_util_peak_percent": _peak(gpu_util),
            "gpu_util_avg_percent": _avg(gpu_util),
            "vram_used_mb_peak": _peak(vram),
            "cpu_percent_avg": _avg(cpu),
            "ram_percent_avg": _avg(ram_pct),
            "ram_used_mb_avg": _avg(ram_mb),
            "sample_ticks": len(cpu) + len(gpu_util),
        }


@dataclass
class CallRecord:
    """Structured record for a single model call."""

    category: str
    model_name: str
    start_ts: float
    duration_s: Optional[float] = None
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    resources: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def set_input(self, **kwargs: Any) -> None:
        self.input.update(kwargs)

    def set_output(self, **kwargs: Any) -> None:
        self.output.update(kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "model_name": self.model_name,
            "start_time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.start_ts)),
            "duration_s": self.duration_s,
            "error": self.error,
            "input": self.input,
            "output": self.output,
            "resources": self.resources,
        }


class _Aggregator:
    """Collects completed call records and periodically emits a roll-up."""

    def __init__(self, interval_s: float, flush_fn: Callable[[list[CallRecord]], None]) -> None:
        self.interval_s = max(1.0, float(interval_s))
        self._flush_fn = flush_fn
        self._lock = threading.Lock()
        self._buf: list[CallRecord] = []
        self._timer: Optional[threading.Timer] = None
        self._stopped = False

    def add(self, rec: CallRecord) -> None:
        with self._lock:
            self._buf.append(rec)

    def start(self) -> None:
        self._schedule()

    def _schedule(self) -> None:
        if self._stopped:
            return
        self._timer = threading.Timer(self.interval_s, self._flush)
        self._timer.daemon = True
        self._timer.start()

    def _flush(self) -> None:
        recs: list[CallRecord] = []
        with self._lock:
            recs = self._buf
            self._buf = []
        if recs:
            try:
                self._flush_fn(recs)
            except Exception:
                pass
        self._schedule()

    def stop(self) -> None:
        self._stopped = True
        if self._timer is not None:
            self._timer.cancel()


class ModelMonitor:
    """Records per-call metrics via the :meth:`trace` context manager."""

    def __init__(
        self,
        enabled: bool = True,
        sample_interval: float = 0.1,
        aggregate_interval_s: float = 30.0,
        metrics_log_path: str = METRICS_LOG_PATH,
    ) -> None:
        self.enabled = enabled
        self.sample_interval = sample_interval
        self.aggregate_interval_s = aggregate_interval_s
        self.metrics_log_path = metrics_log_path
        self._started = False
        self._agg: Optional[_Aggregator] = None

    # -- lifecycle ----------------------------------------------------------
    def _start(self) -> None:
        """Idempotent one-time setup: file handler + aggregate timer."""
        if self._started:
            return
        self._started = True
        self._setup_file_logging()
        if self.enabled:
            self._agg = _Aggregator(self.aggregate_interval_s, self._flush_aggregate)
            self._agg.start()

    def _setup_file_logging(self) -> None:
        """Attach a rotating file handler to this logger; keep it separate from
        the business (root) logs by disabling propagation."""
        try:
            from logging.handlers import RotatingFileHandler

            log_dir = os.path.dirname(os.path.abspath(self.metrics_log_path))
            if log_dir and not os.path.isdir(log_dir):
                os.makedirs(log_dir, exist_ok=True)
            handler = RotatingFileHandler(
                self.metrics_log_path,
                maxBytes=METRICS_LOG_MAX_BYTES,
                backupCount=METRICS_LOG_BACKUPS,
                encoding="utf-8",
            )
            handler.setLevel(logging.INFO)
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            logger.propagate = False  # metrics -> file only, never business logs
        except Exception as exc:  # pragma: no cover - defensive
            # If we cannot open the file (e.g. read-only FS in a test), fall back
            # to the default behaviour: metrics go to the root logger (stdout).
            logger.propagate = True
            logger.warning("model_monitor: file logging unavailable (%s); using root logger", exc)

    # -- tracing ------------------------------------------------------------
    @contextmanager
    def trace(
        self,
        category: str,
        model_name: str,
        input: Optional[dict[str, Any]] = None,
    ) -> Iterator[CallRecord]:
        rec = CallRecord(
            category=category,
            model_name=str(model_name),
            start_ts=time.time(),
        )
        if input:
            rec.input.update(input)

        if not self.enabled:
            yield rec
            return

        sampler = _ResourceSampler(interval=self.sample_interval)
        sampler.start()
        start = time.perf_counter()
        try:
            yield rec
            rec.error = None
        except Exception as exc:
            # Record the failure, then let the caller's handler deal with it.
            rec.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            sampler.stop()
            rec.duration_s = round(time.perf_counter() - start, 4)
            rec.resources = sampler.summary()
            self._emit(rec)

    def _emit(self, rec: CallRecord) -> None:
        payload = {MODEL_MONITOR_MARKER: rec.to_dict()}
        logger.info(json.dumps(payload, ensure_ascii=False, default=str))
        if self._agg is not None:
            self._agg.add(rec)

    def _flush_aggregate(self, recs: list[CallRecord]) -> None:
        by_cat: dict[str, list[CallRecord]] = {}
        for r in recs:
            by_cat.setdefault(r.category, []).append(r)
        cats: dict[str, Any] = {}
        for cat, rs in by_cat.items():
            durs = sorted(x.duration_s for x in rs if x.duration_s is not None)
            errs = sum(1 for x in rs if x.error)
            cats[cat] = {
                "calls": len(rs),
                "errors": errs,
                "error_rate": round(errs / len(rs), 4) if rs else 0.0,
                "avg_latency_s": round(sum(durs) / len(durs), 4) if durs else None,
                "p50_latency_s": _percentile(durs, 50),
                "p95_latency_s": _percentile(durs, 95),
                "max_latency_s": durs[-1] if durs else None,
            }
        payload = {
            MODEL_AGGREGATE_MARKER: {
                "window_seconds": self.aggregate_interval_s,
                "window_start": time.strftime(
                    "%Y-%m-%dT%H:%M:%S", time.localtime(min(r.start_ts for r in recs))
                ),
                "total_calls": len(recs),
                "throughput_qps": round(len(recs) / self.aggregate_interval_s, 4),
                "by_category": cats,
            }
        }
        logger.info(json.dumps(payload, ensure_ascii=False, default=str))


_default_monitor: Optional[ModelMonitor] = None
_default_monitor_lock = threading.Lock()


def get_model_monitor() -> ModelMonitor:
    """Return the process-wide :class:`ModelMonitor` singleton (lazily started)."""
    global _default_monitor
    if _default_monitor is None:
        with _default_monitor_lock:
            if _default_monitor is None:
                _default_monitor = ModelMonitor()
    _default_monitor._start()
    return _default_monitor


def configure_model_monitor(
    enabled: Optional[bool] = None,
    sample_interval: Optional[float] = None,
    aggregate_interval_s: Optional[float] = None,
    metrics_log_path: Optional[str] = None,
) -> None:
    """Tune monitoring at runtime (e.g. disable in tests, change sampling rate or
    the metrics log destination)."""
    monitor = get_model_monitor()
    if enabled is not None:
        # Disabling after the aggregator started: stop it so no more roll-ups.
        if not enabled and monitor._agg is not None:
            monitor._agg.stop()
            monitor._agg = None
        monitor.enabled = enabled
    if sample_interval is not None:
        monitor.sample_interval = max(0.02, float(sample_interval))
    if aggregate_interval_s is not None:
        monitor.aggregate_interval_s = max(1.0, float(aggregate_interval_s))
        if monitor._agg is not None:
            monitor._agg.interval_s = monitor.aggregate_interval_s
    if metrics_log_path is not None:
        monitor.metrics_log_path = metrics_log_path
        # Re-attach the file handler for the new path.
        for h in list(logger.handlers):
            logger.removeHandler(h)
        monitor._started = False
        monitor._start()
