import { defineStore } from 'pinia'
import { ref } from 'vue'

import { lbApi, type LbRule } from '@/api/lb'

/** 路由决策记账：per-rule 匹配数/份额（GET /lb/route-stats 的 rules 明细）。 */
export interface RouteStatRule {
  rule_id: number | null
  matched: number
  tokens: number
  share_pct: number
}

export const useRoutingStore = defineStore('routing', () => {
  const mode = ref('')
  const policyItems = ref<Array<{ key: string; value: unknown; source: string }>>([])
  const rules = ref<LbRule[]>([])
  const stickyHitRate = ref<number | null>(null)
  const routeStatRules = ref<RouteStatRule[]>([])
  const loadError = ref('')

  async function load(): Promise<void> {
    try {
      const [policy, list, stats] = await Promise.all([lbApi.policy(), lbApi.rules(), lbApi.routeStats()])
      mode.value = policy.mode
      policyItems.value = policy.items
      rules.value = list.rules
      stickyHitRate.value = stats.sticky_hit_rate
      routeStatRules.value = stats.rules
      loadError.value = ''
    } catch (error) {
      loadError.value = error instanceof Error ? error.message : String(error)
    }
  }

  return { mode, policyItems, rules, stickyHitRate, routeStatRules, loadError, load }
})
