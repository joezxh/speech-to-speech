import { defineStore } from 'pinia'
import { ref } from 'vue'

import { getLatencyStats, type LatencyStats } from '@/api/traffic'
import { tokensApi, type BackendStats, type EgressRow, type TokenSummary, type TrendPoint } from '@/api/tokens'

export const useTokensStore = defineStore('tokens', () => {
  const window = ref('5m')
  const summary = ref<TokenSummary | null>(null)
  const trend = ref<TrendPoint[]>([])
  const distribution = ref<Array<{ machine_id: string; tokens: number; share_pct: number }>>([])
  const egress = ref<EgressRow[]>([])
  const policy = ref<Array<{ key: string; value: number | null; source: string; effective: boolean }>>([])
  const backends = ref<BackendStats | null>(null)
  const latencyStats = ref<LatencyStats | null>(null)
  const loadError = ref('')

  async function load(nextWindow = window.value): Promise<void> {
    window.value = nextWindow
    try {
      const [s, tr, dist, eg, pol, be, lat] = await Promise.all([
        tokensApi.summary(nextWindow),
        tokensApi.trend(nextWindow),
        tokensApi.distribution(nextWindow),
        tokensApi.egress(nextWindow),
        tokensApi.policy(),
        tokensApi.backends(nextWindow),
        getLatencyStats(nextWindow),
      ])
      summary.value = s
      trend.value = tr.points
      distribution.value = dist.machines
      egress.value = eg.rows
      policy.value = pol.items
      backends.value = be
      latencyStats.value = lat
      loadError.value = ''
    } catch (error) {
      loadError.value = error instanceof Error ? error.message : String(error)
    }
  }

  return { window, summary, trend, distribution, egress, policy, backends, latencyStats, loadError, load }
})
