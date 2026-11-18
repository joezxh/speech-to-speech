"""OpenAPI metadata shared by every route module in this package.

Everything the Swagger UI at ``/docs`` renders — title, tags, the WebSocket
entry (FastAPI cannot express WS routes natively) and the shared error schema —
lives here so the individual route modules only describe their own contract.
"""
from __future__ import annotations

from typing import Any

API_TITLE = "speech-to-speech Realtime API"
API_VERSION = "1.0.0"

API_DESCRIPTION = """
本服务把 **语音 → 转写 → 大模型 → 语音合成** 的全双工链路暴露为 HTTP / WebSocket 接口。

* 实时对话走 `WS /v1/realtime`（OpenAI Realtime 协议）或 `POST /v1/realtime/calls`（WebRTC SDP 握手）。
* 独立音频能力走 `/v1/audio/*`：转写、合成、情感、声纹、口型，均**复用同进程 pipeline 已加载的模型**，不额外占用端口。
* 观测端点 `/v1/pool`、`/v1/usage`、`/v1/realtime/capabilities` 用于排查与容量规划。

**通用约定**

* 所有音频接口均接受 `multipart/form-data`，音频字段名为 `file`；建议 16 kHz 单声道 PCM/WAV，服务端会自动重采样。
* 错误响应统一为 `{"error": {"code": "<机器码>", "reason": "<人读说明>"}}`（声纹接口为 `{"error":{"code","message"}}`）。
* 声纹接口要求 `Authorization: Bearer <token>`，其余接口无需鉴权（仅监听回环地址时使用）。
* 所有示例中的 `http://localhost:8765` 可替换为实际部署地址。
"""

# Tag definitions — the order here is the order of the groups in Swagger UI.
OPENAPI_TAGS: list[dict[str, Any]] = [
    {
        "name": "实时对话",
        "description": "全双工语音对话入口：WebSocket 实时协议与 WebRTC 通话。",
    },
    {
        "name": "音频能力",
        "description": "独立音频接口：转写(ASR)、合成(TTS)、情感(SER)、声纹(VP)、口型(STV)。",
    },
    {
        "name": "LLM 代理",
        "description": "OpenAI 兼容的对话补全接口，转发到上游 LLM 服务。",
    },
    {
        "name": "观测与运维",
        "description": "实例池状态、累计用量、能力探测与热配置推送。",
    },
]

# Shared error body used by most endpoints.
ERROR_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "error": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "机器可读错误码，如 `INVALID_AUDIO`、`SILENCE`、`LOW_CONFIDENCE`、`BUSY`。",
                    "example": "INVALID_AUDIO",
                },
                "reason": {
                    "type": "string",
                    "description": "人读错误说明。",
                    "example": "decode failed: invalid wav header",
                },
            },
            "required": ["code", "reason"],
        }
    },
}


def error_response(description: str, example_code: str = "INTERNAL_ERROR") -> dict[str, Any]:
    """Build a documented error response entry for ``responses=``."""
    schema = {
        "type": "object",
        "properties": {
            "error": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "example": example_code},
                    "reason": {"type": "string", "example": description},
                },
                "required": ["code", "reason"],
            }
        },
    }
    return {"description": description, "content": {"application/json": {"schema": schema}}}


def json_response(description: str, schema: dict[str, Any], example: Any = None) -> dict[str, Any]:
    """Build a documented JSON response entry for ``responses=``."""
    content: dict[str, Any] = {"application/json": {"schema": schema}}
    if example is not None:
        content["application/json"]["example"] = example
    return {"description": description, "content": content}


def text_response(description: str, example: str = "ok") -> dict[str, Any]:
    """Build a documented plain-text response entry (used by the SDP endpoint)."""
    return {"description": description, "content": {"text/plain": {"example": example}}}


def curl(method: str, url: str, *args: str) -> str:
    """Render a copy-pasteable curl example for a Swagger UI description."""
    parts = ["curl -X " + method, url]
    parts.extend(args)
    return " \\\n  ".join(parts)


# ── WebSocket route documentation ────────────────────────────────────────
# FastAPI has no native representation for WebSocket routes, so the WS entry is
# injected into the OpenAPI schema as a regular path with an `x-websocket`
# extension. It still renders (and can be expanded) in Swagger UI.
WS_PATH = "/v1/realtime"

