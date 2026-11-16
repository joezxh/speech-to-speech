"""s2s-agent 常驻进程（pipeline 仓，spec 2026-11-17 §5）。

形态：`python -m speech_to_speech.agent`，随 pipeline 镜像构建并由 supervisor 拉起。
两种部署形态（pipeline-node / workload-node）同一份代码，差别只在 agent.yaml 声明。
"""

from speech_to_speech.agent.runner import main

__all__ = ["main"]
