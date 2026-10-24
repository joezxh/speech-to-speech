"""supervisor 的 XML-RPC 客户端，跑在 unix socket 上（§10.3）。

故意做得很窄：三个函数，三个调用的方法。console 能对容器内做的最坏的事
是重启 pipeline，而不是「以任意权限执行任意 supervisor 命令」。
"""

from __future__ import annotations

import http.client
import os
import socket
import xmlrpc.client
from typing import Any

from app.config import console

# supervisor 的 RPC 是同步的；给足 60s，与规格「单次重启超时 60s」对齐（§4.1）。
CALL_TIMEOUT = 60.0


class SupervisorError(RuntimeError):
    """socket 不可达或 supervisor 拒绝；调用方一律翻译成 502。"""


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._path)
        self.sock = sock


class _UnixTransport(xmlrpc.client.Transport):
    def __init__(self, path: str, timeout: float) -> None:
        super().__init__()
        self._path = path
        self._timeout = timeout

    def make_connection(self, host: str) -> _UnixHTTPConnection:
        return _UnixHTTPConnection(self._path, self._timeout)


def program() -> str:
    """重启目标从配置读，不从请求体读（§10.3）。"""
    return console.supervisor_program


def _proxy() -> xmlrpc.client.ServerProxy:
    path = console.supervisor_socket
    if not os.path.exists(path):
        raise SupervisorError(f"supervisor socket {path} does not exist")
    transport = _UnixTransport(path, CALL_TIMEOUT)
    # host 只用于 HTTP 头，真实连接走 unix socket。
    return xmlrpc.client.ServerProxy("http://localhost", transport=transport, allow_none=True)


def _call(method: str, *args: Any) -> Any:
    try:
        proxy = _proxy()
        return getattr(proxy.supervisor, method)(*args)
    except SupervisorError:
        raise
    except (xmlrpc.client.Fault, xmlrpc.client.ProtocolError) as exc:
        raise SupervisorError(f"supervisor refused {method}: {exc}") from exc
    except (OSError, http.client.HTTPException) as exc:
        raise SupervisorError(f"supervisor socket unusable: {exc}") from exc


def available() -> tuple[bool, str]:
    """`(usable, detail)`。socket 不在是正常状态，不是异常。"""
    try:
        info = _call("getState")
    except SupervisorError as exc:
        return False, str(exc)
    return True, str((info or {}).get("statename", "unknown"))


def state(name: str) -> dict[str, Any]:
    return dict(_call("getProcessInfo", name) or {})


def restart(name: str) -> None:
    """`stopProcess(wait=True)` 后 `startProcess`（§4.1 步骤 7）。

    两次 `_call` 各建一个 proxy: `stopProcess(wait=True)` 期间 XML-RPC 连接可能被
    supervisord 的重启流程关掉，复用同一个 proxy 会出现「stop 成功、start 抛
    `ProtocolError`」的假失败。
    """
    _call("stopProcess", name, True)
    _call("startProcess", name)
