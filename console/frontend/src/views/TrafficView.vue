<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import TokenTrendChart from '@/components/TokenTrendChart.vue'
import type { InstanceRow } from '@/types/api'
import { getInstances } from '@/api/instances'
import { getTrafficSettings } from '@/api/traffic'
import type { TrafficSettings } from '@/types/traffic'
import { useRoutingStore } from '@/stores/routing'
import { useTokensStore } from '@/stores/tokens'
import { DASH } from '@/utils/format'
import {
  barTone,
  egressRoute,
  formatMs,
  formatPct,
  formatRtf,
  loadBarPct,
  mergeInstanceStats,
  ratePerMinute,
  splitBar,
} from './traffic.viewmodel'

const { t } = useI18n()
const tokens = useTokensStore()
const routing = useRoutingStore()
const windows = ['5m', '1h', '24h']
const instances = ref<InstanceRow[]>([])
const settings = ref<TrafficSettings | null>(null)
const loadError = ref('')

const bar = computed(() => splitBar(tokens.summary?.input ?? 0, tokens.summary?.output ?? 0))
const sticky = computed(() =>
  routing.stickyHitRate === null ? DASH : `${(routing.stickyHitRate * 100).toFixed(1)}%`,
)
const activeSessions = computed(() =>
  instances.value.reduce((sum, inst) => sum + (inst.in_use ?? 0), 0),
)
const latency = computed(() => tokens.latencyStats)
const fastestMachine = computed(() => {
  const rows = [...(latency.value?.by_machine_ttft ?? [])]
    .filter((row) => row.p95_ttft_ms !== null)
    .sort((a, b) => (a.p95_ttft_ms ?? 0) - (b.p95_ttft_ms ?? 0))
  return rows[0]?.machine_id ?? DASH
})
const mergedInstances = computed(() => mergeInstanceStats(instances.value, latency.value?.instances ?? null))

// 路由规则卡：配置规则 join 路由决策记账（窗口 token/速率/份额）。
const ruleRows = computed(() => {
  const statById = new Map(routing.routeStatRules.map((row) => [row.rule_id, row]))
  return routing.rules.map((rule) => {
    const stat = statById.get(rule.id)
    const windowTokens = stat?.tokens ?? 0
    return {
      ...rule,
      matched: stat?.matched ?? 0,
      tokens: windowTokens,
      rate: ratePerMinute(windowTokens, 3600),
      share: stat?.share_pct ?? 0,
    }
  })
})

// 模型接口调用统计（新增能力）：四维数据全部来自 GET /tokens/backends。
const backendKindRows = computed(() => tokens.backends?.by_kind ?? [])
const backendModelRows = computed(() => tokens.backends?.by_model ?? [])
const backendMachineRows = computed(() => tokens.backends?.by_machine ?? [])
const backendTrend = computed(() =>
  (tokens.backends?.trend ?? []).map((point) => ({ at: point.at, input: 0, output: 0, total: point.calls })),
)
const backendTotalCalls = computed(() => backendKindRows.value.reduce((sum, row) => sum + row.calls, 0))
const hasBackendData = computed(() => backendKindRows.value.length > 0)

