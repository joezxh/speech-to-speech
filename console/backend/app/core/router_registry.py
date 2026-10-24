from __future__ import annotations

from fastapi import FastAPI


def register_api_routers(app: FastAPI) -> None:
    """Single place where route groups are added, in prefix order.

    /api/v1 (JWT), /api (anonymous), /v1 (reverse proxy) — never reordered,
    because the SPA catch-all is registered after this call returns.
    """
    from app.routers import (  # noqa: PLC0415 - import cycle avoidance
        auth,
        catalog,
        health,
        instances,
        profiles,
        status,
        voices,
    )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(catalog.router)
    app.include_router(profiles.router)
    app.include_router(instances.router)
    app.include_router(voices.router)
    app.include_router(status.router)
