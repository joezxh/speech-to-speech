"""转录分段近重复抑制（V3.68 联调修复）。

同一参会人重发音轨时，多个 VAD 任务可能产生内容相近的重复分段
（例：「之前没一次性写出来。」/「之前没一次性写出来了。」），
前端精确去重无法覆盖这种「多一个尾巴」的变体。

策略（纯函数 + 有状态守卫）：
- 归一化：去标点/空白，仅比较有效中文/数字/字母；
- 近重复：短文本完全相等，或较长文本包含较短文本（两者长度均 >= MIN_LEN）；
- 时间窗：同一 identity 在 WINDOW_MS 内只保留首条；
- 超过窗口或有效长度过短（如「嗯」「对」）一律放行。

（自 livekit-worker 原样移植，行为不变）
"""
from __future__ import annotations

import re
import time
from collections import defaultdict, deque

MIN_LEN = 4
WINDOW_MS = 4000
MAX_HISTORY = 12

_PUNCT = re.compile(r"[\s，。！？；：,.!?;:、~…\-—\"'（）()\[\]【】]+")


def normalize_text(text: str) -> str:
    return _PUNCT.sub("", text or "")


def is_near_duplicate(a: str, b: str) -> bool:
    """两条归一化文本是否近似重复（纯函数）"""
    if len(a) < MIN_LEN or len(b) < MIN_LEN:
        return False
    if a == b:
        return True
    if len(a) >= len(b):
        return b in a
    return a in b


class DuplicateGuard:
    """按 identity 维护最近分段，判定是否应丢弃近重复段落。"""

    def __init__(self, window_ms: int = WINDOW_MS) -> None:
        self.window_ms = window_ms
        self._history: dict[str, deque[tuple[str, int]]] = defaultdict(deque)

    def should_skip(self, identity: str, text: str, ts_ms: int | None = None) -> bool:
        norm = normalize_text(text)
        if len(norm) < MIN_LEN:
            return False
        ts = int(ts_ms if ts_ms is not None else time.time() * 1000)
        hist = self._history[identity]
        while hist and ts - hist[0][1] > self.window_ms:
            hist.popleft()
        if any(is_near_duplicate(norm, old) for old, _ in hist):
            return True
        hist.append((norm, ts))
        while len(hist) > MAX_HISTORY:
            hist.popleft()
        return False
