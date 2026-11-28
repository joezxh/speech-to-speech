"""单阶段 handler 原地重建：复用内存配置，退役旧 handler 并重接外部引用。

首期（阶段 1）支持 ASR 与 TTS 的原地重建；handler 列表长度保持不变，
下游 handler 与发送循环不会收到 PIPELINE_END 级联停机。
"""

from __future__ import annotations

import threading
from queue import Queue
from typing import Any

from speech_to_speech.backend_registry import create_backend_handler
from speech_to_speech.stage_context import StageContextStore


def _handler_kind(handler: Any) -> str:
    name = type(handler).__name__
    if name.endswith("STTHandler"):
        return "stt"
    if name.endswith("TTSHandler"):
        return "tts"
    return ""


def build_stt_handlers(stt_handler: Any, context: Any) -> list[Any]:
    """STT 阶段 handler 链：handler + 可选转写通知（本函数保持链位数）。"""
    return [stt_handler]


class StageRebuilder:
    """按 stage 在 PipelineUnit 中就地替换 handler。"""

    def rebuild(self, unit: Any, stage: str) -> dict[str, Any]:
        if stage == "llm":
            return self._rebuild_llm(unit)
        if stage not in ("asr", "tts"):
            raise ValueError(f"unsupported rebuild stage: {stage!r}")
        store: StageContextStore | None = getattr(unit, "stage_context", None)
        if store is None:
            raise ValueError("unit has no stage context; cannot rebuild from memory config")

        selection = store.selections("asr" if stage == "asr" else "tts")
        target_kind = "stt" if stage == "asr" else "tts"
        handlers = list(unit.handlers)
        index = next(
            (i for i, h in enumerate(handlers) if _handler_kind(h) == target_kind),
            None,
        )
        if index is None:
            raise ValueError(f"no {target_kind} handler found in unit {getattr(unit, 'index', '?')}")

        old = handlers[index]
        retire = getattr(old, "retire", None)
        if retire is not None:
            retire()
        else:
            getattr(old, "stop_event", None) and old.stop_event.set()

        context = self._build_context(unit, store, target_kind)
        new_handler = create_backend_handler(selection, context)
        if stage == "asr":
            rebuilt = build_stt_handlers(new_handler, context)
        else:
            rebuilt = [new_handler]

        # 原位替换：保持列表长度与下游索引稳定；多余 handler 从原链继承。
        handlers[index : index + 1] = rebuilt[:1]
        unit.handlers = handlers

        self._rewire(unit, stage, old, new_handler)
        return {"stage": stage, "unitIndex": getattr(unit, "index", None), "replaced": True}

    def _rebuild_llm(self, unit: Any) -> dict[str, Any]:
        """远程 OpenAI 兼容后端受锁重建客户端；本地后端走 handler 重建。"""
        lm = next(
            (h for h in unit.handlers if type(h).__name__.endswith("LanguageModel")),
            None,
        )
        if lm is None:
            raise ValueError("no language model handler found")
        reconfigure = getattr(lm, "reconfigure", None)
        if callable(reconfigure):
            reconfigure()
            return {"stage": "llm", "mode": "client_reconfigure"}
        selection = getattr(getattr(unit, "stage_context", None), "llm", None)
        if selection is None:
            raise ValueError("no llm selection for handler rebuild")
        context = self._build_context(unit, unit.stage_context, "llm")
        new_handler = create_backend_handler(selection, context)
        index = next(i for i, h in enumerate(unit.handlers) if h is lm)
        old = unit.handlers[index]
        retire = getattr(old, "retire", None)
        if retire is not None:
            retire()
        unit.handlers[index] = new_handler
        return {"stage": "llm", "mode": "handler_rebuild"}

    def _build_context(self, unit: Any, store: StageContextStore, kind: str) -> Any:
        # 复用 unit 现有队列与 stop_event，构造与启动期一致的 HandlerContext。
        from speech_to_speech.backend_registry import HandlerContext

        if kind == "stt":
            queue_in = getattr(unit, "spoken_prompt_queue", None) or Queue()
            queue_out = getattr(unit, "stt_output_queue", None) or getattr(unit, "text_prompt_queue")
        else:
            queue_in = getattr(unit, "lm_processed_queue", None) or Queue()
            queue_out = getattr(unit, "output_queue")
        return HandlerContext(
            stop_event=getattr(unit, "stop_event", None) or threading.Event(),
            queue_in=queue_in,
            queue_out=queue_out,
            text_output_queue=getattr(unit, "text_output_queue", None),
            should_listen=getattr(unit, "should_listen", None),
            cancel_scope=getattr(unit, "cancel_scope", None),
            speculative_turns=getattr(unit, "speculative_turns", None),
            pipeline_index=getattr(unit, "index", 0),
            sample_rate=getattr(getattr(store, "vad_kwargs", None), "sample_rate", 16000),
            enable_live_transcription=getattr(
                getattr(store, "module_kwargs", None), "enable_live_transcription", False
            ),
            live_transcription_update_interval=getattr(
                getattr(store, "module_kwargs", None), "live_transcription_update_interval", 0.5
            ),
        )

    def _rewire(self, unit: Any, stage: str, old: Any, new_handler: Any) -> None:
        if stage == "asr":
            for handler in unit.handlers:
                if getattr(handler, "streaming_stt_sink", None) is old:
                    handler.streaming_stt_sink = new_handler
        # LiveKit / embedded SER 引用在注入协调器时由构造层统一 rewire。
