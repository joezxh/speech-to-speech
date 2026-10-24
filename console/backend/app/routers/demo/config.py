from __future__ import annotations

from fastapi import APIRouter

from app.services import demo_config_service

router = APIRouter(prefix="/api", tags=["demo"])


@router.get("/config")
def get_config():
    """Anonymous and unenveloped: the voice page reads it before it has a cookie."""
    return demo_config_service.config()
