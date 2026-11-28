"""知识库工具：docs/**/*.md 的轻量全文检索（段落切块 + 标题加权）。"""

from __future__ import annotations

import re
from pathlib import Path

from app.config import tools

_CACHE: dict[Path, tuple[float, list[tuple[str, str, str]]]] = {}


def _chunks(path: Path) -> list[tuple[str, str, str]]:
    mtime = path.stat().st_mtime
    cached = _CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    text = path.read_text(encoding="utf-8", errors="ignore")
    heading = ""
    out: list[tuple[str, str, str]] = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        match = re.match(r"^#{1,6}\s+(.+)$", block, re.MULTILINE)
        if match:
            heading = match.group(1).strip()
        out.append((str(path), heading, block[:600]))
    _CACHE[path] = (mtime, out)
    return out


def kb_search(query: str, top_k: int = 5) -> dict:
    root = tools.docs_path
    terms = [term for term in re.split(r"\s+", query.strip()) if term]
    scored: list[dict] = []
    if root.exists():
        for path in root.rglob("*.md"):
            try:
                for file_path, heading, snippet in _chunks(path):
                    haystack = f"{heading} {snippet}".lower()
                    score = sum(haystack.count(term.lower()) for term in terms)
                    score += 2 if any(term.lower() in heading.lower() for term in terms) else 0
                    if score:
                        scored.append(
                            {"path": file_path, "heading": heading, "snippet": snippet, "score": score}
                        )
            except OSError:
                continue
    scored.sort(key=lambda row: row["score"], reverse=True)
    return {"mode": "local", "items": scored[:top_k]}
