/** 四套场景（与 docs/scenarios.yaml 同源；docs 侧由 validate_scenarios.py 校验）。 */

import type { Scene } from './deploy.viewmodel'

export const SCENES: Scene[] = [
  {
    name: 'latency',
    note: '最低首字延迟', why: '短帧与最小缓冲', gain: '更快的轮次切换',
    cost: 'CPU 略增', risk: '噪声环境可能误触发 VAD',
    patches: { 'vad.min_silence_ms': '300', 'tts.qwen3_tts_streaming_chunk_size': '2' },
  },
  {
    name: 'slow',
    note: '放慢语速', why: '给思考中的发言更长静默容忍', gain: '减少句中截断',
    cost: '响应变慢', risk: '体感迟钝',
    patches: { 'vad.min_silence_ms': '1200' },
  },
  {
    name: 'edge',
    note: '边缘设备资源档', why: '内存与显存受限', gain: '可在小机器上运行',
    cost: '并发下降', risk: '负载下音质下降',
    patches: { 'llm.responses_api_audio_max_tokens': '256' },
  },
  {
    name: 'mix',
    note: '混合流量均衡', why: '兼顾延迟与稳定', gain: 'p95 更可预测',
    cost: '单项指标不极致', risk: '需定期重调',
    patches: { 'vad.min_silence_ms': '700', 'llm.responses_api_audio_max_tokens': '512' },
  },
]
