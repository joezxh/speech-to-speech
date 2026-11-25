"""说话人分离（diarization）provider（V3.71）：混合段按说话人时间段的子段切片。

设计要点：
- ``DIARIZATION_BASE_URL`` 未配置 = 功能关闭（is_enabled() 为 False），worker 完全走
  V3.70 整段路径；配置后启用，任何失败（超时/5xx/坏包/空结果）一律抛
  ``DiarizationUnavailableException``，由 worker 回退整段路径，绝不丢转录。
- 音频只在进程内存停留，转 WAV 后请求期发送，不落盘、不进日志。
- 纯函数（parse/merge/slice/pick/to_epoch）可离线单测，Client 只做 IO。

服务契约（deploy/diarization/main.py）：
    POST {base}/v1/audio/diarization   (multipart: file, sample_rate=16000)
    200 -> {"segments": [{"speaker": 0, "startSec": 0.42, "endSec": 2.85}, ...]}
    200 -> {"segments": [], "reason": "NO_SPEECH"}   （有效语音过短）
    4xx/5xx -> 异常 -> worker 回退整段路径

移植来源：mediation-deploy/livekit-worker/diarization_provider.py 逐行移植；
DIARIZATION_BASE_URL 仍指向外部部署，源工程 deploy/diarization 服务不迁移。
"""
from __future__ import annotations

import io
import os
import time
import wave
from dataclasses import dataclass

import requests

DEFAULT_TIMEOUT_SEC = 30.0
DEFAULT_MIN_SUB_SEC = 0.8
DEFAULT_MAX_SUBSEGMENTS = 16
# 同 speaker 相邻窗间隔小于该值（秒）合并，避免 ASR 出超碎句
DEFAULT_MERGE_GAP_SEC = 0.2


class DiarizationUnavailableException(Exception):
    """diarization 服务不可用/返回不可解析，worker 回退整段路径。"""


@dataclass(frozen=True)
class SpeakerSegment:
    """一个说话人的一个连续时间段（秒，相对本段音频起点）。"""

    speaker: int
    start_sec: float
    end_sec: float

    @property
    def duration(self) -> float:
        return self.end_sec - self.start_sec


def is_enabled(base_url):
    """功能开关：未配置 DIARIZATION_BASE_URL 即关闭。"""
    return bool(base_url and str(base_url).strip())


