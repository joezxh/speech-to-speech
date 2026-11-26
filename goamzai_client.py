#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
聚合AI (https://ai.ldxc.xyz) 非官方客户端演示

该站由 GoAmzAI(Pro-Version) 搭建，前端为 Vue SPA，后端接口前缀 /api。
程序调用流程：
  1. POST /api/user/login          账号密码登录，返回 token（纯字符串，无 Bearer 前缀）
  2. GET  /api/chat/tmpl           获取模型列表与站点配置
  3. POST /api/chat/session        创建会话（需指定 model）
  4. POST /api/chat/completions    发送消息，SSE 流式返回

SSE 事件格式（每行 data: 后跟 JSON）：
  {"code":0,"data":"文本增量"}                  -> 文本片段，累加
  {"code":0,"data":{...}}                       -> 结构化字段更新（如联网搜索状态）
  {"code":1,"err":"错误信息"}                    -> 出错并结束
  data: [DONE]                                  -> 结束标记

用法：
  python goamzai_client.py --account <手机号/邮箱> --password <密码>
  python goamzai_client.py --account <账号> --password <密码> --text "你好，介绍一下你自己"
"""

import argparse
import json
import sys

import requests

BASE = "https://ai.ldxc.xyz/api"
APP_VERSION = "1.0.0"  # 前端会在 X-APP-VERSION 头带上版本号


def _find_token(obj):
    """登录返回结构中递归查找 token 字段。"""
    if isinstance(obj, str) and len(obj) > 16:
        return obj
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "token" and isinstance(v, str) and v:
                return v
            found = _find_token(v)
            if found:
                return found
    return None


class GoAmzAIClient:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36",
            "X-APP-VERSION": APP_VERSION,
            "X-Locale": "zh-CN",
            "Origin": "https://ai.ldxc.xyz",
            "Referer": "https://ai.ldxc.xyz/",
        })
        self.token = None

    # ---------- 1. 登录 ----------
    def login(self, account: str, password: str) -> str:
        r = self.s.post(
            f"{BASE}/user/login",
            json={
                "account": account,
                "password": password,
                "code": "",                # 短信/邮箱验证码登录时使用
                "registrationCode": "",
                "captcha": "",
                "captchaId": "",
                "invite": "",
                "agreement": True,
            },
            timeout=30,
        )
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(f"登录失败: HTTP {r.status_code}, {data.get('msg')}")
        self.token = _find_token(data.get("data"))
        if not self.token:
            raise RuntimeError(f"未在登录响应中找到 token，原始响应: {json.dumps(data)[:500]}")
        # 注意：GoAmzAI 使用裸 token，不加 "Bearer " 前缀
        self.s.headers["Authorization"] = self.token
        return self.token

    def _check(self, data):
        if data.get("code") != 0:
            raise RuntimeError(f"接口返回错误: {data.get('msg') or data.get('err')}")
        return data.get("data")

    # ---------- 2. 模型列表 ----------
    def models(self) -> list:
        r = self.s.get(f"{BASE}/chat/tmpl", timeout=30)
        tmpl = self._check(r.json())
        models = (tmpl or {}).get("models") or []
        return [{"value": m.get("value"), "label": m.get("label")} for m in models]

    # ---------- 3. 创建会话 ----------
    def create_session(self, model: str) -> dict:
        r = self.s.post(
            f"{BASE}/chat/session",
            json={
                "model": model,
                "plugins": [],
                "mcp": [],
                "webSearch": False,
                "nativeTools": [],
                "nativeToolOptions": {},
                "reasoningEffort": "",
            },
            timeout=30,
        )
        return self._check(r.json())

    # ---------- 4. 发送消息（SSE 流式） ----------
    def chat(self, text: str, session_id, thinking: bool = False,
             web_search: bool = False, system_prompt: str = None):
        payload = {
            "text": text,
            "sessionId": session_id,
            "files": [],
            "thinking": thinking,
            "webSearch": web_search,
            "nativeTools": [],
            "nativeToolOptions": {},
            "reasoningEffort": "",
        }
        if system_prompt:
            payload["systemPrompt"] = system_prompt

        full_text = ""
        with self.s.post(
            f"{BASE}/chat/completions",
            json=payload,
            headers={"Accept": "text/event-stream"},
            stream=True,
            timeout=(30, 300),
        ) as r:
            ct = r.headers.get("Content-Type", "")
            if not ct.startswith("text/event-stream"):
                body = r.json()
                if body.get("code") == 2:
                    raise RuntimeError("未登录或 token 失效，请重新登录")
                raise RuntimeError(f"响应异常: HTTP {r.status_code}, {ct}, {body}")

            task_id = r.headers.get("X-Chat-Task-Id")
            if task_id:
                print(f"[task-id] {task_id}")

            for raw in r.iter_lines(decode_unicode=True):
                if not raw or not raw.startswith("data:"):
                    continue
                data = raw[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if obj.get("code") != 0:
                    raise RuntimeError(f"模型输出错误: {obj.get('err') or obj}")
                d = obj.get("data")
                if isinstance(d, str) and d:
                    full_text += d
                    print(d, end="", flush=True)
                elif isinstance(d, dict):
                    # 结构化更新（如联网搜索进度），按需处理
                    pass
        print()
        return full_text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True, help="手机号或邮箱")
    ap.add_argument("--password", required=True)
    ap.add_argument("--text", default="你好，请用一句话介绍你自己")
    ap.add_argument("--model", default=None, help="模型ID，不填则列出可用模型后用第一个")
    args = ap.parse_args()

    c = GoAmzAIClient()
    c.login(args.account, args.password)
    print("[ok] 登录成功")

    models = c.models()
    print(f"[ok] 可用模型 {len(models)} 个，示例: {[m['value'] for m in models[:8]]}")

    model = args.model or (models[0]["value"] if models else None)
    if not model:
        sys.exit("未获取到可用模型")

    session = c.create_session(model)
    sid = session.get("id")
    print(f"[ok] 会话已创建: id={sid}, model={model}")

    c.chat(args.text, sid)


if __name__ == "__main__":
    main()
