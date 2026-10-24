from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SessionUpdateRequest(BaseModel):
    """A.9's body. `scope`/`target` are validated in the service, not here.

    A `Literal` here would raise `RequestValidationError` and hand FastAPI's
    default 422 body back to the client, which has no `code` field — the console
    frontend translates codes, never freeform text (Global Constraints).
    """

    scope: str = "all"
    target: int | str | None = None
    session: dict[str, Any] = Field(default_factory=dict)
