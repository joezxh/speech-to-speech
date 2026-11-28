"""本地调试用 webhook 回调接收器（模拟业务方消费端）。

用途：验证 callback 子系统的 python 目标投递链路（payload 形状、鉴权头、重试）。
不属于生产代码，仅本地/联调使用。

启动：
    python scripts/callback_receiver.py --port 9101 --token local-dev-callback-token

行为：
    POST /hook（或任意路径）：
      - 校验 `X-Callback-Token` 头（bearer 鉴权则校验 `Authorization: Bearer`）；
        不匹配返回 401，便于验证 dispatcher 的失败/重试路径
      - 2xx 响应 `{"ok": true}`；打印完整请求头与 JSON body（人工核对 payload 形状）
      - `--fail-first N`：前 N 次返回 500，验证指数退避重试与投递日志三态
    GET /health：探活，返回已收到的事件数
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("callback_receiver")

app = FastAPI()

SETTINGS: dict = {}
received: Counter = Counter()
attempt_no = 0


@app.post("/{path:path}")
async def hook(path: str, request: Request) -> JSONResponse:
    global attempt_no
    attempt_no += 1
    headers = {k: v for k, v in request.headers.items()}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = None

    event_type = "unknown"
    if isinstance(body, list) and body:
        event_type = f"java-array[{len(body)}]"
    elif isinstance(body, dict):
        event_type = str(body.get("eventType", "unknown"))

    # 鉴权头校验：header_token 模式看 X-Callback-Token；bearer 模式看 Authorization。
    token = headers.get("x-callback-token", "")
    bearer = headers.get("authorization", "")
    auth_ok = bool(
        (SETTINGS["token"] and token == SETTINGS["token"])
        or (SETTINGS["token"] and bearer == f"Bearer {SETTINGS['token']}")
    )

    logger.info(
        "#%d %s %s event=%s auth=%s headers=%s body=%s",
        attempt_no,
        request.method,
        request.url.path,
        event_type,
        "ok" if auth_ok else "MISMATCH",
        json.dumps(headers, ensure_ascii=False),
        json.dumps(body, ensure_ascii=False) if body is not None else "<non-json>",
    )

    if SETTINGS["fail_first"] and attempt_no <= SETTINGS["fail_first"]:
        return JSONResponse({"ok": False, "reason": "simulated failure"}, status_code=500)
    if not auth_ok:
        return JSONResponse({"ok": False, "reason": "token mismatch"}, status_code=401)

    received[event_type] += 1
    return JSONResponse({"ok": True, "event": event_type, "path": path})


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "received": dict(received), "attempts": attempt_no}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9101)
    parser.add_argument("--token", default="local-dev-callback-token", help="期望的回调令牌")
    parser.add_argument(
        "--fail-first", type=int, default=0, help="前 N 次请求返回 500（验证重试路径）"
    )
    args = parser.parse_args()
    SETTINGS.update(token=args.token, fail_first=args.fail_first)
    import uvicorn

    logger.info("receiver listening on http://%s:%d (token=%s)", args.host, args.port, args.token)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
