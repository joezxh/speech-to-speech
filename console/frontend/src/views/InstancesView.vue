<script setup lang="ts">
// Task 12（2026-11-17 原型对齐计划）：机器管理页按原型重写（§4.5）。
// 告警条 / 搜索+两按钮 / 12 列机器表（mtbl）/ 内联展开负载清单（svcrow，含模型/参数/显存）/
// 新增两步模态 + 三步测试面板 / 编辑模态。原型外的运行时/日志观测面板已移除。
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import PBadge from '@/components/proto/PBadge.vue'
import PDot from '@/components/proto/PDot.vue'
import PDrawer from '@/components/proto/PDrawer.vue'
import type { PColumn } from '@/components/proto/PTable.vue'
import MachineFormModal from '@/components/proto/MachineFormModal.vue'
import MachineTestPanel from '@/components/proto/MachineTestPanel.vue'
import ErrorBanner from '@/components/ErrorBanner.vue'
import { AppError } from '@/api/client'
import { issueMachineCommand, listMachineCommands } from '@/api/machines'
import type { MachineCommandView, MachineRow, CommandKind, WorkloadRow } from '@/views/machines.viewmodel'
import { useLogsStore } from '@/stores/logs'
import { useMachineStore } from '@/stores/machine'
import {
  commandActions,
  filterMachines,
  healthState,
  latestHealth,
  nodeMetricSummary,
  serviceIdOf,
  vramSummary,
  workloadParamEntries,
  workloadTags
} from './machines.viewmodel'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const store = useMachineStore()
const logsStore = useLogsStore()

// 拓扑下钻（?host=）映射为初始搜索词：host 命中机器 ID 或地址均可（Task 12 保留语义）。
const query = ref(String(route.query.host ?? ''))
watch(
  () => route.query.host,
  (host) => {
    if (host) query.value = String(host)
  }
)
const error = ref('')
const notice = ref('')
const commands = ref<Record<string, MachineCommandView[]>>({})
const expanded = ref<string | null>(null)
const formOpen = ref(false)
const formMode = ref<'create' | 'edit'>('create')
const formTarget = ref<MachineRow | null>(null)
const testTarget = ref<MachineRow | null>(null)

const DOT_STATE: Record<string, 'ok' | 'warn' | 'draining' | 'bad'> = {
  ok: 'ok',
  pending_register: 'warn',
  draining: 'draining',
  unreachable: 'bad'
}
const dotState = (state: string): 'ok' | 'warn' | 'draining' | 'bad' => DOT_STATE[state] ?? 'warn'

const rows = computed(() => filterMachines(store.machines, query.value))

// 告警条：心跳超时（>60s 无 last_seen 更新）与未绑定实例提示由后端字段推导。
const staleMachines = computed(() =>
  store.machines.filter((m) => {
    if (!m.lastSeen) return true
    return Date.now() - new Date(m.lastSeen).getTime() > 60_000
  })
)

const columns: PColumn[] = [
  { key: 'machineId', label: t('machines.admin.columns.machine'), width: 190, sticky: 'start', cls: 'mono' },
  { key: 'role', label: t('machines.admin.columns.role'), width: 80 },
  { key: 'gpu', label: t('machines.admin.columns.gpu'), width: 110 },
  { key: 'state', label: t('machines.admin.columns.state'), width: 130 },
  { key: 'registryMode', label: t('machines.admin.columns.registry'), width: 80 },
  { key: 'agentVersion', label: t('machines.admin.columns.agentVersion'), width: 110, cls: 'mono' },
  { key: 'lastSeen', label: t('machines.admin.columns.lastSeen'), width: 170 },
  { key: 'workloads', label: t('machines.admin.columns.workloads'), width: 240 },
  { key: 'vram', label: t('machines.admin.columns.vram'), width: 150 },
  { key: 'clusterId', label: t('machines.admin.columns.cluster'), width: 110 },
  { key: 'addr', label: t('machines.admin.columns.addr'), width: 140, cls: 'mono' },
  { key: 'actions', label: t('machines.admin.columns.actions'), width: 200, sticky: 'end' }
]

function toggleExpand(id: string): void {
  expanded.value = expanded.value === id ? null : id
}

function openCreate(): void {
  formMode.value = 'create'
  formTarget.value = null
  formOpen.value = true
}

function openEdit(machine: MachineRow): void {
  formMode.value = 'edit'
  formTarget.value = machine
  formOpen.value = true
}

function openTest(machine: MachineRow): void {
  testTarget.value = machine
}

async function remove(machine: MachineRow): Promise<void> {
  if (!window.confirm(t('machines.admin.confirmDelete', { id: machine.machineId }))) return
  try {
    await store.remove(machine.machineId)
  } catch (caught) {
    error.value = caught instanceof AppError ? caught.message : t('machines.admin.deleteFailed')
  }
}

const activeKinds = (machineId: string): string[] =>
  (commands.value[machineId] ?? [])
    .filter((command) => command.status === 'pending' || command.status === 'dispatched')
    .map((command) => command.kind)
