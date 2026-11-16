"""console REST 客户端（machine token 鉴权；register 例外走一次性注册码）。"""

from __future__ import annotations

import httpx


class AgentClient:
    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self, token: str | None = None) -> dict:
        return {"Authorization": f"Bearer {token}"} if token else {}

    def register(self, body: dict) -> dict:
        response = httpx.post(
            f"{self.base_url}/api/v1/agent/register", json=body, timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()["data"]

    def heartbeat(self, token: str, body: dict) -> dict:
        response = httpx.post(
            f"{self.base_url}/api/v1/agent/heartbeat",
            json=body,
            headers=self._headers(token),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()["data"]

    def pull_config(self, token: str, machine_id: str, if_none_match: str = "") -> tuple[int, dict | None]:
        headers = self._headers(token)
        if if_none_match:
            headers["If-None-Match"] = if_none_match
        response = httpx.get(
            f"{self.base_url}/api/v1/agent/config",
            params={"machine_id": machine_id},
            headers=headers,
            timeout=self.timeout,
        )
        if response.status_code == 304:
            return 304, None
        response.raise_for_status()
        return 200, response.json()["data"]

    def report(self, token: str, body: dict) -> dict:
        response = httpx.post(
            f"{self.base_url}/api/v1/agent/config/report",
            json=body,
            headers=self._headers(token),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()["data"]

    def ack(self, token: str, body: dict) -> dict:
        response = httpx.post(
            f"{self.base_url}/api/v1/agent/config/ack",
            json=body,
            headers=self._headers(token),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()["data"]
