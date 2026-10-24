from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from app.config import app as app_settings
from app.config import console as console_settings
from app.core.errors import ApiError, api_error_handler
from app.core.logging import configure_logging
from app.core.router_registry import register_api_routers
from app.core.spa import mount_spa
from app.db.database import SessionLocal
from app.middleware.request_id import RequestIdMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.services import publish_flow_service

configure_logging(app_settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The previous container may have been cut between publish steps 6 and 9;
    # settle those rows before accepting requests.
    session = SessionLocal()
    try:
        outcomes = publish_flow_service.recover_pending(session)
        for outcome in outcomes:
            logger.warning("recovered an interrupted publish: {}", outcome)
    except Exception as exc:  # noqa: BLE001 - a bad DB must not stop the API from booting
        logger.error("startup recovery skipped: {}", exc)
    finally:
        session.close()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="s2s-console", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_middleware(
        SecurityHeadersMiddleware,
        max_body_bytes=app_settings.max_body_bytes,
        # A voice upload is capped by its own endpoint (10 MiB), plus multipart
        # overhead; the 2 MiB guard is for JSON payloads.
        upload_body_bytes=console_settings.voice_max_bytes + 1024 * 1024,
    )
    app.add_middleware(RequestIdMiddleware)
    app.add_exception_handler(ApiError, api_error_handler)

    # Order matters: every API prefix first, SPA last (spec §10.2.3).
    register_api_routers(app)

    mount_spa(app, console_settings.static_dir)
    return app


app = create_app()
