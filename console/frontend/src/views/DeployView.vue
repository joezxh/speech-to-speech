<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import ScenarioAdvisor from '@/components/proto/ScenarioAdvisor.vue'
import { machineConfigApi, type MachineParamRow } from '@/api/machineConfig'
import { useMachineStore as useMachinesStore } from '@/stores/machine'
import { DASH } from '@/utils/format'
import { SCENES } from './scenes'
import { rowTone } from './deploy.viewmodel'

const { t } = useI18n()
const machinesStore = useMachinesStore()
const selectedMachine = ref('')
const rows = ref<MachineParamRow[]>([])
const driftCount = ref(0)
const patch = ref<Record<string, string>>({})
const draftVersion = ref(0)
const confirmWord = ref('')
const notice = ref('')
const scenes = SCENES

const grouped = computed(() => {
  const groups = new Map<string, MachineParamRow[]>()
  for (const row of rows.value) {
    const stage = row.key.split('.')[0]
    if (!groups.has(stage)) groups.set(stage, [])
    groups.get(stage)!.push(row)
  }
  return [...groups.entries()]
})
const actual = computed(() => Object.fromEntries(rows.value.map((r) => [r.key, r.actual ?? ''])))

async function load(): Promise<void> {
  await machinesStore.load()
  if (!selectedMachine.value && machinesStore.machines.length) selectedMachine.value = machinesStore.machines[0].machineId
  if (!selectedMachine.value) return
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

async function saveDraft(): Promise<void> {
  if (!selectedMachine.value) return
  await machineConfigApi.putDraft(selectedMachine.value, patch.value, draftVersion.value)
  notice.value = '草稿已保存'
  await load()
}

async function deploy(mode: 'push' | 'rollback'): Promise<void> {
  if (!selectedMachine.value) return
  await machineConfigApi.deploy(selectedMachine.value, mode, confirmWord.value)
  notice.value = mode === 'push' ? '已下发' : '已回滚到最近 ack 版本'
  confirmWord.value = ''
}

onMounted(load)
</script>

<template>
  <section class="deploy-page">
    <header class="card">
      <h1>{{ t('deploy.title') }}</h1>
      <div class="machine-chips">
        <button v-for="machine in machinesStore.machines" :key="machine.machineId" class="chip" :class="{ active: selectedMachine === machine.machineId }" @click="selectedMachine = machine.machineId; load()">
          {{ machine.machineId }}
        </button>
      </div>
    </header>

    <div v-if="driftCount" class="alert">{{ t('deploy.driftAlert') }}: {{ driftCount }}</div>
    <div v-if="!selectedMachine" class="alert">{{ t('deploy.offline') }}</div>
    <div v-if="notice" class="notice">{{ notice }}</div>

    <div class="kpi-grid">
      <div class="kpi"><span>参数行</span><strong>{{ rows.length }}</strong></div>
      <div class="kpi"><span>漂移</span><strong>{{ driftCount }}</strong></div>
      <div class="kpi"><span>草稿版本</span><strong>{{ draftVersion }}</strong></div>
      <div class="kpi"><span>草稿键</span><strong>{{ Object.keys(patch).length }}</strong></div>
    </div>

    <div class="card">
      <h2>部署栈</h2>
      <input v-model="confirmWord" class="confirm" :placeholder="t('deploy.confirmHint')" />
      <button class="action" @click="deploy('push')">{{ t('deploy.push') }}</button>
      <button class="action ghost" @click="deploy('rollback')">{{ t('deploy.rollback') }}</button>
      <button class="action ghost" @click="saveDraft">{{ t('deploy.saveDraft') }}</button>
    </div>

    <div class="card">
      <h2>场景顾问</h2>
      <ScenarioAdvisor :scenes="scenes" :actual="actual" :patch="patch" @apply="patch = $event" />
    </div>

    <div v-for="[stage, stageRows] in grouped" :key="stage" class="card">
      <h2>{{ stage }}</h2>
      <div class="table-scroll"><table class="tbl"><thead><tr>
        <th v-for="col in ['key','expected','actual','drift','source','effect','exposure','risk','anchor','draft','action']" :key="col">{{ col }}</th>
      </tr></thead><tbody>
        <tr v-for="row in stageRows" :key="row.key" :class="rowTone({ ...row, draft: patch[row.key] }) ?? ''">
          <td>{{ row.key }}</td>
          <td>{{ row.expected ?? DASH }}</td>
          <td>{{ row.actual ?? DASH }}</td>
          <td>{{ row.drift ? '⚠' : '—' }}</td>
          <td>{{ row.source }}</td><td>{{ row.effect }}</td><td>{{ row.exposure }}</td>
          <td>{{ row.risk || DASH }}</td><td>{{ row.anchor || DASH }}</td>
          <td><input v-model="patch[row.key]" class="cell-input" /></td>
          <td><button class="link" @click="patch[row.key] = row.expected ?? ''">reset</button></td>
        </tr>
      </tbody></table></div>
    </div>
  </section>
</template>

<style scoped lang="less">
.deploy-page { display: grid; gap: 16px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.machine-chips { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
.chip { border: 1px solid var(--border); background: transparent; border-radius: 999px; padding: 4px 12px; cursor: pointer; }
.chip.active { background: var(--accent); color: var(--surface); }
.alert { background: var(--danger-soft); color: var(--danger-text); padding: 8px; border-radius: 4px; }
.notice { background: var(--ok-soft); color: var(--ok-text); padding: 8px; border-radius: 4px; }
.kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.kpi { display: flex; flex-direction: column; padding: 12px; border: 1px solid var(--border); border-radius: 8px; }
.kpi strong { font-size: 22px; }
.confirm, .cell-input { border: 1px solid var(--border); background: var(--surface); color: var(--text); padding: 4px 8px; border-radius: 4px; }
.action { background: var(--accent); color: var(--surface); border: 0; border-radius: 4px; padding: 6px 14px; margin-right: 8px; cursor: pointer; }
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
