<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import TokenTrendChart from '@/components/TokenTrendChart.vue'
import type { InstanceRow } from '@/types/api'
import { getInstances } from '@/api/instances'
import { useRoutingStore } from '@/stores/routing'
import { useTokensStore } from '@/stores/tokens'
import { DASH } from '@/utils/format'
import { egressRoute, splitBar } from './traffic.viewmodel'

const { t } = useI18n()
const tokens = useTokensStore()
const routing = useRoutingStore()
const windows = ['5m', '1h', '24h']
const instances = ref<InstanceRow[]>([])
const loadError = ref('')

const instanceColumns: Array<keyof InstanceRow> = [
  'instance_id', 'machine_id', 'base_url', 'status', 'weight', 'enabled',
  'drain_requested', 'size', 'in_use', 'free', 'probe_ms',
]
const bar = computed(() => splitBar(tokens.summary?.input ?? 0, tokens.summary?.output ?? 0))
const sticky = computed(() =>
  routing.stickyHitRate === null ? DASH : `${(routing.stickyHitRate * 100).toFixed(1)}%`,
)

async function load(): Promise<void> {
  await Promise.all([tokens.load(tokens.window), routing.load()])
  loadError.value = tokens.loadError || routing.loadError
  try {
    const payload = await getInstances('prod')
    instances.value = payload.instances ?? []
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : String(error)
  }
}

function setWindow(value: string): void {
  tokens.window = value
  void tokens.load(value)
}

onMounted(load)
</script>

<template>
  <section class="traffic-page">
    <header class="card">
      <h1>{{ t('traffic.cards.title') }}</h1>
      <div class="window-chips">
        <button v-for="w in windows" :key="w" class="chip" :class="{ active: tokens.window === w }" @click="setWindow(w)">{{ w }}</button>
      </div>
    </header>

    <div v-if="loadError" class="notice">{{ loadError }}</div>

    <!-- 卡 1：KPI×4 -->
    <div class="kpi-grid">
      <div class="kpi"><span>{{ t('traffic.cards.total') }}</span><strong>{{ tokens.summary?.total ?? DASH }}</strong></div>
      <div class="kpi"><span>{{ t('traffic.cards.perMinute') }}</span><strong>{{ tokens.summary?.per_minute ?? DASH }}</strong></div>
      <div class="kpi"><span>{{ t('traffic.cards.cost') }}</span><strong>{{ tokens.summary?.cost_usd ?? DASH }}</strong></div>
      <div class="kpi"><span>{{ t('traffic.cards.sticky') }}</span><strong>{{ sticky }}</strong></div>
    </div>

    <!-- 卡 2：Token 卡（四格 + split + 口径黄条） -->
    <div class="card">
      <h2>{{ t('traffic.cards.tokenCard') }}</h2>
      <div class="token-grid">
        <div>input: {{ tokens.summary?.input ?? DASH }}</div>
        <div>output: {{ tokens.summary?.output ?? DASH }}</div>
        <div>per session: {{ tokens.summary?.per_session ?? DASH }}</div>
        <div>turns/session: {{ tokens.summary?.per_session_turns ?? DASH }}</div>
      </div>
      <div class="split"><div class="split-a" :style="{ width: `${bar.aPct}%` }" /></div>
      <p class="notice">{{ t('traffic.cards.tokenNotice') }}</p>
    </div>

    <!-- 卡 3：策略卡（token 策略四项 + 生效徽标） -->
    <div class="card">
      <h2>{{ t('traffic.cards.policy') }} · LB {{ routing.mode || DASH }}</h2>
      <table class="tbl"><tbody>
        <tr v-for="item in tokens.policy" :key="item.key">
          <td>{{ item.key }}</td><td>{{ item.value ?? DASH }}</td>
          <td><span class="badge">{{ item.source }}</span></td>
          <td><span class="badge" :class="item.effective ? 'badge-ok' : ''">{{ item.effective ? t('common.effective') : t('common.default') }}</span></td>
        </tr>
      </tbody></table>
    </div>

    <!-- 卡 4：规则表 -->
    <div class="card">
      <h2>{{ t('traffic.cards.rules') }}</h2>
      <table class="tbl"><thead><tr>
        <th>priority</th><th>name</th><th>match</th><th>target</th><th>enabled</th>
      </tr></thead><tbody>
        <tr v-for="rule in routing.rules" :key="rule.id">
          <td>{{ rule.priority }}</td><td>{{ rule.name }}</td>
          <td>{{ rule.match_type }} {{ rule.match_value }}</td>
          <td>{{ rule.target_kind }} {{ rule.target_value }}</td>
          <td>{{ rule.enabled ? '✓' : '—' }}</td>
        </tr>
        <tr v-if="!routing.rules.length"><td colspan="5">{{ t('common.empty') }}</td></tr>
      </tbody></table>
    </div>

    <!-- 卡 5：趋势 SVG -->
    <div class="card">
      <h2>{{ t('traffic.cards.trend') }}</h2>
      <TokenTrendChart :points="tokens.trend" />
    </div>

    <!-- 卡 6：机器分布 -->
    <div class="card">
      <h2>{{ t('traffic.cards.distribution') }}</h2>
      <div v-for="row in tokens.distribution" :key="row.machine_id" class="dist-row">
        <span>{{ row.machine_id }}</span>
        <div class="bar"><div class="bar-fill" :style="{ width: `${row.share_pct}%` }" /></div>
        <span>{{ row.share_pct }}%</span>
      </div>
      <p v-if="!tokens.distribution.length" class="notice">{{ t('common.empty') }}</p>
    </div>

    <!-- 卡 7：负载出口 -->
    <div class="card">
      <h2>{{ t('traffic.cards.egress') }}</h2>
      <table class="tbl"><thead><tr><th>kind</th><th>route</th><th>tokens</th></tr></thead><tbody>
        <tr v-for="row in tokens.egress" :key="row.kind">
          <td>{{ row.kind }}</td><td><span class="badge">{{ egressRoute(row.kind) }}</span></td><td>{{ row.tokens }}</td>
        </tr>
      </tbody></table>
    </div>

    <!-- 实例表（11 列，列宽横滚） -->
    <div class="card">
      <h2>{{ t('traffic.cards.instances') }}</h2>
      <div class="table-scroll"><table class="tbl"><thead><tr>
        <th v-for="col in instanceColumns" :key="col">{{ col }}</th>
      </tr></thead><tbody>
        <tr v-for="inst in instances" :key="String(inst.instance_id)">
          <td v-for="col in instanceColumns" :key="col">{{ (inst as Record<string, unknown>)[col] ?? DASH }}</td>
        </tr>
      </tbody></table></div>
    </div>
  </section>
