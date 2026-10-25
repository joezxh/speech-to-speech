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
        realtime,
        runtime,
        sessions,
        status,
        voices,
    )
    from app.routers.demo import ROUTERS as DEMO_ROUTERS  # noqa: PLC0415

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(catalog.router)
    app.include_router(profiles.router)
    app.include_router(instances.router)
    app.include_router(runtime.router)
    app.include_router(voices.router)
    app.include_router(sessions.router)
    app.include_router(status.router)

    # The demo face is anonymous and unenveloped (A.13), so it goes last among the
    # API groups but still before the SPA catch-all.
    for router in DEMO_ROUTERS:
        app.include_router(router)

    # /v1 反代最后注册：它只开两条精确路径，不和 /api 抢前缀。
    app.include_router(realtime.router)
