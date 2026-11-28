"""联网搜索 provider：Anspire / 博查 / Serper / You.com / Tavily。

有 key 走真实 API（按配置顺序取第一个有 key 的），全部无 key 或全部失败时
返回内置演示结果，格式与真实一致，模型无需区分。
"""

from __future__ import annotations

import httpx
from loguru import logger

from app.config import demo, tools

MAX_RESULTS = 5
PROVIDERS = ("anspire", "bocha", "serper", "you", "tavily")

DEMO_RESULTS = [
    {
        "title": "Anspire AI Search API 文档",
        "url": "https://open.anspire.cn/document/",
        "snippet": "调用 AI 搜索回答用户问题，支持实时全网检索与结构化数据。",
    },
    {
        "title": "博查搜索 API 产品服务文档",
        "url": "https://api.bocha.cn/",
        "snippet": "面向 AI 应用的实时搜索 API，返回标题、摘要与来源链接。",
    },
]


def _api_keys() -> dict[str, str]:
    return {
        "anspire": tools.anspire_api_key.strip(),
        "bocha": tools.bocha_api_key.strip(),
        "serper": demo.serper_api_key.strip(),
        "you": tools.you_api_key.strip(),
        "tavily": tools.tavily_api_key.strip(),
    }


def _demo(query: str) -> dict:
    return {"mode": "demo", "provider": "demo", "query": query, "results": DEMO_RESULTS, "answer": None}


async def _call_anspire(query: str, key: str, top_k: int) -> dict:
    async with httpx.AsyncClient(timeout=12.0) as http:
        response = await http.get(
            "https://plugin.anspire.cn/api/ntsearch/search",
            params={"query": query, "top_k": str(top_k)},
            headers={"Authorization": f"Bearer {key}"},
        )
    response.raise_for_status()
    data = response.json()
    pages = (data.get("data") or {}).get("webPages") or []
    return {
        "results": [
            {"title": p.get("name", ""), "url": p.get("url", ""), "snippet": p.get("snippet", "")}
            for p in pages[:top_k]
        ],
        "answer": None,
    }


async def _call_bocha(query: str, key: str, top_k: int) -> dict:
    async with httpx.AsyncClient(timeout=12.0) as http:
        response = await http.post(
            "https://api.bocha.cn/v1/web-search",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"query": query, "summary": True, "count": top_k},
        )
    response.raise_for_status()
    data = response.json()
    pages = (data.get("data") or {}).get("webPages") or {}
    values = pages.get("value") if isinstance(pages, dict) else pages
    return {
        "results": [
            {"title": p.get("name", ""), "url": p.get("url", ""), "snippet": p.get("summary") or p.get("snippet", "")}
            for p in (values or [])[:top_k]
        ],
        "answer": None,
    }


async def _call_serper(query: str, key: str, top_k: int) -> dict:
    async with httpx.AsyncClient(timeout=12.0) as http:
        response = await http.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": query, "num": top_k},
        )
    response.raise_for_status()
    data = response.json()
    box = data.get("answerBox") or {}
    return {
        "results": [
            {"title": p.get("title", ""), "url": p.get("link", ""), "snippet": p.get("snippet", "")}
            for p in (data.get("organic") or [])[:top_k]
        ],
        "answer": box.get("answer") or box.get("snippet") or None,
    }


async def _call_you(query: str, key: str, top_k: int) -> dict:
    async with httpx.AsyncClient(timeout=12.0) as http:
        response = await http.get(
            "https://api.you.com/v1/search",
            params={"query": query, "num_web_results": top_k},
            headers={"X-API-Key": key},
        )
    response.raise_for_status()
    data = response.json()
    return {
        "results": [
            {"title": p.get("title", ""), "url": p.get("url", ""), "snippet": p.get("snippet", "")}
            for p in (data.get("results") or [])[:top_k]
        ],
        "answer": data.get("answer"),
    }


async def _call_tavily(query: str, key: str, top_k: int) -> dict:
    async with httpx.AsyncClient(timeout=12.0) as http:
        response = await http.post(
            "https://api.tavily.com/search",
            json={"api_key": key, "query": query, "max_results": top_k},
        )
    response.raise_for_status()
    data = response.json()
    return {
        "results": [
            {"title": p.get("title", ""), "url": p.get("url", ""), "snippet": p.get("content", "")}
            for p in (data.get("results") or [])[:top_k]
        ],
        "answer": data.get("answer"),
    }


CALLERS = {
    "anspire": _call_anspire,
    "bocha": _call_bocha,
    "serper": _call_serper,
    "you": _call_you,
    "tavily": _call_tavily,
}


async def search(query: str, top_k: int = MAX_RESULTS, config: dict | None = None) -> dict:
    keys = _api_keys()
    order = (config or {}).get("providers") or PROVIDERS
    for provider in order:
        key = keys.get(provider, "")
        if not key:
            continue
        try:
            result = await CALLERS[provider](query, key, top_k)
            if result["results"]:
                return {"mode": "live", "provider": provider, "query": query, **result}
        except Exception as exc:
            logger.warning("tool search provider {} failed: {}", provider, exc)
    return _demo(query)
