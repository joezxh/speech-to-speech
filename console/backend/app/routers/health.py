from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db.database import engine

router = APIRouter()


def _package_version() -> str:
    try:
        return version("speech-to-speech")
    except PackageNotFoundError:  # a bare checkout, not the image
        return "0.0.0+dev"


@router.get("/api/v1/health", include_in_schema=False)
async def health() -> JSONResponse:
    """Bare object: docker-compose's healthcheck consumes it directly (A.0.1)."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"code": "db_unavailable", "message": "database is not reachable"}, status_code=503)
    return JSONResponse({"status": "ok", "version": _package_version()})
