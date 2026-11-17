<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import LogAnalysisCard from '@/components/LogAnalysisCard.vue'
import LogPanel from '@/components/LogPanel.vue'
import PDot from '@/components/proto/PDot.vue'
import ScenarioAdvisor from '@/components/proto/ScenarioAdvisor.vue'
import { machineConfigApi, type MachineParamRow } from '@/api/machineConfig'
import { useLogsStore } from '@/stores/logs'
import { useMachineStore as useMachinesStore } from '@/stores/machine'
import { DASH } from '@/utils/format'
import { SCENES } from './scenes'
import {
  deployDetailRows,
  deployKpis,
  deployStack,
  groupChips,
  groupRows,
  rowTone,
  type ParamRow
} from './deploy.viewmodel'

const { t } = useI18n()
const route = useRoute()
const machinesStore = useMachinesStore()
const logsStore = useLogsStore()
const selectedMachine = ref(String(route.query.machine ?? ''))
const paramSource = ref<'runtime' | 'declared'>('runtime')
const rows = ref<MachineParamRow[]>([])
const driftCount = ref(0)
const patch = ref<Record<string, string>>({})
const draftVersion = ref(0)
const confirmWord = ref('')
const notice = ref('')
const scenes = SCENES
const selectedScene = ref('')
const group = ref('ALL')

const machine = computed(() =>
  machinesStore.machines.find((m) => m.machineId === selectedMachine.value) ?? null
)
const grouped = computed(() => {
  const map = new Map<string, ParamRow[]>()
  for (const row of rows.value) {
    const stage = row.key.split('.')[0] || 'other'
    if (!map.has(stage)) map.set(stage, [])
    map.get(stage)!.push(row)
  }
  return [...map.entries()]
})
const actual = computed(() => Object.fromEntries(rows.value.map((r) => [r.key, r.actual ?? ''])))
const kpis = computed(() => deployKpis(rows.value, driftCount.value, selectedScene.value))
const chips = computed(() => groupChips(rows.value))
const stack = computed(() => deployStack(rows.value))
const visibleRows = computed(() => groupRows(rows.value, group.value))
const detailRows = computed(() => deployDetailRows({
  machineId: machine.value?.machineId ?? '',
  addr: machine.value?.addr ?? '',
  state: machine.value?.state ?? '',
  version: machine.value?.version ?? null,
  deployedAt: machine.value?.deployedAt ?? null,
  configSource: machine.value?.configSource ?? null,
  gpu: machine.value?.gpu ?? null,
  gpuUtilPct: machine.value?.gpuUtilPct ?? null,
  lastPushAt: machine.value?.lastPushAt ?? null,
  lastPushBy: machine.value?.lastPushBy ?? ''
}))
const nodeMetrics = computed(() => [
  { label: t('deploy.node.cpu'), value: machine.value?.cpuPct == null ? DASH : `${machine.value.cpuPct}%` },
  { label: t('deploy.node.load'), value: machine.value?.loadAvg?.length ? machine.value.loadAvg.join(' / ') : DASH },
  { label: t('deploy.node.mem'), value: machine.value?.memUsedGb == null ? DASH : `${machine.value.memUsedGb} / ${machine.value.memTotalGb ?? DASH} GB (${machine.value.memPct ?? DASH}%)` },
  { label: t('deploy.node.gpuMem'), value: machine.value?.gpuMemUsedGb == null ? DASH : `${machine.value.gpuMemUsedGb} / ${machine.value.gpuMemTotalGb ?? DASH} GB` },
  { label: t('deploy.node.pipelineVram'), value: machine.value?.pipelineVramGb == null ? DASH : `${machine.value.pipelineVramGb} GB` },
  { label: t('deploy.node.collectedAt'), value: machine.value?.collectedAt ?? DASH }
])
const deploymentEntries = computed(() =>
  Object.entries(machine.value?.deployment?.[paramSource.value] ?? {}).map(([key, value]) => ({
    key,
    value: typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value)
  }))
)

