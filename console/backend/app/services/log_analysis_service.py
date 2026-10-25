"""A.16: one LLM call over a bounded, redacted window of the four logs.

Two properties carry the whole design:

* **What leaves the container is decided here, not by the prompt.** Redaction,
  the line budget and the template fold all happen before the request is built,
  and the numbers reported back (`sent`) describe the text that was actually
  sent — not the text that was read.
* **No local fallback.** If the loopback LLM face is off, the answer is 502.
  Falling back to the pipeline's own model would push analysis load onto the
  GPU that is serving audio (Global Constraint 4.3), and the latency spike
  would be blamed on the code being analysed.

Single-flight plus a 6/5min window are both here because an LLM analysis is a
paid, rate-limited side effect: two operators clicking at once must not double
the bill, and a stuck retry loop must not drain the quota.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from loguru import logger

from app.config import console as console_settings
from app.core.errors import ApiError
from app.repositories.audit_repository import AuditRepository
from app.services import log_service

RATE_LIMIT = (6, 300)
TIMEOUT_S = 45.0
MAX_LINES_DEFAULT = 800
MAX_LINES_CAP = 2000
MAX_WINDOW = timedelta(hours=24)

# A.16 lists exactly these keys. A model that adds one has answered a different
# question, and a model that drops one has answered incompletely — both are
# upstream format errors, not "close enough".
_RESULT_KEYS: dict[str, set[str]] = {
    "errors": {"signature", "count", "firstSeen", "lastSeen", "level", "sample"},
    "critical": {"signature", "impact", "rationale", "evidence"},
    "rootCauses": {"hypothesis", "confidence", "evidence"},
    "actions": {"title", "detail", "expectedEffect", "risk"},
}

_AUTH = re.compile(r"(?i)\b(authorization)(\s*[:=]\s*)(?:bearer\s+)?\S+")
_SECRET_FIELD = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?key|secret[_-]?key|token|secret|password|key)(\s*[:=]\s*)\S+"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_SK = re.compile(r"\bsk-[A-Za-z0-9_-]{6,}")
_HF = re.compile(r"\bhf_[A-Za-z0-9]{6,}")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}")

_PRIORITY = {"ERROR": 0, "WARN": 1, "INFO": 2}


class WindowTooLarge(Exception):
    """A.16 caps the analysed window at 24h — beyond that the answer is a guess."""


class AnalysisBusy(Exception):
    """One analysis at a time: the second caller gets 429, not a queue slot."""


class AnalysisRateLimited(Exception):
    """More than `RATE_LIMIT` analyses inside the window."""


class AnalysisTimeout(Exception):
    """The loopback call overran `TIMEOUT_S`."""


class AnalysisUnavailable(Exception):
    """The loopback LLM face is off, unreachable, or answered outside the contract."""


@dataclass(slots=True)
class LogLineStub:
    """The only shape `prepare()` needs: text, level and (maybe) a timestamp."""

    text: str
    level: str = "INFO"
    ts: str = ""


def _parse_ts(value: str | None) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text.replace(",", "."))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def validate_window(from_iso: str | None, to_iso: str | None) -> tuple[datetime, datetime]:
    """Returns the window or refuses it; the caller maps the two failures."""
    start = _parse_ts(from_iso)
    end = _parse_ts(to_iso)
    if start is None or end is None:
        raise ValueError("from/to must be ISO 8601 timestamps")
    if start > end:
        raise ValueError("from must not be after to")
    if end - start > MAX_WINDOW:
        raise WindowTooLarge("the analysis window is capped at 24 hours")
    return start, end


def redact(text: str) -> str:
    """Strip secret *values*, never the key names (§10.1 keeps names readable)."""
    text = _AUTH.sub(r"\1\2***", text)
    text = _SECRET_FIELD.sub(r"\1\2***", text)
    text = _BEARER.sub("Bearer ***", text)
    text = _SK.sub("***", text)
    text = _HF.sub("***", text)
    return _JWT.sub("***", text)


def _cap(max_lines: int | None) -> int:
    if not max_lines or max_lines <= 0:
        return MAX_LINES_DEFAULT
    return min(int(max_lines), MAX_LINES_CAP)


def _template(text: str) -> str:
    """Everything that varies between two instances of the same message."""
    collapsed = re.sub(r"\d+", "#", text)
    return re.sub(r"\s+", " ", collapsed).strip()


def _format(line: LogLineStub) -> str:
    head = f"[{line.ts}] " if line.ts else ""
    return f"{head}{line.level} {line.text}"


def _fold(lines: Sequence[LogLineStub]) -> list[str]:
    """Keep the first and last of a consecutive run, and count the rest.

    A retry loop emits the same line 300 times; sending it 300 times spends the
    budget on one signature and buries the other 20 errors.
    """
    folded: list[str] = []
    index = 0
    while index < len(lines):
        template = _template(lines[index].text)
        end = index + 1
        while end < len(lines) and _template(lines[end].text) == template:
            end += 1
        folded.append(_format(lines[index]))
        if end - index > 1:
            folded.append(f"... 同模板连续 {end - index - 1} 行，末条：{lines[end - 1].text[:120]}")
        index = end
    return folded


SYSTEM_PROMPT = (
    "你是 speech-to-speech 服务的值班工程师。下面是从容器 supervisor 日志里挑出的行，"
    "已经脱敏并按级别优先截断。只依据这些行归纳，日志里没有的事实不要臆测。\n"
    "输出一个 JSON 对象，键恰好是 errors、critical、rootCauses、actions，不得增删：\n"
    "errors: [{signature, count, firstSeen, lastSeen, level, sample}]\n"
    "critical: [{signature, impact, rationale, evidence}]\n"
    "rootCauses: [{hypothesis, confidence, evidence}]\n"
    "actions: [{title, detail, expectedEffect, risk}]\n"
)


def _header(sent: dict[str, Any]) -> str:
    return (
        f"## 上下文\n窗口内共送入 {sent['lines']} 行"
        + (f"（另有 {sent['droppedLines']} 行因预算未送）" if sent["truncated"] else "")
        + "\n"
    )


def prepare(
    lines: Sequence[LogLineStub],
    *,
    max_lines: int | None = None,
    turn_block: str = "",
    turn_rows: int = 0,
) -> tuple[dict[str, Any], str]:
    """Select, redact, fold, then report what was actually sent."""
    cap = _cap(max_lines)
    # Priority first (errors are the reason anyone opens this page), original
    # order second, so the prompt still reads chronologically.
    ranked = sorted(
        enumerate(lines),
        key=lambda item: (_PRIORITY.get(item[1].level.upper(), 2), item[0]),
    )
    selected = sorted(ranked[:cap], key=lambda item: item[0])
    chosen = [
        LogLineStub(text=redact(line.text), level=line.level.upper(), ts=line.ts)
        for _, line in selected
    ]
    dropped = len(lines) - len(chosen)
    sent: dict[str, Any] = {
        "lines": len(chosen),
        "estimatedTokens": 0,
        "truncated": dropped > 0,
        "droppedLines": max(dropped, 0),
        "turnRows": int(turn_rows),
    }
    prompt = (
        SYSTEM_PROMPT
        + "\n"
        + _header(sent)
        + turn_block
        + "\n## 日志行\n"
        + "\n".join(_fold(chosen))
        + "\n\n只输出 JSON，不要解释。"
    )
    # ceil(chars / 4) is the A.16 estimate: a token is roughly four characters
    # for this mix of English identifiers and Chinese messages.
    sent["estimatedTokens"] = math.ceil(len(prompt) / 4)
    return sent, prompt


def validate_result(payload: Any) -> dict[str, list[dict[str, Any]]]:
    """A key-for-key check of the four blocks (A.16 says "不多不少")."""
    if not isinstance(payload, dict):
        raise AnalysisUnavailable("the model did not return a JSON object")
    result: dict[str, list[dict[str, Any]]] = {}
    for block, keys in _RESULT_KEYS.items():
        rows = payload.get(block)
        if not isinstance(rows, list):
            raise AnalysisUnavailable(f"missing block: {block}")
        for row in rows:
            if not isinstance(row, dict):
                raise AnalysisUnavailable(f"{block} must contain objects")
            if set(row) != keys:
                extra = sorted(set(row) - keys)
                missing = sorted(keys - set(row))
                raise AnalysisUnavailable(f"{block} keys mismatch: extra={extra} missing={missing}")
        result[block] = rows
    return result


class RateLimiter:
    """A sliding window of `limit` hits per `window_s` seconds, in memory only.

    In memory is correct here: console runs a single worker (§3.1), and a
    restart resetting the counter is the failure everybody prefers.
    """

    def __init__(self, limit: int = RATE_LIMIT[0], window_s: float = RATE_LIMIT[1]) -> None:
        self.limit = limit
        self.window_s = window_s
        self._hits: list[float] = []
        self._lock = threading.Lock()

    def hit(self) -> None:
        now = time.monotonic()
        with self._lock:
            cutoff = now - self.window_s
            self._hits = [at for at in self._hits if at > cutoff]
            if len(self._hits) >= self.limit:
                raise AnalysisRateLimited(
                    f"at most {self.limit} analyses per {int(self.window_s)}s"
                )
            self._hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_limiter = RateLimiter()
_lock = threading.Lock()


@contextmanager
def _exclusive() -> Iterator[None]:
    """Non-blocking single-flight: busy is answered, never queued."""
    if not _lock.acquire(blocking=False):
        raise AnalysisBusy("another log analysis is still running")
    try:
        yield
    finally:
        _lock.release()


def _value(request: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(request, dict):
            if name in request:
                return request[name]
        elif getattr(request, name, None) is not None:
            return getattr(request, name)
    return default


def _loopback_url() -> str:
    base = (console_settings.pipeline_base_url or "http://127.0.0.1:8765").rstrip("/")
    return f"{base}/v1/chat/completions"


def _load_lines(
    *, start: datetime, end: datetime, process: Any, level: Any, q: str
) -> list[LogLineStub]:
    page = log_service.read(
        log_dir=console_settings.log_dir,
        process=process or None,
        level=level or None,
        from_iso=start.isoformat().replace("+00:00", "Z"),
        to_iso=end.isoformat().replace("+00:00", "Z"),
        q=q or "",
        limit=MAX_LINES_CAP,
    )
    return [LogLineStub(text=line["text"], level=line["level"], ts=line["ts"]) for line in page["lines"]]


def _strip_fence(text: str) -> str:
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[1] if "\n" in body else ""
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3]
    return body.strip()


def _call_loopback(prompt: str, model: str) -> tuple[str, dict[str, Any]]:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    try:
        response = httpx.post(_loopback_url(), json=body, timeout=TIMEOUT_S)
    except httpx.TimeoutException as exc:
        raise AnalysisTimeout("the LLM did not answer within 45s") from exc
    except httpx.HTTPError as exc:
        raise AnalysisUnavailable(f"loopback LLM unreachable: {exc}") from exc
    if response.status_code == 501:
        # The proxy is mounted but this deployment's LLM backend is in-process;
        # A.16 deliberately does not fall back to it.
        raise AnalysisUnavailable(
            "日志归纳需要 ENABLE_LLM_PROXY 且 LLM 后端为 chat-completions / responses-api"
        )
    if response.status_code >= 400:
        raise AnalysisUnavailable(f"loopback LLM returned {response.status_code}")
    try:
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AnalysisUnavailable("loopback LLM returned an unexpected envelope") from exc
    answered = str(payload.get("model") or model)
    return _strip_fence(str(content)), {"model": answered}


def _audit(
    session: Any,
    *,
    actor: str,
    role: str,
    profile: str,
    fields: list[str],
    result: str,
    error_code: str | None,
    duration_s: float,
) -> str:
    if session is None:
        return ""
    try:
        row = AuditRepository(session).record(
            actor=actor,
            role=role,
            action="logs.analyze",
            profile=profile,
            fields=fields,
            result=result,
            error_code=error_code,
            duration_s=duration_s,
        )
        return str(row.id)
    except Exception as exc:  # noqa: BLE001 - the analysis already succeeded
        logger.warning("logs.analyze audit failed: {}", exc)
        return ""


def analyze(
    request: Any,
    *,
    actor: str = "",
    role: str = "operator",
    profile: str = "prod",
    session: Any = None,
    turn_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A.16's `data`. Every failure is mapped to a stable code, none to a 500."""
    from_iso = _value(request, "from_", "from")
    to_iso = _value(request, "to")
    process = list(_value(request, "process", default=[]) or [])
    level = list(_value(request, "level", default=[]) or [])
    q = str(_value(request, "q", default="") or "")
    max_lines = int(_value(request, "max_lines", "maxLines", default=MAX_LINES_DEFAULT))
    want_turns = bool(_value(request, "include_turn_latency", "includeTurnLatency", default=True))

    started = time.monotonic()
    try:
        start, end = validate_window(from_iso, to_iso)
    except WindowTooLarge as exc:
        raise ApiError("log_window_too_large", str(exc), 400) from exc
    except ValueError as exc:
        raise ApiError("invalid_parameter", str(exc), 400) from exc

    try:
        _limiter.hit()
    except AnalysisRateLimited as exc:
        raise ApiError("log_analysis_rate_limited", str(exc), 429) from exc

    audit_fields = ["from", "to", "process", "level", "q", "sentLines", "estimatedTokens", "turnRows"]

    try:
        with _exclusive():
            try:
                lines = _load_lines(start=start, end=end, process=process, level=level, q=q)
            except log_service.LogsUnavailable as exc:
                raise ApiError("logs_unavailable", str(exc), 503) from exc

            # The turn summary is an aggregate, never the rows: A.16 sends no
            # `response_key` anywhere near the model.
            from app.services import turn_latency_service  # noqa: PLC0415 - cycle at import time

            turn_block, turn_rows = turn_latency_service.prompt_block(
                start, end, enabled=want_turns, summary=turn_summary, session=session
            )
            sent, prompt = prepare(
                lines, max_lines=max_lines, turn_block=turn_block, turn_rows=turn_rows
            )

            try:
                content, meta = _call_loopback(prompt, model="s2s-console")
            except AnalysisTimeout as exc:
                raise ApiError("log_analysis_timeout", str(exc), 504) from exc
            except AnalysisUnavailable as exc:
                raise ApiError("log_analysis_unavailable", str(exc), 502) from exc

            try:
                result = validate_result(json.loads(content))
            except json.JSONDecodeError as exc:
                raise ApiError(
                    "log_analysis_unavailable", "the model did not return parseable JSON", 502
                ) from exc
            except AnalysisUnavailable as exc:
                raise ApiError("log_analysis_unavailable", str(exc), 502) from exc
    except AnalysisBusy as exc:
        raise ApiError("log_analysis_busy", str(exc), 429) from exc

    duration_ms = int((time.monotonic() - started) * 1000)
    audit_id = _audit(
        session,
        actor=actor,
        role=role,
        profile=profile,
        fields=audit_fields,
        result="ok",
        error_code=None,
        duration_s=duration_ms / 1000,
    )
    analysis_id = f"an_{int(time.time() * 1000):x}"
    return {
        "analysisId": analysis_id,
        "model": meta["model"],
        "durationMs": duration_ms,
        "sent": sent,
        "result": result,
        "auditId": audit_id,
    }
