"""远程 LLM 客户端受锁重建（TDD RED → GREEN）。"""

from __future__ import annotations

import threading
from types import SimpleNamespace

from speech_to_speech.LLM.base_openai_compatible_language_model import (
    BaseOpenAICompatibleHandler,
)


class _FakeReconfigurable:
    """只承载 reconfigure 依赖的字段；不加载真实 OpenAI 客户端。"""

    connection_kwargs = BaseOpenAICompatibleHandler.connection_kwargs
    reconfigure = BaseOpenAICompatibleHandler.reconfigure

    def __init__(self) -> None:
        self._reconfigure_lock = threading.RLock()
        self._connection_kwargs = {
            "model_name": "qwen-plus",
            "base_url": "https://example.com/v1",
            "api_key": "sk-old",
            "disable_thinking": True,
            "reasoning_effort": None,
            "stream": True,
        }
        self.client = SimpleNamespace(close=lambda: None)
        self._async_client = SimpleNamespace(close=lambda: None)
        self._async_runner = SimpleNamespace()
        self._extra_body = {"old": True}
        self.compactor = None

    def _build_extra_body(self, base_url, disable_thinking, reasoning_effort):
        return {"thinking": disable_thinking}

    def _build_compaction_generate_fn(self):
        return lambda *args, **kwargs: None

    def _make_sync_client(self, **kwargs):
        return SimpleNamespace(**kwargs)


def test_connection_kwargs_returns_a_copy():
    model = _FakeReconfigurable()
    kwargs = model.connection_kwargs()
    kwargs["api_key"] = "mutated"
    assert model.connection_kwargs()["api_key"] == "sk-old"


def test_reconfigure_replaces_client_and_clears_async_state():
    model = _FakeReconfigurable()
    old_client = model.client

    model.reconfigure()

    assert model.client is not old_client
    assert model._async_client is None
    assert model._async_runner is None
    assert model._extra_body != {"old": True}
