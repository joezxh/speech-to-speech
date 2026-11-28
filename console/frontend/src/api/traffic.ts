import { api } from './client'
import type { TrafficSettings } from '@/types/traffic'

/** 按机器的 TTFT/RTF 聚合行（GET /traffic/latency-stats）。 */
export interface MachineLatencyRow {
  machine_id: string
  turns: number
  avg_ttft_ms: number | null
  p95_ttft_ms: number | null
  rtf: number | null
}

/** 实例级统计行（与实例表按 instance_id 合并）。 */
export interface InstanceLatencyRow {
  instance_id: string
  ttft_ms: number | null
  rtf: number | null
  err_rate: number | null
}

export interface TopErrorInstance {
  instance_id: string
  errors: number
  err_rate: number | null
}

export interface LatencyStats {
  p95_ttft_ms: number | null
  by_machine_ttft: MachineLatencyRow[]
  err_rate: number | null
  top_err_instance: TopErrorInstance | null
  instances: InstanceLatencyRow[]
}

export const getTrafficSettings = (): Promise<TrafficSettings> =>
  api.get<TrafficSettings>('/traffic/settings')

export const getLatencyStats = (window: string): Promise<LatencyStats> =>
  api.get<LatencyStats>(`/traffic/latency-stats?window=${window}`)
