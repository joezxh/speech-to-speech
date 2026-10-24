from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 200
    message: str = "success"
    data: T


def ok(data):
    """The only success envelope. /health and /api/config deliberately bypass it."""
    return {"code": 200, "message": "success", "data": data}


class PageData(BaseModel, Generic[T]):
    # `list` is a builtin name but it is the contract the SPA consumes (A.0).
    list: list[T]
    total: int
    page: int
    pageSize: int
