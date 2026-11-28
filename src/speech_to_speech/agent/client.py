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

    def pull_commands(self, token: str, limit: int = 10) -> list[dict]:
        """拉取本机命令；领到即被 console 标记 dispatched。"""
        response = httpx.get(
            f"{self.base_url}/api/v1/agent/commands",
            params={"limit": limit},
            headers=self._headers(token),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()["data"]

    def report_command(
        self, token: str, command_id: str, *, ok: bool, result: dict, error: str = ""
    ) -> dict:
        response = httpx.post(
            f"{self.base_url}/api/v1/agent/commands/{command_id}/report",
            json={"ok": ok, "result": result, "error": error},
            headers=self._headers(token),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()["data"]

    def set_instance_drain(self, token: str, drain: bool) -> dict:
        """排空/恢复本机绑定的 pipeline 实例（console DB + 内存注册表同步）。"""
        response = httpx.post(
            f"{self.base_url}/api/v1/agent/instances/drain",
            json={"drain": drain},
            headers=self._headers(token),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()["data"]

    def upload_logs(self, token: str, logs: list[dict]) -> dict:
        """上报容器日志（已脱敏、有界）；console 复用现有四日志格式落盘。"""
        response = httpx.post(
            f"{self.base_url}/api/v1/agent/logs",
            json={"logs": logs},
            headers=self._headers(token),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()["data"]

    def report_turn_latency(self, token: str, rows: list[dict]) -> dict:
        """A5：逐轮 TURN_LATENCY 行上报（response_key+turn_revision 幂等去重）。"""
        response = httpx.post(
            f"{self.base_url}/api/v1/agent/turn-latency",
            json={"rows": rows},
            headers=self._headers(token),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()["data"]

    def probe_instances(self, token: str) -> dict:
        response = httpx.post(
            f"{self.base_url}/api/v1/agent/instances/probe",
            headers=self._headers(token),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()["data"]
