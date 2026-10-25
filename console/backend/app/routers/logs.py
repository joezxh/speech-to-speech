"""A.15 (read the four logs) and A.16 (summarise them with the loopback LLM).

Neither endpoint writes anything except one audit row; the log files themselves
are opened read-only. Both are side channels: a failure here must never look
like a failure of the pipeline, which is why the reader degrades to a partial
page and the analyser answers with a stable code instead of a 500.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query

from app.config import console as console_settings
from app.core.errors import ApiError
from app.core.security import CurrentUser, require_user
from app.deps import DbSession
from app.schemas.common import ApiResponse
from app.schemas.logs import (
    MAX_LIMIT,
    MAX_QUERY_CHARS,
    AnalyzeRequest,
    AnalyzeResponse,
    LogPage,
)
from app.services import log_analysis_service, log_service

router = APIRouter(prefix="/api/v1", tags=["logs"])

# A.15: a page that takes longer than this is answered with what was read.
READ_TIMEOUT_S = 1.5
# A.15's default window when the client sends neither bound.
DEFAULT_WINDOW_MINUTES = 15


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_limit(raw: str) -> int:
    """Manual, because `Query(ge=..., le=...)` answers 422 and A.15 promises 400."""
    try:
        limit = int(raw)
    except (TypeError, ValueError) as exc:
        raise ApiError("invalid_parameter", "limit must be an integer", 400) from exc
    if limit < 1 or limit > MAX_LIMIT:
        raise ApiError("invalid_parameter", f"limit must be between 1 and {MAX_LIMIT}", 400)
    return limit


@router.get("/logs", response_model=ApiResponse[LogPage])
async def list_logs(
    process: list[str] = Query(default=["console", "pipeline"]),
    level: list[str] = Query(default=[]),
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    q: str = Query(default=""),
    after: str = Query(default=""),
    limit: str = Query(default="500"),
    user: CurrentUser = Depends(require_user),
) -> ApiResponse[LogPage]:
    """A.15: the tail of the four supervisor files, filtered in the reader."""
    limit_value = _parse_limit(limit)
    if len(q) > MAX_QUERY_CHARS:
        raise ApiError(
            "invalid_parameter", f"q must be at most {MAX_QUERY_CHARS} characters", 400
        )

    if from_ or to:
        start_iso, end_iso = from_, to
    else:
        # The default window is decided here, not in `log_service`: the reader
        # stays a pure function of its arguments, and a caller that wants the
        # whole file can still ask for it.
        end = datetime.now(UTC)
        start_iso, end_iso = _iso(end - timedelta(minutes=DEFAULT_WINDOW_MINUTES)), _iso(end)

    try:
        page = await asyncio.wait_for(
            asyncio.to_thread(
                log_service.read,
                log_dir=console_settings.log_dir,
                process=process,
                level=level,
                from_iso=start_iso,
                to_iso=end_iso,
                q=q,
                after=after,
                limit=limit_value,
            ),
            READ_TIMEOUT_S,
        )
    except TimeoutError:
        # Not a 504: the panel would go blank exactly when the container is
        # too busy to write, which is when an operator needs it most.
        page = log_service.partial(limit=limit_value)
    except log_service.LogsUnavailable as exc:
        raise ApiError("logs_unavailable", str(exc), 503) from exc
    except ValueError as exc:
        raise ApiError("invalid_parameter", str(exc), 400) from exc
    return ApiResponse(data=LogPage(**page))


@router.post("/logs/analyze", response_model=ApiResponse[AnalyzeResponse])
def analyze_logs(
    body: AnalyzeRequest,
    db: DbSession,
    user: CurrentUser = Depends(require_user),
) -> ApiResponse[AnalyzeResponse]:
    """A.16: one bounded, redacted window goes to the loopback LLM, once."""
    data = log_analysis_service.analyze(
        body, actor=user.username, role=user.role, session=db
    )
    return ApiResponse(data=AnalyzeResponse(**data))
