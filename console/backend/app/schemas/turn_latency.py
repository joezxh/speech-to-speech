"""A.17 payload shapes. Field names are the contract: the panel infers nullability from them."""

from __future__ import annotations

from pydantic import BaseModel, Field

STATUSES = ("completed", "failed", "cancelled", "incomplete")

DEFAULT_LIMIT = 100
MAX_LIMIT = 500
DEFAULT_WINDOW_MINUTES = 15
MAX_WINDOW_HOURS = 24
# Aggregates are computed in memory over at most this many rows (A.17).
MAX_AGGREGATE_ROWS = 2000
# `lagS` above this and the aggregate stops describing the present (§3.9.4).
LAG_LIMIT_S = 30


class TurnLatencyWindow(BaseModel):
    from_: str = Field(alias="from")
    to: str

    model_config = {"populate_by_name": True}


class TurnLatencyStage(BaseModel):
    p50Ms: int | None = None
    p95Ms: int | None = None


class TurnLatencyE2E(TurnLatencyStage):
    maxMs: int | None = None


class TurnLatencyHold(TurnLatencyStage):
    unavailableCount: int = 0


class TurnLatencyStages(BaseModel):
    stt: TurnLatencyStage
    llm: TurnLatencyStage
    ttsTtfa: TurnLatencyStage
    vadDecision: TurnLatencyStage
    hold: TurnLatencyHold


class TurnLatencySummary(BaseModel):
    count: int
    completed: int
    failed: int
    cancelled: int
    incomplete: int
    failureRate: float | None = None
    e2e: TurnLatencyE2E
    stages: TurnLatencyStages


class TurnLatencyItem(BaseModel):
    loggedAt: str
    responseKey: str
    turnRevision: int
    source: str
    status: str
    smartStatus: str | None = None
    e2eMs: int | None = None
    sttMs: int | None = None
    llmMs: int | None = None
    ttsTtfaMs: int | None = None
    vadDecisionMs: int | None = None
    holdMs: int | None = None


class TurnLatencySource(BaseModel):
    file: str
    size: int = 0
    mtime: str | None = None


class TurnLatencyIndex(BaseModel):
    lagS: int | None = None
    ingestedAt: str | None = None
    sources: list[TurnLatencySource] = Field(default_factory=list)


class TurnLatencyPage(BaseModel):
    window: TurnLatencyWindow
    summary: TurnLatencySummary
    rows: list[TurnLatencyItem] = Field(default_factory=list)
    truncated: bool = False
    index: TurnLatencyIndex
    reasons: dict[str, str] = Field(default_factory=dict)
