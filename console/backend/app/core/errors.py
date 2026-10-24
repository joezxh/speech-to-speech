from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse


@dataclass
class ApiError(Exception):
    """A stable machine code plus a human message. Never carries input values."""

    code: str
    message: str
    status: int = 400
    detail: list[dict] | None = None


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        {
            "code": exc.code,
            "message": exc.message,
            "detail": exc.detail or [],
            "requestId": getattr(request.state, "request_id", ""),
        },
        status_code=exc.status,
    )