async function load(): Promise<void> {
  await machinesStore.fetch()
  if (!selectedMachine.value && machinesStore.machines.length) {
    selectedMachine.value = machinesStore.machines[0].machineId
  }
  if (!selectedMachine.value) return
  logsStore.filters.process = ['pipeline']
  logsStore.filters.q = selectedMachine.value
  void logsStore.reload()
  const [view, drift, draft] = await Promise.all([
    machineConfigApi.view(selectedMachine.value),
    machineConfigApi.drift(selectedMachine.value),
    machineConfigApi.draft(selectedMachine.value),
  ])
  rows.value = view.rows
  driftCount.value = drift.drift_count
  patch.value = draft.values
  draftVersion.value = draft.version
}

watch(
  () => route.query.machine,
  (value) => {
    if (!value) return
    selectedMachine.value = String(value)
    void load()
  }
)

async function saveDraft(): Promise<void> {
  if (!selectedMachine.value) return
  await machineConfigApi.putDraft(selectedMachine.value, patch.value, draftVersion.value)
  notice.value = t('deploy.noticeSaved', { version: draftVersion.value + 1 })
  await load()
}

async function deploy(mode: 'push' | 'rollback'): Promise<void> {
  if (!selectedMachine.value) return
  await machineConfigApi.deploy(selectedMachine.value, mode, confirmWord.value)
  notice.value = mode === 'push' ? t('deploy.noticePublished') : t('deploy.noticeRollback')
  confirmWord.value = ''
}

function applyScene(name: string): void {
  selectedScene.value = name
  const scene = scenes.find((s) => s.name === name)
  if (scene) {
    for (const [key, value] of Object.entries(scene.patches)) patch.value[key] = value
  }
}

onMounted(load)
</script>

