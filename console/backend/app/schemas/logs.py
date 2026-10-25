"""A.15 / A.16 payload shapes.

The response models exist so the four analysis blocks are checked on the way
out, not only on the way in: A.16 says "不多不少", and a model that adds a key
to `errors[]` has answered a different question. `validate_result()` already
refuses that upstream; these models make sure the envelope cannot drift either.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

PROCESSES = ("console", "pipeline")
LEVELS = ("ERROR", "WARN", "INFO")

DEFAULT_LIMIT = 500
MAX_LIMIT = 2000
MAX_QUERY_CHARS = 200


class LogLine(BaseModel):
    ts: str = ""
    process: str
    stream: str
    level: str
    text: str
    file: str
    offset: int


class LogSource(BaseModel):
    """Listed even when absent (`size:0`): "the file is missing" is evidence."""

    file: str
    size: int = 0
    mtime: str | None = None


class LogScanned(BaseModel):
    files: int = 0
    bytes: int = 0


class LogPage(BaseModel):
    lines: list[LogLine]
    nextCursor: str = ""
    reset: bool = False
    truncated: bool = False
    scanned: LogScanned = Field(default_factory=LogScanned)
    sources: list[LogSource] = Field(default_factory=list)


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    from_: str = Field(alias="from")
    to: str
    process: list[str] = Field(default_factory=list)
    level: list[str] = Field(default_factory=list)
    q: str = Field(default="", max_length=MAX_QUERY_CHARS)
    max_lines: int = Field(default=800, alias="maxLines", ge=1, le=MAX_LIMIT)
    include_turn_latency: bool = Field(default=True, alias="includeTurnLatency")


class SentStats(BaseModel):
    lines: int
    estimatedTokens: int
    truncated: bool
    droppedLines: int
    turnRows: int = 0


class ErrorRow(BaseModel):
    signature: str
    count: int
    firstSeen: str = ""
    lastSeen: str = ""
    level: str = "ERROR"
    sample: str = ""


class CriticalRow(BaseModel):
    signature: str
    impact: str = ""
    rationale: str = ""
    evidence: str = ""


class RootCauseRow(BaseModel):
    hypothesis: str
    confidence: float = 0.0
    evidence: str = ""


class ActionRow(BaseModel):
    title: str
    detail: str = ""
    expectedEffect: str = ""
    risk: str = ""


class LogAnalysisResult(BaseModel):
    errors: list[ErrorRow] = Field(default_factory=list)
    critical: list[CriticalRow] = Field(default_factory=list)
    rootCauses: list[RootCauseRow] = Field(default_factory=list)
    actions: list[ActionRow] = Field(default_factory=list)


class AnalyzeResponse(BaseModel):
    analysisId: str
    model: str
    durationMs: int
    sent: SentStats
    result: LogAnalysisResult
    auditId: str = ""
