"""把 pool 装配为嵌入式 agent 的 reload provider。"""

from __future__ import annotations

from typing import Any, Callable

from speech_to_speech.api.openai_realtime.model_reload import ModelReloadCoordinator
from speech_to_speech.api.openai_realtime.model_reload_executor import ReloadExecutor
from speech_to_speech.stage_rebuild import StageRebuilder


def build_reload_provider(pool: list[Any]) -> tuple[Callable, ModelReloadCoordinator]:
    """构造 (submit, coordinator)；submit 可直接注入 EmbeddedAgent。"""
    rebuilder = StageRebuilder()
    executor = ReloadExecutor(pool, rebuild=rebuilder.rebuild)
    # 终态回执由 commands.execute 的 accepted 回执 + 进度回调负责；
    # 这里不重复 report_command，避免与命令行回执冲突。
    coordinator = ModelReloadCoordinator(executor)
    return coordinator.submit, coordinator