</template>

<style scoped lang="less">
.traffic-page { display: grid; gap: 16px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
h1, h2 { margin: 0 0 12px; }
.window-chips { display: flex; gap: 8px; margin-top: 8px; }
.chip { border: 1px solid var(--border); background: transparent; border-radius: 999px; padding: 4px 12px; cursor: pointer; }
.chip.active { background: var(--accent); color: #fff; }
.kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.kpi { display: flex; flex-direction: column; gap: 4px; padding: 12px; border: 1px solid var(--border); border-radius: 8px; }
.kpi strong { font-size: 24px; }
.token-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.split { margin-top: 12px; height: 8px; background: var(--border); border-radius: 4px; overflow: hidden; }
.split-a { height: 100%; background: var(--accent); }
.notice { color: var(--warn-text); background: var(--warn-soft); padding: 8px; border-radius: 4px; }
.badge { border: 1px solid var(--border); border-radius: 4px; padding: 2px 6px; font-size: 12px; }
.badge-ok { color: var(--ok-text); border-color: var(--ok-border); }
.tbl { width: 100%; border-collapse: collapse; }
.tbl th, .tbl td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); }
.table-scroll { overflow-x: auto; }
.dist-row { display: grid; grid-template-columns: 160px 1fr 56px; gap: 8px; align-items: center; margin: 6px 0; }
.bar { height: 8px; background: var(--border); border-radius: 4px; }
.bar-fill { height: 100%; background: var(--accent); border-radius: 4px; }
</style>
