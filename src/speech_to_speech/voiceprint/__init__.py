"""声纹嵌入服务（Voiceprint Embedding Service）。

网关侧只做「一次音频 → 一次说话人向量」，不做注册/验证/底库/比对，
也不产出任何身份结论。契约见 docs/voiceprint-embedding-service-design-CN.md。
"""

from speech_to_speech.voiceprint.embedder import (
    SpeakerEmbedder,
    SpeakerEncoderUnavailable,
)
from speech_to_speech.voiceprint.errors import (
    ErrorStage,
    VoiceprintErrorCode,
    error_body,
    http_status,
)
from speech_to_speech.voiceprint.service import (
    VoiceprintRequestError,
    VoiceprintService,
)

__all__ = [
    "ErrorStage",
    "SpeakerEmbedder",
    "SpeakerEncoderUnavailable",
    "VoiceprintErrorCode",
    "VoiceprintRequestError",
    "VoiceprintService",
    "error_body",
    "http_status",
]
