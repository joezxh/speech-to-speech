from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import database

connect_args = {"check_same_thread": False} if database.database_url.startswith("sqlite") else {}
engine = create_engine(database.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