WS_DESCRIPTION = """
**全双工语音对话（WebSocket）**。这是本服务的主入口。

连接建立后按 OpenAI Realtime 协议交互：

1. 客户端发送 `session.update` 配置会话（音频格式、语音、温度等）。
2. 客户端持续发送 `input_audio_buffer.append`（PCM16 16 kHz 单声道）。
3. 服务端 VAD（silero）检测语音结束并自动提交，生成回复；
   音频以 `response.audio.delta` 下发，结束时给出 `response.done`。
4. 客户端可发送 `conversation.item.truncate` 打断正在进行的回复。

服务端会额外下发扩展事件 `speech_to_speech.output_audio.visemes`
（口型时序，仅在启用 STV 时出现）与 `speech_to_speech.output_audio.visemes.capability`。

本实现**不要求**客户端发送 `input_audio_buffer.commit`——服务端 VAD 会自动提交；
重复提交只会得到 `conversation_already_has_active_response`（良性）。

### 调用范例

> `curl` **不支持 WebSocket 协议**（它只能发 HTTP 请求），因此本端点无法用 curl 直接调用。
> 请用下列任一 WebSocket 客户端；命令可直接复制执行。

```bash
# 方式一：websocat（纯命令行，最接近 curl 的体验）
websocat -H="Authorization: Bearer s2s-local" ws://localhost:8765/v1/realtime
```

```bash
# 方式二：用 curl 验证端点可达（升级握手，非 WebSocket 帧）
curl -i -N \\
  -H "Connection: Upgrade" \\
  -H "Upgrade: websocket" \\
  -H "Sec-WebSocket-Version: 13" \\
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \\
  -H "Authorization: Bearer s2s-local" \\
  http://localhost:8765/v1/realtime
# 期望：HTTP/1.1 101 Switching Protocols
```

```python
# 方式三：Python 客户端（发送 session.update 并接收首个事件）
import asyncio, json, websockets

async def main():
    async with websockets.connect(
        "ws://localhost:8765/v1/realtime",
        additional_headers={"Authorization": "Bearer s2s-local"},
    ) as ws:
        await ws.send(json.dumps({
            "type": "session.update",
            "session": {"modalities": ["text", "audio"], "voice": "Aiden"},
        }))
        print(await ws.recv())

asyncio.run(main())
```

> Python `websockets` 新版用 `additional_headers`；旧版（<11）用 `extra_headers`。
"""

WS_SCHEMA: dict[str, Any] = {
    "get": {
        "tags": ["实时对话"],
        "summary": "全双工语音对话（WebSocket）",
        "description": WS_DESCRIPTION,
        "operationId": "realtime_websocket",
        "x-websocket": True,
        "parameters": [
            {
                "name": "authorization",
                "in": "header",
                "required": False,
                "description": (
                    "可选 Bearer 令牌。部分部署要求握手时携带；控制台同源代理会自动注入短票据。"
                ),
                "schema": {"type": "string", "example": "Bearer s2s-local"},
            }
        ],
        "responses": {
            "101": {
                "description": "协议切换成功（Switching Protocols），此后为 JSON 文本帧。",
            },
            "403": {"description": "握手鉴权失败。"},
        },
    }
}

WS_CURL = """# WebSocket 需用专用客户端（浏览器/websocat/python），以下为等价命令：
websocat -H="Authorization: Bearer s2s-local" \\
  ws://localhost:8765/v1/realtime

# 或用 Python 一行流式发音频：
python -c "import asyncio,websockets,json; \\
async def m():\\n  async with websockets.connect('ws://localhost:8765/v1/realtime') as w: \\
    await w.send(json.dumps({'type':'session.update','session':{'modalities':['text','audio']}})); \\
    print(await w.recv())\\
asyncio.run(m())" """


def install_websocket_docs(app: Any) -> None:
    """Patch ``app.openapi`` so the WebSocket route shows up in Swagger UI."""
    original_openapi = app.openapi

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = original_openapi()
        paths = schema.setdefault("paths", {})
        if WS_PATH not in paths:
            paths[WS_PATH] = WS_SCHEMA
        schema["info"]["title"] = API_TITLE
        schema["info"]["version"] = API_VERSION
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi


__all__ = [
    "API_DESCRIPTION",
    "API_TITLE",
    "API_VERSION",
    "ERROR_RESPONSE_SCHEMA",
    "OPENAPI_TAGS",
    "WS_CURL",
    "WS_PATH",
    "curl",
    "error_response",
    "install_websocket_docs",
    "json_response",
    "text_response",
]
