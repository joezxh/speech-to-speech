"""声纹嵌入端点的机器可读错误码与 HTTP 映射。

设计依据（docs/voiceprint-embedding-service-design-CN.md §8.1）：
  · 错误体固定为 {"error": {code, message, stage, retryable}}
  · `code` 是穷举枚举，平台侧据此映射，**不解析 message**
  · 任何失败都不得返回 200，也不得返回全零/默认向量
"""

from __future__ import annotations

from enum import Enum


class ErrorStage(str, Enum):
    """失败阶段（供平台侧填 `failStage`）。"""

    AUTH = "AUTH"
    PREPROCESS = "PREPROCESS"
    INFER = "INFER"
    CAPACITY = "CAPACITY"
    INTERNAL = "INTERNAL"


class VoiceprintErrorCode(str, Enum):
    """网关侧错误码穷举枚举。"""

    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    AUTH_NOT_CONFIGURED = "AUTH_NOT_CONFIGURED"
    INVALID_REQUEST = "INVALID_REQUEST"
    MODEL_MISMATCH = "MODEL_MISMATCH"
    AUDIO_TOO_LARGE = "AUDIO_TOO_LARGE"
    AUDIO_TOO_LONG = "AUDIO_TOO_LONG"
    AUDIO_UNDECODABLE = "AUDIO_UNDECODABLE"
    AUDIO_SILENT = "AUDIO_SILENT"
    AUDIO_TOO_SHORT = "AUDIO_TOO_SHORT"
    SPEECH_NOT_DETECTED = "SPEECH_NOT_DETECTED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    QUEUE_FULL = "QUEUE_FULL"
    INFERENCE_TIMEOUT = "INFERENCE_TIMEOUT"
    INFERENCE_FAILED = "INFERENCE_FAILED"
    DIM_DRIFT = "DIM_DRIFT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


#: code → (HTTP 状态码, 固定文案, 失败阶段, 是否可重试)
#:
#: 文案一律固定，**不得**把底层异常原文（含路径/凭据片段）透出（设计 §8.2 约束 4）。
_ERROR_TABLE: dict[VoiceprintErrorCode, tuple[int, str, ErrorStage, bool]] = {
    VoiceprintErrorCode.UNAUTHORIZED: (401, "缺少或无效的 Bearer 凭据", ErrorStage.AUTH, False),
    VoiceprintErrorCode.FORBIDDEN: (403, "凭据不匹配", ErrorStage.AUTH, False),
    VoiceprintErrorCode.AUTH_NOT_CONFIGURED: (
        503,
        "服务端未配置声纹服务凭据，端点已按 fail-closed 关闭",
        ErrorStage.AUTH,
        False,
    ),
    VoiceprintErrorCode.INVALID_REQUEST: (400, "请求不合法：缺少音频文件", ErrorStage.PREPROCESS, False),
    VoiceprintErrorCode.MODEL_MISMATCH: (400, "请求的 model 与服务端配置不一致", ErrorStage.PREPROCESS, False),
    VoiceprintErrorCode.AUDIO_TOO_LARGE: (413, "音频超过大小上限", ErrorStage.PREPROCESS, False),
    VoiceprintErrorCode.AUDIO_TOO_LONG: (422, "音频超过时长上限", ErrorStage.PREPROCESS, False),
    VoiceprintErrorCode.AUDIO_UNDECODABLE: (422, "音频解码失败", ErrorStage.PREPROCESS, False),
    VoiceprintErrorCode.AUDIO_SILENT: (409, "音频为静音", ErrorStage.PREPROCESS, False),
    VoiceprintErrorCode.AUDIO_TOO_SHORT: (409, "有效语音过短", ErrorStage.PREPROCESS, False),
    VoiceprintErrorCode.SPEECH_NOT_DETECTED: (409, "未检测到有效语音", ErrorStage.PREPROCESS, False),
    VoiceprintErrorCode.MODEL_UNAVAILABLE: (503, "声纹模型不可用", ErrorStage.CAPACITY, True),
    VoiceprintErrorCode.QUEUE_FULL: (503, "声纹服务繁忙，请稍后重试", ErrorStage.CAPACITY, True),
    VoiceprintErrorCode.INFERENCE_TIMEOUT: (504, "声纹推理超时", ErrorStage.INFER, True),
    VoiceprintErrorCode.INFERENCE_FAILED: (500, "声纹推理失败", ErrorStage.INFER, True),
    VoiceprintErrorCode.DIM_DRIFT: (500, "声纹向量维度与实测值不一致", ErrorStage.INFER, False),
    VoiceprintErrorCode.INTERNAL_ERROR: (500, "声纹服务内部错误", ErrorStage.INTERNAL, True),
}


def http_status(code: VoiceprintErrorCode) -> int:
    return _ERROR_TABLE[code][0]


def error_body(code: VoiceprintErrorCode) -> dict[str, object]:
    """构造统一的错误响应体。"""
    _, message, stage, retryable = _ERROR_TABLE[code]
    return {
        "error": {
            "code": code.value,
            "message": message,
            "stage": stage.value,
            "retryable": retryable,
        }
    }


__all__ = [
    "ErrorStage",
    "VoiceprintErrorCode",
    "error_body",
    "http_status",
]
