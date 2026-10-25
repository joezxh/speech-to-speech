"""A.17: read-only turn latency. No delete, no export, no recompute knob."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import OperationalError

from app.core.errors import ApiError
from app.core.security import CurrentUser, require_user
from app.deps import DbSession
from app.schemas.common import ApiResponse
from app.schemas.turn_latency import DEFAULT_LIMIT, MAX_LIMIT, STATUSES, TurnLatencyPage
from app.services import turn_latency_service

router = APIRouter(prefix="/api/v1", tags=["turn-latency"])


def _parse_limit(raw: str) -> int:
    """Manual so an out-of-range value is A.17's 400, not FastAPI's 422."""
    try:
        limit = int(raw)
    except (TypeError, ValueError) as exc:
        raise ApiError("invalid_parameter", "limit must be an integer", 400) from exc
    if limit < 1 or limit > MAX_LIMIT:
        raise ApiError("invalid_parameter", f"limit must be between 1 and {MAX_LIMIT}", 400)
    return limit


@router.get("/turn-latency", response_model=ApiResponse[TurnLatencyPage])
async def read_turn_latency(
    db: DbSession,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    status: list[str] = Query(default=[]),
    limit: str = Query(default=str(DEFAULT_LIMIT)),
    user: CurrentUser = Depends(require_user),
) -> ApiResponse[TurnLatencyPage]:
    limit_value = _parse_limit(limit)
    if status:
        unknown = [name for name in status if name not in STATUSES]
        if unknown:
            # A value outside the enum must not be silently dropped: the panel
            # would then show everything while the filter chip says otherwise.
            raise ApiError("invalid_parameter", f"unknown status: {sorted(unknown)}", 400)

    try:
        start, end = turn_latency_service.resolve_window(from_, to)
    except ValueError as exc:
        raise ApiError("invalid_parameter", str(exc), 400) from exc

    try:
        data = await asyncio.to_thread(
            turn_latency_service.read, db, start=start, end=end, status=status, limit=limit_value
        )
    except OperationalError as exc:
        # The table is created by `alembic upgrade head`; a console that booted
        # against an un-migrated database says so instead of 500-ing.
        raise ApiError("turn_latency_unavailable", "turn_latency is not migrated", 503) from exc
    return ApiResponse(data=TurnLatencyPage(**data))
