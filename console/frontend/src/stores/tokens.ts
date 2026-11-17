import { defineStore } from 'pinia'
import { ref } from 'vue'

import { tokensApi, type TokenSummary, type TrendPoint } from '@/api/tokens'

export const useTokensStore = defineStore('tokens', () => {
  const window = ref('5m')
  const summary = ref<TokenSummary | null>(null)
  const trend = ref<TrendPoint[]>([])
  const distribution = ref<Array<{ machine_id: string; tokens: number; share_pct: number }>>([])
  const egress = ref<Array<{ kind: string; route: string; tokens: number }>>([])
  const policy = ref<Array<{ key: string; value: number | null; source: string; effective: boolean }>>([])
  const loadError = ref('')

  async function load(nextWindow = window.value): Promise<void> {
    window.value = nextWindow
    try {
      const [s, tr, dist, eg, pol] = await Promise.all([
        tokensApi.summary(nextWindow),
        tokensApi.trend(nextWindow),
        tokensApi.distribution(nextWindow),
        tokensApi.egress(nextWindow),
        tokensApi.policy(),
      ])
      summary.value = s
      trend.value = tr.points
      distribution.value = dist.machines
      egress.value = eg.rows
      policy.value = pol.items
      loadError.value = ''
    } catch (error) {
      loadError.value = error instanceof Error ? error.message : String(error)
    }
  }

  return { window, summary, trend, distribution, egress, policy, loadError, load }
})
