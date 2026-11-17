import { api } from './client'

export interface LbRule {
  id: number
  name: string
  priority: number
  match_type: string
  match_value: string
  target_kind: string
  target_value: string
  enabled: boolean
}

export const lbApi = {
  policy: () => api.get<{ mode: string; items: Array<{ key: string; value: unknown; source: string }> }>('/lb/policy'),
  rules: () => api.get<{ rules: LbRule[] }>('/lb/rules'),
  routeStats: (windowS = 3600) => api.get<{ rules: Array<{ rule_id: number | null; matched: number; tokens: number; share_pct: number }>; sticky_hit_rate: number | null }>(`/lb/route-stats?window_s=${windowS}`),
}