const actionsFor = (machine: MachineRow) => commandActions(machine.state, activeKinds(machine.machineId))

async function issue(machine: MachineRow, kind: CommandKind, serviceId = ''): Promise<void> {
  error.value = ''
  notice.value = ''
  try {
    await issueMachineCommand(machine.machineId, kind, serviceId)
    notice.value = t('machines.action.issued', { kind: t(`machines.action.${kind}`), id: machine.machineId })
    commands.value[machine.machineId] = await listMachineCommands(machine.machineId)
  } catch (caught) {
    error.value = caught instanceof AppError ? caught.message : t('machines.action.failed')
  }
}

const checkState = (machine: MachineRow, workload: WorkloadRow) =>
  healthState(latestHealth(commands.value[machine.machineId] ?? [], serviceIdOf(workload)))
const checkService = (machine: MachineRow, workload: WorkloadRow) =>
  issue(machine, 'health_check', serviceIdOf(workload))

function goDeploy(machine: MachineRow): void {
  void router.push({ name: 'deploy', query: { machine: machine.machineId } })
}

const deploymentCounts = (machine: MachineRow) => ({
  runtime: Object.keys(machine.deployment?.runtime ?? {}).length,
  declared: Object.keys(machine.deployment?.declared ?? {}).length
})

function goLogs(machine: MachineRow): void {
  logsStore.filters.process = ['pipeline']
  logsStore.filters.q = machine.machineId
  void logsStore.reload()
  void logsStore.analyze()
  goDeploy(machine)
}

async function poll(): Promise<void> {
  await store.fetch()
  await Promise.allSettled(
    store.machines.map(async (machine) => {
      commands.value[machine.machineId] = await listMachineCommands(machine.machineId)
    })
  )
}

void poll()
const pollTimer = setInterval(poll, 5000)
onBeforeUnmount(() => clearInterval(pollTimer))
</script>

