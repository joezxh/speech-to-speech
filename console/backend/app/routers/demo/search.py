from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import demo
from app.services import search_service

router = APIRouter(prefix="/api", tags=["demo"])


class SearchRequest(BaseModel):
    query: str = ""
    # 用户自带的 key：只在本次请求用，不存。
    key: str | None = None
    # 调用方被授权的会话，让服务端 key 的搜索能绑到一个活着的会话上。
    sessionId: str | None = None


@router.post("/search")
async def search(payload: SearchRequest, request: Request):
    query = (payload.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Empty query.")

    key = (payload.key or "").strip()
    if not key:
        if not demo.server_search:
            raise HTTPException(status_code=503, detail="Search is not configured.")
        await search_service.gate(request, payload.sessionId or "")
        key = demo.serper_api_key.strip()

    return await search_service.run(query, key)
