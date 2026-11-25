"""会议音轨音量信号（SP-2 §5.1）。

把 VAD 切出的 int16 单声道 16k PCM 段换算为 RMS dBFS，作为一级门的输入之一。
纯函数、无第三方依赖，供 ``pytest`` 离线单测（worker.py 因依赖 livekit 不便导入）。

约定：空段与全静音返回 -96（下限），满幅方波返回 0，值域约 [-96, 0]。
audioLevel 为回调 payload 的可空字段。

（自 livekit-worker 原样移植，行为不变）
"""

from __future__ import annotations

import array
import math

SILENCE_DBFS = -96


def compute_audio_level_dbfs(pcm16_bytes: bytes) -> int:
    """int16 mono PCM → RMS dBFS（四舍五入取整数）。"""
    if not pcm16_bytes:
        return SILENCE_DBFS
    # 奇数长度无法组成 int16，截掉最后一个孤立字节而不是抛异常
    usable = pcm16_bytes[: len(pcm16_bytes) // 2 * 2]
    if not usable:
        return SILENCE_DBFS
    samples = array.array("h")
    samples.frombytes(usable)
    if not samples:
        return SILENCE_DBFS
    rms = math.sqrt(sum(x * x for x in samples) / len(samples))
    if rms <= 0:
        return SILENCE_DBFS
    level = 20 * math.log10(rms / 32768)
    return max(SILENCE_DBFS, min(0, round(level)))
