"""智能设置（原型 smartPanel）：拉取 agent 侧当前参数与日志、AI 分析给出参数推荐。

两步接口共用一个模块：
* fetch —— 机器实际参数（machine_config_service.config_view）+ 最近日志
  （log_service，agent 通过 POST /api/v1/agent/logs 推到 console 日志文件）。
* analyze —— LLM 优先（loopback /v1/chat/completions，与 logs.analyze 同一通道、
  同一限流与单飞约束、同一脱敏），LLM 不可用/超时/输出不合规时按关键词规则
  兜底，响应里 `source` 标明 "llm" 或 "rules"，前端据此灰显"应用"。

规则兜底是保守建议（只动 1 个参数），绝不做机器变更；应用走既有
PUT /machines/{id}/draft（部署页）或对话态热更下发（前台），本模块只出建议。
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from app.config import console as console_settings
from app.core.errors import ApiError
from app.repositories.audit_repository import AuditRepository
from app.services import log_service, log_analysis_service, machine_config_service
from app.services.machine_service import MachineDetail

TIMEOUT_S = 45.0
MAX_LOG_LINES = 200

# 与 log_analysis_service 同口径的限流/单飞：LLM 分析是付费副作用。
_rate_limiter = log_analysis_service.RateLimiter(limit=6, window_s=300.0)
_lock = threading.Lock()

SMART_SYSTEM_PROMPT = (
    "你是 speech-to-speech 语音服务的参数调优顾问。下面给出操作员描述的故障现象、"
    "机器当前参数（key=value）与近期日志行（已脱敏）。只依据这些材料给建议，"
    "没有依据的事实不要臆测。输出一个 JSON 对象，键恰好是 summary、recommendations，不得增删：\n"
    "summary: 一句话归纳故障判断；\n"
    "recommendations: [{key, from, to, reason}]，每条是一个参数的调整建议，"
    "key 为参数键（目录键 <stage>.<name> 或热更参数名），from 为当前值（未知填 \"\"），"
    "to 为建议值（字符串），reason 为一句理由；不超过 5 条。\n"
    "只输出 JSON，不要解释。"
)


# ---- 拉取（agent 侧参数 + 最近日志） -----------------------------------------


def _machine_summary(db: Session, machine_id: str) -> dict:
    machine: MachineDetail = machine_config_service_machine(db, machine_id)
    return {
        "machineId": machine.machineId,
        "platform": machine.platform,
        "driver": machine.driver,
        "gpu": machine.gpu,
        "gpuTotalGb": machine.gpuTotalGb,
        "state": machine.state,
        "version": machine.version,
    }


def machine_config_service_machine(db: Session, machine_id: str):
    from app.services import machine_service  # noqa: PLC0415 - 延迟导入避免环

    return machine_service.get_machine(db, machine_id)


def _recent_logs(machine_id: str) -> list[dict[str, str]]:
    """优先取含 machine_id 的行，没有则回退到最近日志尾部（拉取不为空即可见）。"""
    since = (datetime.now(UTC) - timedelta(hours=24)).isoformat().replace("+00:00", "Z")
    for needle in (machine_id, ""):
        try:
            page = log_service.read(
                log_dir=console_settings.log_dir,
                from_iso=since,
                q=needle,
                limit=MAX_LOG_LINES,
            )
        except log_service.LogsUnavailable as exc:
            logger.info("smart-settings fetch: logs unavailable: {}", exc)
            return []
        lines = page.get("lines") or []
        if lines:
            return [
                {"ts": line.get("ts", ""), "level": line.get("level", ""), "text": line.get("text", "")}
                for line in lines
            ]
    return []


def fetch(db: Session, machine_id: str) -> dict:
    if machine_config_service_machine(db, machine_id) is None:  # 不存在 → KeyError 由路由映射
        raise KeyError(machine_id)
    return {
        "machine": _machine_summary(db, machine_id),
        "params": machine_config_service.config_view(db, machine_id),
        "logs": _recent_logs(machine_id),
    }


# ---- 分析（LLM 优先，规则兜底） ----------------------------------------------


def _cap_logs(logs: list[str], limit: int = MAX_LOG_LINES) -> list[str]:
    return [line for line in logs if str(line).strip()][-limit:]


def _prompt(fault: str, params: dict[str, str], logs: list[str]) -> str:
    param_lines = "\n".join(f"{key}={value}" for key, value in sorted(params.items())) or "（未提供）"
    log_lines = "\n".join(log_analysis_service.redact(line) for line in _cap_logs(logs)) or "（未提供）"
    return (
        f"## 故障现象\n{log_analysis_service.redact(fault)}\n\n"
        f"## 当前参数\n{param_lines}\n\n"
        f"## 近期日志\n{log_lines}\n\n只输出 JSON。"
    )


def _validate_result(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise log_analysis_service.AnalysisUnavailable("the model did not return a JSON object")
    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise log_analysis_service.AnalysisUnavailable("missing summary")
    rows = payload.get("recommendations")
    if not isinstance(rows, list):
        raise log_analysis_service.AnalysisUnavailable("missing recommendations")
    out: list[dict[str, str]] = []
    for row in rows[:5]:
        if not isinstance(row, dict) or set(row) != {"key", "from", "to", "reason"}:
            raise log_analysis_service.AnalysisUnavailable("recommendations keys mismatch")
        out.append({key: str(row[key]) for key in ("key", "from", "to", "reason")})
    return {"summary": summary.strip(), "recommendations": out}


def _call_llm(prompt: str) -> tuple[dict[str, Any], str]:
    body = {
        "model": "s2s-console",
        "messages": [
            {"role": "system", "content": SMART_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    url = f"{(console_settings.pipeline_base_url or 'http://127.0.0.1:8765').rstrip('/')}/v1/chat/completions"
    try:
        response = httpx.post(url, json=body, timeout=TIMEOUT_S)
    except httpx.TimeoutException as exc:
        raise log_analysis_service.AnalysisTimeout("the LLM did not answer within 45s") from exc
    except httpx.HTTPError as exc:
        raise log_analysis_service.AnalysisUnavailable(f"loopback LLM unreachable: {exc}") from exc
    if response.status_code >= 400:
        raise log_analysis_service.AnalysisUnavailable(f"loopback LLM returned {response.status_code}")
    try:
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        model = str(payload.get("model") or "s2s-console")
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise log_analysis_service.AnalysisUnavailable("loopback LLM returned an unexpected envelope") from exc
    text = str(content).strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return _validate_result(json.loads(text)), model


# 规则兜底（原型 AI_RULES 的保守子集）：按故障关键词给出单参数建议。
_RULES: tuple[tuple[tuple[str, ...], dict[str, str]], ...] = (
    (("截断", "打断", "被切", "误切", "不生效"), {"key": "min_silence_ms", "to": "700", "reason": "句尾被切/打断不生效时先调大判停静音"}),
    (("误触发", "噪音", "噪声", "幻觉", "自动说话"), {"key": "thresh", "to": "0.7", "reason": "噪声误触发时调高 VAD 语音阈值"}),
    (("显存", "oom", "内存溢出", "溢出"), {"key": "num_pipelines", "to": "1", "reason": "显存溢出时先降低并发路数"}),
    (("识别错", "语言", "混说", "中英"), {"key": "qwen3_asr_language", "to": "zh", "reason": "语言漂移时固定识别语言"}),
)
_GENERIC_RULE = {"key": "min_silence_ms", "to": "500", "reason": "日志信号不足：先按手册保守档复查句末静音"}


def _rule_recommendations(fault: str, params: dict[str, str]) -> dict[str, Any]:
    text = fault.lower()
    rule = _GENERIC_RULE
    for keywords, candidate in _RULES:
        if any(word in text for word in keywords):
            rule = candidate
            break
    rec = {
        "key": rule["key"],
        "from": str(params.get(rule["key"], "")),
        "to": rule["to"],
        "reason": rule["reason"],
    }
    return {
        "summary": "LLM 不可用，以下为关键词规则的保守建议，应用前请人工确认。",
        "recommendations": [rec],
    }


def analyze(db: Session, payload: Any, *, actor: str) -> dict:
    fault = str(payload.fault or "").strip()
    if not fault:
        raise ApiError("invalid_parameter", "fault description is required", 400)
    params = {str(k): str(v) for k, v in (payload.params or {}).items()}
    logs = [str(line) for line in (payload.logs or [])]

    started = time.monotonic()
    source, model, result = "rules", "", None
    try:
        _rate_limiter.hit()
    except log_analysis_service.AnalysisRateLimited as exc:
        raise ApiError("smart_analysis_rate_limited", str(exc), 429) from exc
    if not _lock.acquire(blocking=False):
        raise ApiError("smart_analysis_busy", "another smart analysis is still running", 429)
    try:
        try:
            result, model = _call_llm(_prompt(fault, params, logs))
            source = "llm"
        except (
            log_analysis_service.AnalysisUnavailable,
            log_analysis_service.AnalysisTimeout,
            json.JSONDecodeError,
        ) as exc:
            logger.info("smart-settings analyze: LLM fallback to rules: {}", exc)
    finally:
        _lock.release()

    if result is None:
        result = _rule_recommendations(fault, params)

    duration_ms = int((time.monotonic() - started) * 1000)
    audit_id = ""
    try:
        audit_id = str(
            AuditRepository(db)
            .record(
                actor=actor,
                role="",
                action="smart.analyze",
                profile=str(payload.machineId or ""),
                fields=["fault", "params", "logs"],
                result="ok" if source == "llm" else "fallback",
            )
            .id
        )
    except Exception as exc:  # noqa: BLE001 - 分析已成功，审计失败不回滚
        logger.warning("smart.analyze audit failed: {}", exc)

    return {
        "summary": result["summary"],
        "source": source,
        "model": model,
        "recommendations": result["recommendations"],
        "durationMs": duration_ms,
        "auditId": audit_id,
    }