<template>
  <section class="deploy-page">
    <header class="card">
      <h1>{{ t('deploy.pageTitle') }}</h1>
      <p class="hint">{{ t('deploy.pageDesc') }}</p>
      <div class="machine-chips">
        <button
          v-for="item in machinesStore.machines"
          :key="item.machineId"
          class="chip"
          :class="{ active: selectedMachine === item.machineId }"
          @click="selectedMachine = item.machineId; load()"
        >
          <PDot :state="item.state === 'ok' ? 'ok' : item.state === 'draining' ? 'draining' : 'bad'" />
          {{ item.machineId }}
        </button>
      </div>
    </header>

    <p v-if="driftCount" class="alert">{{ t('deploy.driftAlert') }}: {{ driftCount }}</p>
    <p v-if="machine && machine.state !== 'ok'" class="alert">{{ t('deploy.offline', { machine: machine.machineId }) }}</p>
    <div v-if="notice" class="notice">{{ notice }}</div>

    <div class="kpi-grid">
      <div class="kpi"><span>{{ t('deploy.kpi.params') }}</span><strong>{{ kpis.params }}</strong><small>{{ t('deploy.kpi.drift') }}: {{ kpis.drift }}</small></div>
      <div class="kpi"><span>{{ t('deploy.kpi.ops') }}</span><strong>{{ kpis.ops }}</strong><small>{{ t('deploy.kpi.opsHint') }}</small></div>
      <div class="kpi"><span>{{ t('deploy.kpi.hot') }}</span><strong>{{ kpis.hot }}</strong><small>{{ t('deploy.kpi.hotHint') }}</small></div>
      <div class="kpi"><span>{{ t('deploy.kpi.scene') }}</span><strong>{{ kpis.scene || DASH }}</strong><small>{{ t('deploy.kpi.sceneTitle') }}</small></div>
    </div>

    <div class="deploy-grid">
      <div class="card">
        <h2>{{ t('deploy.stack') }}</h2>
        <dl class="kv">
          <template v-for="row in detailRows" :key="row.labelKey">
            <dt>{{ t(row.labelKey) }}</dt>
            <dd
              :class="{ mono: row.mono }"
              :data-detail="row.labelKey"
            >
              <span v-if="row.tagClass" class="tag" :class="row.tagClass">{{ row.value || DASH }}</span>
              <span v-else-if="row.statusRow && row.value">{{ t(`machines.status.${row.value}`) }}</span>
              <span v-else-if="row.valueKey && row.params">{{ t(row.valueKey, row.params) }}</span>
              <span v-else-if="row.labelKey === 'deploy.field.configSource' && row.value === 'console'">{{ t('deploy.source.console') }}</span>
              <span v-else>{{ row.value || DASH }}</span>
            </dd>
          </template>
        </dl>
        <div class="rowline">
          <input v-model="confirmWord" class="confirm" :placeholder="t('deploy.confirmHint')" />
          <button class="action" @click="deploy('push')">{{ t('deploy.push') }}</button>
          <button class="action ghost" @click="deploy('rollback')">{{ t('deploy.rollback') }}</button>
          <button class="action ghost" @click="saveDraft">{{ t('deploy.saveDraft') }}</button>
        </div>
      </div>

      <div class="card">
        <h2>{{ t('deploy.groups') }} <span class="hint">{{ t('deploy.groupCount') }}</span></h2>
        <p class="note">{{ t('deploy.groupNote') }}</p>
        <table class="tbl">
          <thead><tr>
            <th>{{ t('deploy.groups') }}</th><th>{{ t('deploy.field.version') }}</th><th>{{ t('deploy.groupCount') }}</th>
          </tr></thead>
          <tbody>
            <tr v-for="item in stack" :key="item.group">
              <td>{{ item.group }}</td><td>{{ DASH }}</td><td>{{ item.count }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="deploy-grid">
      <div class="card">
        <h2>{{ t('deploy.node.title') }}</h2>
        <div class="metric-grid">
          <div v-for="item in nodeMetrics" :key="item.label" class="metric">
            <span>{{ item.label }}</span><strong>{{ item.value }}</strong>
          </div>
        </div>
      </div>
      <div class="card">
        <h2>{{ t('deploy.params.title') }}</h2>
        <div class="machine-chips">
          <button class="chip" :class="{ active: paramSource === 'runtime' }" @click="paramSource = 'runtime'">{{ t('deploy.params.runtime') }}</button>
          <button class="chip" :class="{ active: paramSource === 'declared' }" @click="paramSource = 'declared'">{{ t('deploy.params.declared') }}</button>
        </div>
        <div class="table-wrapper" role="region" :aria-label="t('deploy.params.title')" tabindex="0">
          <table class="tbl">
            <thead><tr><th>{{ t('deploy.params.key') }}</th><th>{{ t('deploy.params.value') }}</th></tr></thead>
            <tbody>
              <tr v-for="entry in deploymentEntries" :key="entry.key">
                <td class="mono">{{ entry.key }}</td><td class="mono wrap">{{ entry.value }}</td>
              </tr>
            </tbody>
          </table>
          <p v-if="!deploymentEntries.length" class="note">{{ DASH }}</p>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>{{ t('deploy.logs.title') }}</h2>
      <LogPanel
        :live="logsStore.live"
        @follow="logsStore.setLive($event)"
        @refresh="logsStore.reload()"
        @analyze="logsStore.analyze()"
      />
      <LogAnalysisCard
        :analysis="logsStore.analysis"
        :pending="logsStore.pending"
        :error="logsStore.analysisError"
        @retry="logsStore.analyze()"
      />
    </div>

    <div class="card">
      <h2>{{ t('deploy.sceneTitle') }}</h2>
      <div class="scene-list">
        <button v-for="scene in scenes" :key="scene.name" class="chip" :class="{ active: selectedScene === scene.name }" @click="applyScene(scene.name)">
          {{ scene.note }}
        </button>
      </div>
      <ScenarioAdvisor :scenes="scenes" :actual="actual" :patch="patch" @apply="patch = $event" />
    </div>

    <div class="card">
      <h2>{{ t('deploy.paramsTitle') }} <span class="hint">{{ selectedMachine || DASH }}</span></h2>
      <div class="machine-chips">
        <button v-for="item in chips" :key="item.group" class="chip" :class="{ active: group === item.group }" @click="group = item.group">
          {{ item.group === 'ALL' ? t('deploy.all') : item.group }} ({{ item.count }})
        </button>
      </div>
    </div>

    <div v-for="[stage] in grouped" :key="stage" class="card">
      <h2>{{ stage }} <span class="hint">{{ t('deploy.col.actual') }} · {{ selectedMachine || DASH }}</span></h2>
      <div v-if="group === 'ALL' || group === stage" class="table-scroll">
        <table class="tbl"><thead><tr>
          <th v-for="col in ['key','expected','actual','drift','source','effect','exposure','risk','anchor','draft','action']" :key="col">{{ col }}</th>
        </tr></thead><tbody>
          <tr v-for="row in visibleRows.filter((r) => r.key.split('.')[0] === stage)" :key="row.key" :class="rowTone({ ...row, draft: patch[row.key] }) ?? ''">
            <td>{{ row.key }}</td>
            <td>{{ row.expected ?? DASH }}</td>
            <td>{{ row.actual ?? DASH }}</td>
            <td>{{ row.drift ? '⚠' : DASH }}</td>
            <td>{{ row.source }}</td><td>{{ row.effect }}</td><td>{{ row.exposure }}</td>
            <td>{{ row.risk || DASH }}</td><td>{{ row.anchor || DASH }}</td>
            <td><input v-model="patch[row.key]" class="cell-input" /></td>
            <td><button class="link" @click="patch[row.key] = row.expected ?? ''">reset</button></td>
          </tr>
        </tbody></table>
      </div>
    </div>
  </section>
</template>

<style scoped lang="less">
.deploy-page { display: grid; gap: 16px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.hint { color: var(--muted); font-size: 12px; }
.note { color: var(--muted); font-size: 12px; }
.machine-chips, .scene-list { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
.chip { border: 1px solid var(--border); background: transparent; border-radius: 999px; padding: 4px 12px; cursor: pointer; }
.chip.active { background: var(--accent); color: var(--surface); }
.alert { background: var(--danger-soft); color: var(--danger-text); padding: 8px; border-radius: 4px; }
.notice { background: var(--ok-soft); color: var(--ok-text); padding: 8px; border-radius: 4px; }
.kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.kpi { display: flex; flex-direction: column; padding: 12px; border: 1px solid var(--border); border-radius: 8px; }
.kpi strong { font-size: 22px; }
.kpi small { color: var(--muted); }
.deploy-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.metric-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.metric { display: flex; flex-direction: column; gap: 4px; padding: 10px; border: 1px solid var(--border); border-radius: 6px; }
.metric span { color: var(--muted); font-size: 12px; }
.table-wrapper { overflow: auto; max-inline-size: 100%; max-block-size: min(420px, 70vh); container-type: inline-size; }
.table-wrapper thead { position: sticky; inset-block-start: 0; background: var(--surface); z-index: 1; }
.wrap { white-space: normal; word-break: break-all; }
.kv { display: grid; grid-template-columns: 130px 1fr; gap: 8px 12px; }
.kv dt { color: var(--muted); }
.kv dd { margin: 0; }
.rowline { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; align-items: center; }
.confirm, .cell-input { border: 1px solid var(--border); background: var(--surface); color: var(--text); padding: 4px 8px; border-radius: 4px; }
.action { background: var(--accent); color: var(--surface); border: 0; border-radius: 4px; padding: 6px 14px; cursor: pointer; }
.action.ghost { background: transparent; color: var(--text); border: 1px solid var(--border); }
.table-scroll { overflow-x: auto; }
.tbl { width: 100%; border-collapse: collapse; }
.tbl th, .tbl td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); white-space: nowrap; }
tr.drift { background: var(--danger-soft); }
tr.ops { background: var(--warn-soft); }
tr.ro { color: var(--muted); }
tr.draft { background: var(--accent-soft); }
.link { background: none; border: 0; color: var(--accent); cursor: pointer; }
</style>
