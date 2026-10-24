from __future__ import annotations

import time
from collections import defaultdict, deque

import bcrypt

from app.config import auth as auth_settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


class LoginThrottle:
    """Per-IP failure window. In-process is enough: console runs one worker."""

    def __init__(self, max_attempts: int, window_s: int) -> None:
        self.max_attempts = max_attempts
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _trim(self, key: str, now: float) -> None:
        hits = self._hits[key]
        while hits and now - hits[0] > self.window_s:
            hits.popleft()

    def blocked(self, key: str) -> bool:
        now = time.monotonic()
        self._trim(key, now)
        return len(self._hits[key]) >= self.max_attempts

    def fail(self, key: str) -> None:
        self._hits[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)


throttle = LoginThrottle(auth_settings.login_max_attempts, auth_settings.login_window_seconds)
