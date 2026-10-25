from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from loguru import logger

from app.config import app as app_settings
from app.config import console as console_settings
from app.config import demo as demo_settings
from app.core.errors import ApiError, api_error_handler
from app.core.logging import configure_logging
from app.core.router_registry import register_api_routers
from app.core.spa import mount_spa
from app.db.database import SessionLocal
from app.middleware.request_id import RequestIdMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.services import (
    bootstrap_service,
    identity_service,
    instance_seed,
    metering_service,
    publish_flow_service,
    turn_latency_indexer,
)

configure_logging(app_settings.log_level)


async def _usage_sweeper() -> None:
    """回收静默掉的计量会话（崩了 / 关页没发 beacon）（demo/server.py:227-233）。"""
    while True:
        await asyncio.sleep(metering_service.REAP_AFTER_SEC)
        try:
            await asyncio.to_thread(metering_service.sweep)
        except Exception as exc:  # noqa: BLE001 - 一次 sweep 失败不该杀掉后台任务
            logger.warning("usage sweep failed: {}", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    session = SessionLocal()
    try:
        # A fresh volume has no account and no registration page, so the image
        # would boot into a console nobody can sign in to. DEFAULT_ADMIN_*
        # seeds one; an empty password leaves the behaviour unchanged.
        try:
            bootstrap_service.ensure_default_admin(session)
        except Exception as exc:  # noqa: BLE001 - a bad DB must not stop the API from booting
            session.rollback()
            logger.error("default admin bootstrap skipped: {}", exc)

        # The previous container may have been cut between publish steps 6 and 9;
        # settle those rows before accepting requests.
        try:
            outcomes = publish_flow_service.recover_pending(session)
            for outcome in outcomes:
                logger.warning("recovered an interrupted publish: {}", outcome)
        except Exception as exc:  # noqa: BLE001 - a bad DB must not stop the API from booting
            logger.error("startup recovery skipped: {}", exc)

        # P1.0: declarative seed is idempotent; a missing/empty path is a no-op.
        try:
            for alert in instance_seed.apply_seed(session):
                logger.warning("instances seed: {}", alert)
        except Exception as exc:  # noqa: BLE001 - a bad seed file must not stop the API
            session.rollback()
            logger.error("instances seed skipped: {}", exc)
    finally:
        session.close()

    # Order matters: the sweeper depends on the metering tables existing (§9.1).
    # The parameter tree is already up; the usage store is bare sqlite3 (D11).
    sweeper: asyncio.Task | None = None
    if demo_settings.limiter_enabled:
        metering_service.init()
        sweeper = asyncio.create_task(_usage_sweeper())

    # A.17's indexer: one background task in this process (console is a single
    # worker), reading the pipeline's own log file. It never blocks a request.
    indexer = asyncio.create_task(turn_latency_indexer.run_forever())

    try:
        yield
    finally:
        indexer.cancel()
        with suppress(asyncio.CancelledError):
            await indexer
        if sweeper is not None:
            sweeper.cancel()
            with suppress(asyncio.CancelledError):
                await sweeper


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

    # OAuth routes are appended by attach(), so this has to happen before
    # mount_spa registers the catch-all; otherwise /oauth/huggingface/login
    # would receive index.html instead of a redirect.
    if demo_settings.auth_enabled:
        identity_service.attach(app)

    # Order matters: every API prefix first, SPA last (spec §10.2.3).
    register_api_routers(app)

    mount_spa(app, console_settings.static_dir)
    return app


app = create_app()
