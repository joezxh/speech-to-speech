from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

# Re-exported so routers and `dependency_overrides` share one function object:
# overriding `app.db.database.get_db` in tests must actually take effect.
from app.db.database import get_db  # noqa: F401

DbSession = Annotated[Session, Depends(get_db)]
