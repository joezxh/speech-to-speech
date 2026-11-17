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

export const tokensApi = {
  summary: (window: string) => api.get<TokenSummary>(`/tokens/summary?window=${window}`),
  trend: (window: string, buckets = 30) => api.get<{ points: TrendPoint[] }>(`/tokens/trend?window=${window}&buckets=${buckets}`),
  distribution: (window: string) => api.get<{ machines: Array<{ machine_id: string; tokens: number; share_pct: number }> }>(`/tokens/distribution?window=${window}`),
  egress: (window: string) => api.get<{ rows: Array<{ kind: string; route: string; tokens: number }> }>(`/tokens/egress?window=${window}`),
  policy: () => api.get<{ items: Array<{ key: string; value: number | null; source: string; effective: boolean }> }>('/tokens/policy'),
}
