from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import database


def _build(url: str):
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    bind = create_engine(url, connect_args=connect_args, future=True)
    return bind, sessionmaker(bind=bind, autoflush=False, autocommit=False, future=True)


engine, SessionLocal = _build(database.database_url)


def init_engine(url: str | None = None) -> None:
    """Rebind the module-level engine/session factory (tests point at a temp file)."""
    global engine, SessionLocal
    engine, SessionLocal = _build(url or database.database_url)


def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
