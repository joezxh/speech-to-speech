import { api } from './client'

export interface TokenSummary {
  window: string
  total: number
  input: number
  output: number
  per_minute: number
  quota: number | null
  water_pct: number | null
  cost_usd: number | null
  per_session: number | null
  per_session_turns: number | null
}

export interface TrendPoint {
  at: string
  input: number
  output: number
  total: number
}

/** 模型接口调用统计：按 kind 汇总行（GET /tokens/backends）。 */
export interface BackendKindRow {
  kind: string
  calls: number
  errors: number
  avg_ms: number | null
}

/** 按 engine+model 细分行。 */
export interface BackendModelRow {
  kind: string
  engine: string
  model: string
  calls: number
  errors: number
  avg_ms: number | null
}

/** 按机器分布行。 */
export interface BackendMachineRow {
  machine_id: string
  calls: number
  share_pct: number
}

/** 调用次数时间桶。 */
export interface BackendTrendPoint {
  at: string
  calls: number
}

export interface BackendStats {
  by_kind: BackendKindRow[]
  by_model: BackendModelRow[]
  by_machine: BackendMachineRow[]
  trend: BackendTrendPoint[]
}

/** 负载出口 7 列行（GET /tokens/egress，kind=engine/hosts/load/tokens/vram/route）。 */
export interface EgressRow {
  kind: string
  engine: string
  hosts: string[]
  load: string
  tokens: number
  vram_gb: number | null
  route: string
}

export const tokensApi = {
  summary: (window: string) => api.get<TokenSummary>(`/tokens/summary?window=${window}`),
  trend: (window: string, buckets = 30) => api.get<{ points: TrendPoint[] }>(`/tokens/trend?window=${window}&buckets=${buckets}`),
  distribution: (window: string) => api.get<{ machines: Array<{ machine_id: string; tokens: number; share_pct: number }> }>(`/tokens/distribution?window=${window}`),
  egress: (window: string) => api.get<{ rows: EgressRow[] }>(`/tokens/egress?window=${window}`),
  policy: () => api.get<{ items: Array<{ key: string; value: number | null; source: string; effective: boolean }> }>('/tokens/policy'),
  backends: (window: string, buckets = 30) => api.get<BackendStats>(`/tokens/backends?window=${window}&buckets=${buckets}`),
}