def parse_diarization(payload):
    """服务响应 -> 规范化时间段列表（纯函数）。

    空 segments（NO_SPEECH）返回空表；非法/缺字段抛不可用异常。
    """
    if not isinstance(payload, dict):
        raise DiarizationUnavailableException("diarization payload not dict")
    raw = payload.get("segments")
    if raw is None:
        raise DiarizationUnavailableException("diarization payload missing segments")
    if not isinstance(raw, list):
        raise DiarizationUnavailableException("diarization segments not list")
    out = []
    for item in raw:
        if not isinstance(item, dict):
            raise DiarizationUnavailableException("diarization segment not dict")
        try:
            speaker = int(item["speaker"])
            start = float(item["startSec"])
            end = float(item["endSec"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DiarizationUnavailableException(f"bad segment fields: {exc}") from exc
        if end > start >= 0:
            out.append(SpeakerSegment(speaker, start, end))
    return out


def merge_adjacent(segments, gap_sec=DEFAULT_MERGE_GAP_SEC):
    """同 speaker 相邻窗（间隔 <= gap_sec）合并；跨 speaker 不合并（纯函数）。"""
    if not segments:
        return []
    ordered = sorted(segments, key=lambda s: (s.speaker, s.start_sec))
    merged = [ordered[0]]
    for seg in ordered[1:]:
        last = merged[-1]
        if seg.speaker == last.speaker and seg.start_sec - last.end_sec <= gap_sec:
            merged[-1] = SpeakerSegment(seg.speaker, last.start_sec,
                                        max(last.end_sec, seg.end_sec))
        else:
            merged.append(seg)
    return merged


def slice_by_speaker(pcm16_bytes, sample_rate, segments,
                     min_sub_sec=DEFAULT_MIN_SUB_SEC,
                     max_subsegments=DEFAULT_MAX_SUBSEGMENTS):
    """按说话人时间段切子段 PCM（纯函数）。

    返回 {speaker: [(pcm_bytes, startSec, endSec), ...]}（按 startSec 升序）；
    时长 < min_sub_sec 的子片段丢弃；子段总数超上限视为服务异常输出（抛不可用）。
    """
    total_sub = sum(1 for s in segments if s.duration >= min_sub_sec)
    if total_sub > max_subsegments:
        raise DiarizationUnavailableException(
            f"too many subsegments: {total_sub} > {max_subsegments}")
    bytes_per_sec = sample_rate * 2  # 16bit mono
    out = {}
    for seg in segments:
        if seg.duration < min_sub_sec:
            continue
        start_byte = int(seg.start_sec * bytes_per_sec)
        end_byte = min(len(pcm16_bytes), int(seg.end_sec * bytes_per_sec))
        if end_byte - start_byte < int(min_sub_sec * bytes_per_sec):
            continue
        out.setdefault(seg.speaker, []).append(
            (pcm16_bytes[start_byte:end_byte], seg.start_sec, seg.end_sec))
    return out


def pick_representative(subs):
    """取该 speaker 的最长子段作声纹代表（纯函数）；空表抛不可用。"""
    if not subs:
        raise DiarizationUnavailableException("no subsegment for representative")
    return max(subs, key=lambda t: t[2] - t[1])


def to_epoch_ms(started_ms, start_sec, end_sec):
    """段起点 epoch 毫秒 + 子段秒偏移 -> 子段 (startTs, endTs) epoch 毫秒（纯函数）。"""
    base = int(started_ms)
    return base + int(start_sec * 1000), base + int(end_sec * 1000)


def pcm_to_wav(pcm16_bytes, sample_rate):
    """PCM16 单声道 -> WAV 容器（纯函数；与 asr_provider._to_wav 同实现，避免环依赖）。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm16_bytes)
    return buf.getvalue()


class DiarizationClient:
    """diarization 服务客户端（只做 IO；失败一律抛 DiarizationUnavailableException）。"""

    def __init__(self, base_url, timeout_sec=DEFAULT_TIMEOUT_SEC,
                 min_sub_sec=DEFAULT_MIN_SUB_SEC,
                 max_subsegments=DEFAULT_MAX_SUBSEGMENTS):
        self.base = base_url.rstrip("/")
        self.timeout = timeout_sec
        self.min_sub_sec = min_sub_sec
        self.max_subsegments = max_subsegments

    def diarize(self, pcm16_bytes, sample_rate):
        """整段 PCM -> [{speaker, startSec, endSec}]（已按同 speaker 相邻窗合并、升序）。

        超时/5xx/网络异常/坏包统一抛 DiarizationUnavailableException。
        """
        wav = pcm_to_wav(pcm16_bytes, sample_rate)
        try:
            r = requests.post(
                f"{self.base}/v1/audio/diarization",
                files={"file": ("seg.wav", wav, "audio/wav")},
                data={"sample_rate": str(sample_rate)},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise DiarizationUnavailableException(f"request failed: {exc}") from exc
        if r.status_code >= 400:
            raise DiarizationUnavailableException(f"diarization http {r.status_code}")
        try:
            payload = r.json()
        except ValueError as exc:
            raise DiarizationUnavailableException("diarization body not json") from exc
        try:
            segments = parse_diarization(payload)
        except DiarizationUnavailableException:
            raise
        return merge_adjacent(segments)

    def slice(self, pcm16_bytes, sample_rate, segments):
        """按说话人切子段（Client 便捷入口，套用自身阈值配置）。"""
        return slice_by_speaker(pcm16_bytes, sample_rate, segments,
                                min_sub_sec=self.min_sub_sec,
                                max_subsegments=self.max_subsegments)


def get_client():
    """按环境变量构建 Client；DIARIZATION_BASE_URL 未配置返回 None（功能关闭）。"""
    base = os.environ.get("DIARIZATION_BASE_URL", "").strip()
    if not base:
        return None
    return DiarizationClient(
        base,
        timeout_sec=float(os.environ.get("DIARIZATION_TIMEOUT_SEC", str(DEFAULT_TIMEOUT_SEC))),
        min_sub_sec=float(os.environ.get("DIARIZATION_MIN_SUB_SEC", str(DEFAULT_MIN_SUB_SEC))),
        max_subsegments=int(os.environ.get("DIARIZATION_MAX_SUBSEGMENTS",
                                           str(DEFAULT_MAX_SUBSEGMENTS))),
    )


def monotonic_ms():
    """测试/日志辅助：当前 epoch 毫秒。"""
    return int(time.time() * 1000)
