"""`POST /api/search`：把 Serper 查询挡在服务端（A.13）。

服务端 key 是花钱的。公开 Space 上它只给登录用户、且只在 LB 授权的活跃会话里
用（`gate()`）；用户自带 key 只用于当次请求，不落库、不回显。
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from fastapi import HTTPException, Request
from loguru import logger

from app.config import demo
from app.services import identity_service, metering_service

SERPER_URL = "https://google.serper.dev/search"
# 结果条数压小，才能整段回给模型。
MAX_RESULTS = 5


async def _post(payload: dict[str, Any], key: str) -> httpx.Response:
    """单独一层：测试替换点，真实实现只打一次 Serper。"""
    async with httpx.AsyncClient(timeout=12.0) as http:
        return await http.post(
            SERPER_URL,
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json=payload,
        )


async def gate(request: Request, session_id: str) -> None:
    """放行一次服务端 key 的搜索，否则抛。

    Space 上必须是登录用户（匿名只有 IP + cookie，两个都能换），且处在 LB 授权、
    还在心跳的会话里——每个档位都算，PRO 也不例外。所有人每天限 SEARCH_PER_DAY 次。
    不在 Space 上什么都不查。
    """
    if not demo.space_id.strip():
        return
    if identity_service.oauth_login_required_reason(request):
        raise HTTPException(status_code=401, detail="Sign in with Hugging Face to use web search.")
    tier, keys, _ = identity_service.resolve_identity(request)
    if tier == "anon":
        raise HTTPException(status_code=401, detail="Sign in with Hugging Face to use web search.")
    if not await asyncio.to_thread(metering_service.session_live, session_id, keys):
        raise HTTPException(status_code=403, detail="Web search only works during a conversation.")
    if not await asyncio.to_thread(metering_service.take_search, keys):
        raise HTTPException(status_code=429, detail="Daily web search limit reached.")


def _message(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except Exception:
        return None
    return body.get("message") if isinstance(body, dict) else None


async def run(query: str, key: str) -> dict[str, Any]:
    """打一次 Serper，把结果压成模型能直接读的形状。"""
    try:
        response = await _post({"q": query, "num": MAX_RESULTS}, key)
    except httpx.RequestError as exc:
        logger.warning("serper unreachable: {}", exc)
        raise HTTPException(status_code=502, detail="Search provider unreachable.") from exc

    if response.status_code != 200:
        # Serper 的错误体带真实原因（如 "Not enough credits"）且不含 key，可以记录并转达。
        logger.warning("serper error {}: {}", response.status_code, response.text[:300])
        message = _message(response)
        detail = f"Search provider error ({response.status_code})"
        if message:
            detail += f": {message}"
        raise HTTPException(status_code=502, detail=detail)

    data = response.json()
    results = [
        {
            "title": item.get("title", ""),
            "snippet": item.get("snippet", ""),
            "url": item.get("link", ""),
        }
        for item in (data.get("organic") or [])[:MAX_RESULTS]
    ]

    # Google 有直接答案就直接给，省模型一跳。
    box = data.get("answerBox") or {}
    answer = box.get("answer") or box.get("snippet") or None
    if not answer:
        graph = data.get("knowledgeGraph") or {}
        answer = graph.get("description") or None

    return {"query": query, "answer": answer, "results": results}
