"""阶段重建上下文：保存 pipeline 启动时各阶段的 BackendSelection 与 HandlerContext。

首期重载严格复用内存配置（不重解析 YAML），因此这些上下文在构造期一次性
保存到 PipelineUnit 上，供 ModelReloadCoordinator 原地重建 handler 使用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

STAGES = ("asr", "llm", "tts")


@dataclass
class StageContext:
    """重建单个阶段 handler 所需的最小输入集合。"""

    queue_in: Any
    queue_out: Any
    sample_rate: int
    pipeline_index: int
    queue_text_output: Any | None = None
    should_listen: Any | None = None
    cancel_scope: Any | None = None
    speculative_turns: Any | None = None
    extra: dict[str, Any] | None = None


@dataclass
class StageContextStore:
    """一个 unit 的三阶段选择 + 上下文快照。"""

    stt: Any
    llm: Any
    tts: Any
    vad_kwargs: Any | None = None
    module_kwargs: Any | None = None
    stt_context: StageContext | None = None
    llm_context: StageContext | None = None
    tts_context: StageContext | None = None

    def selections(self, stage: str) -> Any:
        key = {"asr": "stt", "llm": "llm", "tts": "tts"}.get(stage)
        if key is None:
            raise ValueError(f"unknown stage: {stage!r}")
        return getattr(self, key)

    def snapshot(self) -> dict[str, Any]:
        return {
            "modules": list(STAGES),
            "stages": {
                stage: {
                    "backend": getattr(self.selections(stage), "name", ""),
                }
                for stage in STAGES
            },
        }


__all__ = ["STAGES", "StageContext", "StageContextStore"]