async function load(): Promise<void> {
  await Promise.all([tokens.load(tokens.window), routing.load()])
  loadError.value = tokens.loadError || routing.loadError
  try {
    const payload = await getInstances('prod')
    instances.value = payload.instances ?? []
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : String(error)
  }
  try {
    settings.value = await getTrafficSettings()
  } catch {
    settings.value = null
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
    <div v-if="loadError" class="note">{{ loadError }}</div>

    <!-- 块 1：KPI×4（P95 TTFT / 活跃会话 / 路由命中 / 错误率） -->
    <div class="grid g4">
      <div class="kpi">
        <div class="label">{{ t('traffic.kpi.p95ttft') }}</div>
        <div class="value">{{ formatMs(latency?.p95_ttft_ms ?? null) }}</div>
        <div class="sub">{{ t('traffic.kpi.p95ttftSub', { machine: fastestMachine }) }}</div>
      </div>
      <div class="kpi">
        <div class="label">{{ t('traffic.kpi.activeSessions') }}</div>
        <div class="value">{{ activeSessions }}</div>
        <div class="sub">{{ t('traffic.kpi.instancesSub', { n: instances.length }) }}</div>
      </div>
      <div class="kpi">
        <div class="label">{{ t('traffic.kpi.routeHit') }}</div>
        <div class="value">{{ sticky }}</div>
        <div class="sub">{{ t('traffic.kpi.stickySub', { ttl: settings?.grantTtlS ?? DASH }) }}</div>
      </div>
      <div class="kpi">
        <div class="label">{{ t('traffic.kpi.errRate') }}</div>
        <div class="value">{{ formatPct(latency?.err_rate ?? null) }}</div>
        <div class="sub">{{ t('traffic.kpi.topErrSub', { instance: latency?.top_err_instance?.instance_id ?? DASH }) }}</div>
      </div>
    </div>

    <!-- 块 2：Token 汇总卡（窗口 chips 收进卡头 + 4 KPI + split + 成本） -->
    <div class="card">
      <div class="rowline" style="justify-content: space-between; gap: 12px">
        <h2 class="card-title">{{ t('traffic.cards.tokenCard') }}</h2>
        <div class="chips" style="margin: 0">
          <button v-for="w in windows" :key="w" class="chip" :class="{ active: tokens.window === w }" @click="setWindow(w)">{{ w }}</button>
        </div>
      </div>
      <div class="grid g4" style="margin-top: 10px">
        <div class="kpi">
          <div class="label">{{ t('traffic.token.windowTotal', { win: tokens.window }) }}</div>
          <div class="value">{{ tokens.summary?.total ?? DASH }}</div>
        </div>
        <div class="kpi">
          <div class="label">{{ t('traffic.token.prompt') }}</div>
          <div class="value">{{ tokens.summary?.input ?? DASH }}</div>
          <div class="sub">{{ bar.aPct }}%</div>
        </div>
        <div class="kpi">
          <div class="label">{{ t('traffic.token.completion') }}</div>
          <div class="value">{{ tokens.summary?.output ?? DASH }}</div>
          <div class="sub">{{ (100 - bar.aPct).toFixed(1) }}%</div>
        </div>
        <div class="kpi">
          <div class="label">{{ t('traffic.token.rate') }}</div>
          <div class="value" :style="barTone(tokens.summary?.water_pct ?? null) === 'warn' ? 'color: var(--s2s-color-warning)' : ''">
            {{ tokens.summary?.per_minute ?? DASH }}
          </div>
          <div class="sub">{{ t('traffic.token.quotaSub', { pct: tokens.summary?.water_pct ?? DASH, quota: tokens.summary?.quota ?? DASH }) }}</div>
        </div>
      </div>
      <div style="margin-top: 14px">
        <div class="muted">{{ t('traffic.token.splitRatio') }}</div>
        <div class="split">
          <i class="p" :style="{ width: `${bar.aPct}%` }" />
          <i class="c" :style="{ width: `${(100 - bar.aPct).toFixed(1)}%` }" />
        </div>
        <div class="rowline" style="font-size: 11px; color: var(--s2s-color-faint)">
          <span>{{ t('traffic.token.promptLabel') }} {{ bar.aPct }}%</span>
          <span>{{ t('traffic.token.completionLabel') }} {{ (100 - bar.aPct).toFixed(1) }}%</span>
          <span>{{ t('traffic.token.costLine', { win: tokens.window, cost: tokens.summary?.cost_usd ?? DASH }) }}</span>
        </div>
      </div>
      <p class="note" style="margin-top: 12px">{{ t('traffic.cards.tokenNotice') }}</p>
    </div>

    <!-- 块 3+4：策略卡 / 规则卡 双列 -->
    <div class="grid g2">
      <div class="card">
        <h2 class="card-title">{{ t('traffic.cards.policy') }}</h2>
        <dl class="kv">
          <dt>{{ t('traffic.policyCard.scheduling') }}</dt><dd>{{ routing.mode || DASH }}</dd>
          <dt>{{ t('traffic.policyCard.stickyTtl') }}</dt><dd>{{ settings?.grantTtlS ?? DASH }} {{ t('traffic.policyCard.seconds') }}</dd>
          <dt>{{ t('traffic.policyCard.healthInterval') }}</dt><dd>{{ settings?.probeIntervalS ?? DASH }} {{ t('traffic.policyCard.seconds') }}</dd>
          <dt>{{ t('traffic.policyCard.evict') }}</dt><dd>{{ t('traffic.policyCard.failures', { n: settings?.failThreshold ?? DASH }) }}</dd>
          <dt>{{ t('traffic.policyCard.canary') }}</dt><dd>—</dd>
        </dl>
        <table class="tbl" style="margin-top: 12px"><tbody>
          <tr v-for="item in tokens.policy" :key="item.key">
            <td>{{ item.key }}</td><td>{{ item.value ?? DASH }}</td>
            <td><span class="tag">{{ item.source }}</span></td>
            <td><span class="tag" :class="item.effective ? 'ok' : ''">{{ item.effective ? t('traffic.common.effective') : t('traffic.common.default') }}</span></td>
          </tr>
        </tbody></table>
      </div>
      <div class="card">
        <h2 class="card-title">{{ t('traffic.cards.rules') }}</h2>
        <table class="tbl">
          <thead><tr>
            <th>{{ t('traffic.rules.colRule') }}</th>
            <th>{{ t('traffic.rules.colDest') }}</th>
            <th>{{ t('traffic.rules.colTokens') }}</th>
            <th>{{ t('traffic.rules.colRate') }}</th>
            <th>{{ t('traffic.rules.colShare') }}</th>
          </tr></thead>
          <tbody>
            <tr v-for="rule in ruleRows" :key="rule.id">
              <td>{{ rule.name }}</td>
              <td><span class="tag accent">{{ rule.target_kind }} {{ rule.target_value }}</span></td>
              <td>{{ rule.tokens || DASH }}</td>
              <td>{{ rule.rate ?? DASH }}</td>
              <td>{{ rule.matched ? `${rule.share}%` : DASH }}</td>
            </tr>
            <tr v-if="!routing.rules.length"><td colspan="5">{{ t('traffic.common.empty') }}</td></tr>
            <tr v-else-if="!ruleRows.some((rule) => rule.matched)"><td colspan="5">{{ t('traffic.rules.noMatched') }}</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 块 5：Token 趋势（峰值/当前标注） -->
    <div class="card">
      <h2 class="card-title">{{ t('traffic.cards.trend') }}</h2>
      <TokenTrendChart :points="tokens.trend" />
    </div>

    <!-- 块 6：Token 机器分布 -->
    <div class="card">
      <h2 class="card-title">{{ t('traffic.cards.distribution') }}</h2>
      <table class="tbl">
        <thead><tr>
          <th>{{ t('traffic.distribution.colMachine') }}</th>
          <th>{{ t('traffic.distribution.colTokens') }}</th>
          <th>{{ t('traffic.distribution.colShare') }}</th>
        </tr></thead>
        <tbody>
          <tr v-for="row in tokens.distribution" :key="row.machine_id">
            <td class="mono">{{ row.machine_id }}</td>
            <td class="mono">{{ row.tokens }}</td>
            <td style="min-width: 140px">
              <div class="bar"><i :style="{ width: `${row.share_pct}%` }" /></div>
              <small>{{ row.share_pct }}%</small>
            </td>
          </tr>
          <tr v-if="!tokens.distribution.length"><td colspan="3">{{ t('traffic.common.empty') }}</td></tr>
        </tbody>
      </table>
    </div>

    <!-- 块 7：负载出口（7 列） -->
    <div class="card">
      <h2 class="card-title">{{ t('traffic.cards.egress') }}</h2>
      <div class="tscroll"><table class="tbl">
        <thead><tr>
          <th>{{ t('traffic.egress.colKind') }}</th>
          <th>{{ t('traffic.egress.colEngine') }}</th>
          <th>{{ t('traffic.egress.colHosts') }}</th>
          <th>{{ t('traffic.egress.colLoad') }}</th>
          <th>{{ t('traffic.egress.colTokens') }}</th>
          <th>{{ t('traffic.egress.colVram') }}</th>
          <th>{{ t('traffic.egress.colRoute') }}</th>
        </tr></thead>
        <tbody>
          <tr v-for="row in tokens.egress" :key="row.kind">
            <td><span class="tag" :class="`wl-${row.kind}`">{{ row.kind }}</span></td>
            <td class="mono">{{ row.engine || DASH }}</td>
            <td class="mono">{{ row.hosts.length ? row.hosts.join(', ') : DASH }}</td>
            <td>{{ row.load || DASH }}</td>
            <td class="mono">{{ row.tokens || DASH }}</td>
            <td class="mono">{{ row.vram_gb !== null ? `${row.vram_gb} GB` : DASH }}</td>
            <td><span class="tag" :class="egressRoute(row.kind) === 'lb' ? 'accent' : ''">{{ t(egressRoute(row.kind) === 'lb' ? 'traffic.egress.routeLb' : 'traffic.egress.routeDirect') }}</span></td>
          </tr>
          <tr v-if="!tokens.egress.length"><td colspan="7">{{ t('traffic.common.empty') }}</td></tr>
        </tbody>
      </table></div>
    </div>

    <!-- 块 8：模型接口调用统计（新增能力） -->
    <div class="card">
      <div class="rowline" style="justify-content: space-between">
        <h2 class="card-title">{{ t('traffic.cards.backends') }}</h2>
        <small class="muted">{{ backendTotalCalls }}</small>
      </div>
      <div v-if="!hasBackendData" class="note">{{ t('traffic.backends.noData') }}</div>
      <template v-else>
        <h3 class="section-title">{{ t('traffic.backends.byKind') }}</h3>
        <table class="tbl">
          <thead><tr>
            <th>{{ t('traffic.backends.colKind') }}</th>
            <th>{{ t('traffic.backends.colCalls') }}</th>
            <th>{{ t('traffic.backends.colErrors') }}</th>
            <th>{{ t('traffic.backends.colAvgMs') }}</th>
          </tr></thead>
          <tbody>
            <tr v-for="row in backendKindRows" :key="row.kind">
              <td><span class="tag accent">{{ row.kind.toUpperCase() }}</span></td>
              <td class="mono">{{ row.calls }}</td>
              <td class="mono">{{ row.errors }}</td>
              <td class="mono">{{ formatMs(row.avg_ms) }}</td>
            </tr>
          </tbody>
        </table>

        <h3 class="section-title">{{ t('traffic.backends.byModel') }}</h3>
        <div class="tscroll"><table class="tbl">
          <thead><tr>
            <th>{{ t('traffic.backends.colKind') }}</th>
            <th>{{ t('traffic.backends.colEngine') }}</th>
            <th>{{ t('traffic.backends.colModel') }}</th>
            <th>{{ t('traffic.backends.colCalls') }}</th>
            <th>{{ t('traffic.backends.colErrors') }}</th>
            <th>{{ t('traffic.backends.colAvgMs') }}</th>
          </tr></thead>
          <tbody>
            <tr v-for="(row, index) in backendModelRows" :key="index">
              <td>{{ row.kind.toUpperCase() }}</td>
              <td class="mono">{{ row.engine || DASH }}</td>
              <td class="mono">{{ row.model || DASH }}</td>
              <td class="mono">{{ row.calls }}</td>
              <td class="mono">{{ row.errors }}</td>
              <td class="mono">{{ formatMs(row.avg_ms) }}</td>
            </tr>
          </tbody>
        </table></div>

        <h3 class="section-title">{{ t('traffic.backends.byMachine') }}</h3>
        <div v-for="row in backendMachineRows" :key="row.machine_id" class="dist-row">
          <span class="mono">{{ row.machine_id }}</span>
          <div class="bar"><i :style="{ width: `${row.share_pct}%` }" /></div>
          <span class="mono">{{ row.share_pct }}%</span>
        </div>

        <h3 class="section-title">{{ t('traffic.backends.trend') }}</h3>
        <TokenTrendChart :points="backendTrend" />
      </template>
    </div>

    <!-- 块 9：实例表（横滚 + TTFT/RTF/错误率合并列） -->
    <div class="card">
      <h2 class="card-title">{{ t('traffic.cards.instances') }}</h2>
      <div class="tscroll"><table class="tbl">
        <thead><tr>
          <th>{{ t('traffic.instances.colInstance') }}</th>
          <th>{{ t('traffic.instances.colMachine') }}</th>
          <th>{{ t('traffic.instances.colLoad') }}</th>
          <th>{{ t('traffic.instances.colRpm') }}</th>
          <th>{{ t('traffic.instances.colTtft') }}</th>
          <th>{{ t('traffic.instances.colRtf') }}</th>
          <th>{{ t('traffic.instances.colErr') }}</th>
          <th>{{ t('traffic.instances.colStatus') }}</th>
        </tr></thead>
        <tbody>
          <tr v-for="inst in mergedInstances" :key="inst.instance_id">
            <td class="mono">{{ inst.instance_id }}</td>
            <td class="mono">{{ inst.machine_id || DASH }}</td>
            <td style="min-width: 120px">
              <div class="bar"><i :style="{ width: loadBarPct(inst.in_use, inst.size) }" /></div>
              <small>{{ inst.in_use ?? DASH }} / {{ inst.size ?? DASH }}</small>
            </td>
            <td class="mono">{{ inst.rpm_5m ?? DASH }}</td>
            <td class="mono">{{ formatMs(inst.ttft_ms) }}</td>
            <td class="mono">{{ formatRtf(inst.rtf) }}</td>
            <td class="mono">{{ formatPct(inst.err_rate) }}</td>
            <td><span class="tag" :class="inst.status === 'online' ? 'ok' : ''">{{ inst.status }}</span></td>
          </tr>
          <tr v-if="!instances.length"><td colspan="8">{{ t('traffic.common.empty') }}</td></tr>
        </tbody>
      </table></div>
    </div>
  </section>
</template>

<style scoped lang="less">
.traffic-page { display: grid; gap: 16px; }
.card-title { margin: 0; font-size: 16px; }
.section-title { margin: 16px 0 8px; font-size: 13px; color: var(--s2s-color-muted); }
.muted { color: var(--s2s-color-muted); }
/* 原型 tkBar 口径：水位/占比 ≥85% 变警示色（值由视图模型 barTone 判定）。 */
.bar > i.warn { background: var(--s2s-color-warning); }
.dist-row {
  display: grid;
  grid-template-columns: 160px 1fr 56px;
  gap: 8px;
  align-items: center;
  margin: 6px 0;
}
</style>