<template>
  <div class="machines-page">
    <!-- 告警条 -->
    <div v-if="staleMachines.length" class="note">
      {{ t('machines.admin.alertStale', { ids: staleMachines.map((m) => m.machineId).join(', ') }) }}
    </div>

    <!-- 搜索 + 两按钮 -->
    <div class="rowline">
      <input v-model="query" class="fin" style="max-width: 260px" :placeholder="t('machines.admin.searchPlaceholder')" />
      <span class="spacer"></span>
      <button type="button" class="btn" @click="store.acceptAutoRegister({ clusterId: 'default' })">
        {{ t('machines.admin.autoRegister') }}
      </button>
      <button type="button" class="btn primary" @click="openCreate">{{ t('machines.admin.newMachine') }}</button>
    </div>

    <ErrorBanner v-if="store.error" :error="new AppError('unknown', store.error)" />
    <ErrorBanner v-if="error" :error="new AppError('unknown', error)" />
    <div v-if="notice" class="note">{{ notice }}</div>

    <!-- 12 列机器表（mtbl）；单击展开负载，双击下钻部署页 -->
    <div class="tscroll">
      <table class="tbl mtbl">
        <thead>
          <tr>
            <th v-for="col in columns" :key="col.key" :class="col.cls" :style="col.width ? { width: col.width + 'px' } : {}">
              {{ col.label }}
            </th>
          </tr>
        </thead>
        <tbody>
          <template v-for="row in rows" :key="row.machineId">
            <tr
              class="clickable"
              :data-machine="row.machineId"
              @click="toggleExpand(row.machineId)"
              @dblclick="goDeploy(row)"
            >
              <td class="mono">
                <PDot :state="dotState(row.state)" />
                {{ row.machineId }}
              </td>
              <td>{{ row.role }}</td>
              <td>{{ row.gpu || '—' }}</td>
              <td>
                <PBadge kind="equal" :text="t(`machines.status.${row.state}`)" />
              </td>
              <td>{{ t(`machines.admin.registry.${row.registryMode === 'auto' ? 'auto' : 'manual'}`) }}</td>
              <td>{{ row.agentVersion || '—' }}</td>
              <td>{{ row.lastSeen || '—' }}</td>
              <td>
                <span class="wls">
                  <span v-for="tag in workloadTags(row.workloads)" :key="tag.kind" class="tag" :class="`wl-${tag.kind}`">
                    {{ tag.kind }} ×{{ tag.count }}
                  </span>
                </span>
              </td>
              <td>
                <template v-if="vramSummary(row.workloads, row.gpuTotalGb).totalGb > 0">
                  <div class="bar">
                    <i
                      :style="{
                        width: Math.min(100, vramSummary(row.workloads, row.gpuTotalGb).pct) + '%'
                      }"
                    ></i>
                  </div>
                  <small>{{ vramSummary(row.workloads, row.gpuTotalGb).usedGb }} / {{ row.gpuTotalGb }} GB</small>
                </template>
                <template v-else>—</template>
              </td>
              <td>{{ row.clusterId || '—' }}</td>
              <td>{{ row.addr || '—' }}</td>
              <td @click.stop @dblclick.stop>
                <button
                  v-for="action in actionsFor(row)"
                  :key="action.kind"
                  type="button"
                  class="btn sm"
                  :data-action="action.kind"
                  :disabled="action.disabled"
                  @click="issue(row, action.kind)"
                >
                  {{ t(action.labelKey) }}
                </button>
                <button type="button" class="btn sm" @click="openTest(row)">{{ t('machines.test.start') }}</button>
                <button type="button" class="btn sm" @click="openEdit(row)">{{ t('machines.form.edit') }}</button>
                <button type="button" class="btn sm ghost" @click="remove(row)">{{ t('machines.form.delete') }}</button>
              </td>
            </tr>
            <!-- 内联展开：负载清单 + 汇总行 -->
            <tr v-if="expanded === row.machineId" class="svcrow">
              <td :colspan="columns.length">
                <div class="svc-sum">
                  <span>{{ t('machines.admin.workloadSum', { n: row.workloads.length, used: vramSummary(row.workloads, row.gpuTotalGb).usedGb, total: row.gpuTotalGb ?? 0 }) }}</span>
                </div>
                <div class="svc-sum">
                  <strong>{{ t('machines.admin.nodeTitle') }}</strong>
                  <span v-for="metric in nodeMetricSummary(row)" :key="metric.key">
                    {{ t(`machines.admin.nodeMetric.${metric.key}`) }}: {{ metric.value }}
                  </span>
                </div>
                <div class="svc-sum">
                  <strong>{{ t('machines.admin.deploySummary') }}</strong>
                  <span>{{ t('machines.admin.deployCounts', deploymentCounts(row)) }}</span>
                  <button type="button" class="btn sm" @click.stop="goDeploy(row)">{{ t('machines.admin.deployAction') }}</button>
                  <button type="button" class="btn sm" @click.stop="goLogs(row)">{{ t('machines.admin.logsAction') }}</button>
                </div>
                <table class="tbl">
                  <thead>
                    <tr>
                      <th>{{ t('machines.admin.workloadCols.kind') }}</th>
                      <th>{{ t('machines.admin.workloadCols.engine') }}</th>
                      <th>{{ t('machines.admin.workloadCols.model') }}</th>
                      <th>{{ t('machines.admin.workloadCols.port') }}</th>
                      <th>{{ t('machines.admin.workloadCols.listen') }}</th>
                      <th>{{ t('machines.admin.workloadCols.healthPath') }}</th>
                      <th>{{ t('machines.admin.workloadCols.vramGb') }}</th>
                      <th>{{ t('machines.admin.workloadCols.params') }}</th>
                      <th>{{ t('machines.admin.workloadCols.check') }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="wl in row.workloads" :key="`${wl.kind}-${wl.port}`">
                      <td><span class="tag" :class="`wl-${wl.kind}`">{{ wl.kind }}</span></td>
                      <td class="mono">{{ wl.engine || '—' }}</td>
                      <td class="mono">{{ wl.model || '—' }}</td>
                      <td class="mono">{{ wl.port ?? '—' }}</td>
                      <td class="mono">{{ wl.listen || '—' }}</td>
                      <td class="mono">{{ wl.healthPath || '—' }}</td>
                      <td>{{ wl.vramGb != null ? `${wl.vramGb} GB` : '—' }}</td>
                      <td>
                        <details v-if="workloadParamEntries(wl.params).length">
                          <summary>{{ t('machines.admin.paramsCount', { n: workloadParamEntries(wl.params).length }) }}</summary>
                          <pre class="param-list">{{ workloadParamEntries(wl.params).map((p) => `${p.key} = ${p.value}`).join('\n') }}</pre>
                        </details>
                        <span v-else>—</span>
                      </td>
                      <td>
                        <span class="mono" :data-check="serviceIdOf(wl)">
                          {{ t(`machines.checkResult.${checkState(row, wl)}`) }}
                        </span>
                        <button
                          type="button"
                          class="btn sm"
                          :data-svc-check="serviceIdOf(wl)"
                          @click.stop="checkService(row, wl)"
                        >
                          {{ t('machines.action.health_check') }}
                        </button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </td>
            </tr>
          </template>
          <tr v-if="!rows.length">
            <td :colspan="columns.length" class="empty-cell">
              {{ t('machines.admin.empty') }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 三步测试面板（抽屉） -->
    <PDrawer :open="testTarget !== null" :title="t('machines.test.title')" @close="testTarget = null">
      <MachineTestPanel
        v-if="testTarget"
        :machine-id="testTarget.machineId"
        :addr="testTarget.addr"
      />
    </PDrawer>

    <!-- 新增/编辑两步模态 -->
    <MachineFormModal :open="formOpen" :mode="formMode" :machine="formTarget" @close="formOpen = false" />

  </div>
</template>

<style scoped lang="less">
.machines-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.empty-cell { text-align: center; opacity: 0.65; }
.param-list {
  max-height: 220px;
  max-width: 520px;
  overflow: auto;
  margin: 6px 0 0;
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
