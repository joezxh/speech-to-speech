<script setup lang="ts">
import { message } from 'ant-design-vue'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { api, AppError } from '@/api/client'
import { clustersApi } from '@/api/clusters'
import { listMachines } from '@/api/machines'
import ClusterFormModal from '@/components/ClusterFormModal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ErrorBanner from '@/components/ErrorBanner.vue'
import TopoChart from '@/components/TopoChart.vue'
import { useConfirm } from '@/composables/useConfirm'
import { useAuthStore } from '@/stores/auth'
import { useClusterStore } from '@/stores/cluster'
import { useConsoleStore } from '@/stores/console'
import type { ClusterEventRow, ClusterRow, InstanceRow, InstanceSnapshot, InstancesSummary } from '@/types/api'
import { clusterKpis } from '@/utils/clusterKpis'
import { clusterStatus, type ClusterStatus } from '@/utils/clusterStatus'
import { describeAlert } from '@/utils/error'
import { DASH, formatTime } from '@/utils/format'
import { hostOf } from '@/utils/host'
import { layoutTopo } from '@/utils/topoLayout'
import { topoRows, type Instance, type Machine } from './overview.viewmodel'

/**
 * 集群总览（spec §5.2，原型 renderOverview/clusterRows/topoSVG）：
 * 页面头 + 五段=KPI 四卡 / 集群表 CRUD / 拓扑 / 图例+最近事件 / 全降级态。
 * 数据只有三个来源：/clusters、/clusters/events、/instances?cluster=，不引 Mock。
 * 端点各败各的：一条告警或一个端点不可用都不能让整页空白。
 */
const consoleStore = useConsoleStore()
const clusterStore = useClusterStore()
const auth = useAuthStore()
const router = useRouter()
const { t } = useI18n()
const {
  open: confirmOpen,
  title: confirmTitle,
  content: confirmContent,
  ask: askConfirm,
  answer: answerConfirm
} = useConfirm()

const summary = ref<InstancesSummary | null>(null)
const instances = ref<InstanceRow[]>([])
const alerts = ref<string[]>([])
const events = ref<ClusterEventRow[]>([])
const instancesError = ref<AppError | null>(null)
const eventsError = ref<AppError | null>(null)
const actionError = ref<AppError | null>(null)
const formOpen = ref(false)
const formCluster = ref<ClusterRow | null>(null)

const kpis = computed(() => clusterKpis(clusterStore.currentRow, summary.value))

const KPI_LABELS: Record<string, string> = {
  machines: 'overview.kpi.machines',
  instances: 'overview.kpi.pipelineInstances',
  sessions: 'overview.kpi.activeSessions',
  errorRate: 'overview.kpi.errorRate'
}

const STATUS_COLOR: Record<ClusterStatus, string> = {
  ok: 'green',
  warn: 'orange',
  draining: 'orange',
  bad: 'red',
  muted: 'default'
}

const EVENT_CATEGORIES = ['cluster', 'param', 'deploy', 'release', 'voice', 'machine', 'access']
function categoryOf(action: string): string {
  const prefix = action.split('.')[0]
  return EVENT_CATEGORIES.includes(prefix) ? prefix : 'other'
}

// 机器层：param_machine 行（含 label 与负载模型）∪ 实例 host 派生（同 host 去重）。
// 只按实例派生时，注册了机器但还没绑实例的节点不上拓扑（用户反馈）。
const topo = computed(() => {
  const byHost = new Map<
    string,
    { host: string; online: boolean; label?: string; models?: string[] }
  >()
  for (const machine of machines.value) {
    if (machine.clusterId !== clusterStore.current) continue
    byHost.set(hostOf(machine.addr), {
      host: hostOf(machine.addr),
      online: machine.state === 'ok',
      label: machine.machineId,
      models: machine.workloads.map((w) => (w.model ? `${w.kind}·${w.model}` : w.kind))
    })
  }
  for (const row of instances.value) {
    const host = hostOf(row.base_url)
    const existing = byHost.get(host)
    byHost.set(host, {
      host,
      online: (existing?.online ?? false) || row.status === 'online',
      label: existing?.label,
      models: existing?.models
    })
  }
  const current = clusterStore.currentRow
  return layoutTopo({
    cluster: clusterStore.current,
    registry: current?.registry ?? '',
    policy: current?.policy ?? 'least',
    sessions: summary.value?.slots_in_use ?? null,
    machines: [...byHost.values()],
    instances: instances.value.map((row) => ({
      id: row.instance_id,
      status: row.status,
      host: hostOf(row.base_url),
      inUse: row.in_use,
      size: row.size
    }))
  })
})

async function loadClusterData(): Promise<void> {
  const [instancesResult, eventsResult] = await Promise.allSettled([
    api.get<InstanceSnapshot>('/instances', {
      params: { profile: consoleStore.profile, cluster: clusterStore.current }
    }),
    clustersApi.events(4)
  ])
  if (instancesResult.status === 'fulfilled') {
    summary.value = instancesResult.value.summary ?? null
    instances.value = instancesResult.value.instances ?? []
    alerts.value = instancesResult.value.alerts ?? []
    instancesError.value = null
  } else {
    summary.value = null
    instances.value = []
    alerts.value = []
    instancesError.value =
      instancesResult.reason instanceof AppError
        ? instancesResult.reason
        : new AppError('unknown', t('errors.load.instances'))
  }
  if (eventsResult.status === 'fulfilled') {
    events.value = eventsResult.value
    eventsError.value = null
  } else {
    events.value = []
    eventsError.value =
      eventsResult.reason instanceof AppError
        ? eventsResult.reason
        : new AppError('unknown', t('errors.load.events'))
  }
}

// 15s 自动刷新（原型是静态 mock，真实数据需要持续更新）：防重入，避免
// /instances 探池耗时数秒时请求叠罗汉；卸载即清理。
let refreshing = false
let timer: number | undefined
// Task 29 真值区（原型对齐后只留拓扑分组表；重复 KPI 与事件"日志"已按反馈删除）。
const machines = ref<Machine[]>([])
const machineInstances = computed<Instance[]>(() =>
  instances.value.map((row) => ({
    instance_id: row.instance_id,
    base_url: row.base_url,
    machine_id: row.machine_id ?? null,
    status: row.status ?? 'unknown',
  }))
)
const protoTopo = computed(() => topoRows(machines.value, machineInstances.value))

async function refreshSafely(): Promise<void> {
  if (refreshing) return
  refreshing = true
  try {
    await loadClusterData()
    const machinesResult = await listMachines().then(
      (value) => value,
      () => null
    )
    if (machinesResult) machines.value = machinesResult.machines as unknown as Machine[]
  } finally {
    refreshing = false
  }
}

onMounted(async () => {
  await clusterStore.load()
  await refreshSafely()
  timer = window.setInterval(() => void refreshSafely(), 15000)
})
onBeforeUnmount(() => {
  if (timer !== undefined) window.clearInterval(timer)
})

watch(() => clusterStore.current, () => void refreshSafely())
watch(() => consoleStore.profile, () => void refreshSafely())

function openCreate(): void {
  formCluster.value = null
  formOpen.value = true
}

function openEdit(row: ClusterRow): void {
  formCluster.value = row
  formOpen.value = true
}

async function onSaved(row: ClusterRow): Promise<void> {
  const isNew = formCluster.value === null
  await clusterStore.load()
  // 场景 3：新增成功后自动切入新集群，便于紧接着加机器；switchTo 顺带留审计。
  if (isNew) await clusterStore.switchTo(row.name)
  message.success(t(isNew ? 'overview.toast.created' : 'overview.toast.updated', { name: row.name }))
  await refreshSafely()
}

async function switchCluster(row: ClusterRow): Promise<void> {
  actionError.value = null
  const ok = await clusterStore.switchTo(row.name)
  if (!ok) {
    actionError.value = clusterStore.error
    message.error(t('overview.toast.switchFailed', { message: clusterStore.error?.message ?? '' }))
    return
  }
  message.success(t('overview.toast.switched', { name: row.name }))
  await refreshSafely()
}

async function removeCluster(row: ClusterRow): Promise<void> {
  const confirmed = await askConfirm({
    title: t('overview.actions.delete'),
    content: t('overview.confirm.deleteContent', { name: row.name })
  })
  if (!confirmed) return
  actionError.value = null
  try {
    await clusterStore.remove(row.name)
    message.success(t('overview.toast.deleted', { name: row.name }))
  } catch (caught) {
    const err = caught instanceof AppError ? caught : new AppError('unknown', String(caught))
    actionError.value = err
    if (err.code === 'last_cluster') message.warning(t('overview.toast.last'))
    else if (err.code === 'cluster_not_empty')
      message.warning(t('overview.toast.blocked', { name: row.name, n: row.machines_total }))
    else message.error(t('overview.toast.serverError', { message: err.message }))
  }
  await refreshSafely()
}

// 场景 8：拓扑里的机器跳部署参数页，用 query.host 带身份（Task 12 接手高亮/筛选）。
function goMachine(host: string): void {
  void router.push({ name: 'machines', query: { host } })
}

const tableColumns = computed(() => [
  { title: t('overview.table.cluster'), key: 'name' },
  { title: t('overview.table.registry'), key: 'registry' },
  { title: t('overview.table.policy'), key: 'policy', width: 130 },
  { title: t('overview.table.machines'), key: 'machines', width: 90 },
  { title: t('overview.table.instances'), key: 'instances', width: 90 },
  { title: t('overview.table.status'), key: 'status', width: 90 },
  { title: t('overview.table.actions'), key: 'actions', width: 220 }
])
</script>

<template>
  <div class="overview">
    <!-- 原型 head(nav.overview, overview.desc)：页面标题 + 一句说明。 -->
    <div class="overview__head">
      <h1>{{ t('overview.page.title') }}</h1>
      <p>{{ t('overview.page.desc') }}</p>
    </div>

    <ErrorBanner :error="instancesError" />
    <ErrorBanner :error="eventsError" />
    <ErrorBanner :error="clusterStore.error" />
    <ErrorBanner :error="actionError" />

    <section v-if="alerts.length" class="overview__alerts">
      <a-alert v-for="alert in alerts" :key="alert" type="warning" show-icon :message="describeAlert(alert)" />
    </section>

    <!-- Task 29 真值区（原型对齐后只留拓扑分组表；重复 KPI 与事件日志已删）。 -->
    <div class="overview__truth">
      <table class="truth-topo">
        <thead><tr><th>machine</th><th>instances</th></tr></thead>
        <tbody>
          <tr v-for="row in protoTopo" :key="row.machine_id ?? '__unbound__'">
            <td>{{ row.machine_id ?? '未绑定实例' }}</td>
            <td>{{ row.instances.map((i) => i.instance_id).join('、') || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ① KPI 四卡：机器 / 实例 / 活跃会话 / 错误率(5m)，随当前集群联动。 -->
    <div class="overview__grid">
      <a-card v-for="kpi in kpis" :key="kpi.key" size="small" class="kpi">
        <p class="kpi__label">{{ t(KPI_LABELS[kpi.key]) }}</p>
        <p class="kpi__value" :class="`is-${kpi.tone}`" :data-metric="`kpi.${kpi.key}`">{{ kpi.primary }}</p>
        <p v-if="kpi.subKey" class="kpi__sub">{{ t(`overview.kpi.sub.${kpi.subKey}`, kpi.subParams) }}</p>
      </a-card>
    </div>

    <!-- ② 集群表：当前行带「当前」标签且不摆切换按钮（场景 2）。 -->
    <a-card size="small">
      <template #title>
        <span class="overview__card-title">{{ t('overview.table.sectionTitle') }}</span>
        <span class="overview__card-hint">{{ t('overview.table.hint') }}</span>
      </template>
      <template #extra>
        <a-button v-if="auth.hasPermission('console:cluster:create')" size="small" type="primary" @click="openCreate">
          {{ t('overview.actions.create') }}
        </a-button>
      </template>
      <a-table
        size="small"
        row-key="name"
        :pagination="false"
        :data-source="clusterStore.rows"
        :columns="tableColumns"
        :locale="{ emptyText: t('overview.table.empty') }"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <span class="cluster-name">{{ record.name }}</span>
            <a-tag v-if="record.name === clusterStore.current" color="blue">{{ t('overview.table.current') }}</a-tag>
            <p v-if="record.note" class="cluster-note">{{ record.note }}</p>
          </template>
          <template v-else-if="column.key === 'registry'">
            <span class="mono">{{ record.registry || DASH }}</span>
          </template>
          <template v-else-if="column.key === 'policy'">
            {{ t(`overview.policy.${record.policy}`) }}
          </template>
          <template v-else-if="column.key === 'machines'">
            <span class="mono">{{ record.machines_online }} / {{ record.machines_total }}</span>
          </template>
          <template v-else-if="column.key === 'instances'">
            <span class="mono">{{ record.instances_total }}</span>
          </template>
          <template v-else-if="column.key === 'status'">
            <a-tag :color="STATUS_COLOR[clusterStatus(record as ClusterRow)]">
              {{ t(`overview.status.${clusterStatus(record as ClusterRow)}`) }}
            </a-tag>
          </template>
          <template v-else-if="column.key === 'actions'">
            <a-space>
              <a-button
                v-if="record.name !== clusterStore.current && auth.hasPermission('console:cluster:switch')"
                size="small"
                @click="switchCluster(record as ClusterRow)"
              >
                {{ t('overview.actions.switchTo') }}
              </a-button>
              <a-button
                v-if="auth.hasPermission('console:cluster:update')"
                size="small"
                @click="openEdit(record as ClusterRow)"
              >
                {{ t('overview.actions.edit') }}
              </a-button>
              <a-button
                v-if="auth.hasPermission('console:cluster:delete')"
                size="small"
                danger
                @click="removeCluster(record as ClusterRow)"
              >
                {{ t('overview.actions.delete') }}
              </a-button>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <!-- ③ 拓扑：集群→LB→机器→pipeline 实例，机器可点跳部署参数页（场景 8）。 -->
    <a-card size="small">
      <template #title>
        <span class="overview__card-title">{{ t('overview.topology.title') }}</span>
        <span class="overview__card-hint">{{ t('overview.topology.hint') }}</span>
      </template>
      <TopoChart :layout="topo" @machine="goMachine" />
    </a-card>

    <div class="overview__split">
      <!-- ④a 图例：原型六项（LB / 健康 / 降级 / 排空中 / 故障 / 流动连线）。 -->
      <a-card size="small" :title="t('overview.legend.title')">
        <ul class="legend">
          <li><span class="legend__lb" />{{ t('overview.legend.lb') }}</li>
          <li><span class="legend__dot is-ok" />{{ t('overview.legend.ok') }}</li>
          <li><span class="legend__dot is-warn" />{{ t('overview.legend.warn') }}</li>
          <li><span class="legend__dot is-draining" />{{ t('overview.legend.draining') }}</li>
          <li><span class="legend__dot is-bad" />{{ t('overview.legend.bad') }}</li>
          <li><span class="legend__flow" />{{ t('overview.legend.flow') }}</li>
        </ul>
      </a-card>

      <!-- ④b 最近事件：原型无表头、五列含「分类」tag；action 代码态不翻译，结果列翻译。 -->
      <a-card size="small">
        <template #title>
          <span class="overview__card-title">{{ t('overview.events.title') }}</span>
          <span class="overview__card-hint">{{ t('overview.events.hint') }}</span>
        </template>
        <table v-if="events.length" class="events-table">
          <tbody>
            <tr v-for="event in events" :key="event.auditId">
              <td class="mono">{{ formatTime(event.at) }}</td>
              <td>{{ event.actor }}</td>
              <td><span class="tag tag--accent">{{ t(`overview.events.cat.${categoryOf(event.action)}`) }}</span></td>
              <td class="mono">{{ event.action }}</td>
              <td>
                <span :class="['tag', event.result === 'ok' ? 'tag--ok' : 'tag--bad']">
                  {{ t(event.result === 'ok' ? 'overview.events.ok' : 'overview.events.error') }}<template v-if="event.result === 'error' && event.errorCode"> · {{ event.errorCode }}</template>
                </span>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="events-empty">{{ t('overview.events.empty') }}</p>
      </a-card>
    </div>

    <ClusterFormModal v-model:open="formOpen" :cluster="formCluster" @saved="onSaved" />
    <ConfirmDialog :open="confirmOpen" :title="confirmTitle" :content="confirmContent" @answer="answerConfirm" />
  </div>
</template>

<style scoped lang="less">
.overview__truth {
  display: grid;
  gap: 12px;
}
.truth-topo {
  width: 100%;
  border-collapse: collapse;
}
.truth-topo th,
.truth-topo td {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
}
.overview {
  display: flex;
  flex-direction: column;
  gap: 16px;

  &__head {
    margin: 0 0 2px;

    h1 {
      color: var(--s2s-color-text);
      font-size: 20px;
      margin: 0 0 6px;
    }

    p {
      color: var(--s2s-color-muted);
      font-size: 13px;
      margin: 0;
    }
  }

  &__card-title {
    font-weight: 600;
  }

  &__card-hint {
    color: var(--s2s-color-faint);
    font-size: 12px;
    font-weight: 400;
    margin-left: 8px;
  }

  &__alerts {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  /* 原型 .grid.g4：四卡等宽铺满整行；窄屏（≤1100px）降为两列。 */
  &__grid {
    display: grid;
    gap: 14px;
    grid-template-columns: repeat(4, minmax(0, 1fr));

    @media (max-width: 1100px) {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  &__split {
    display: grid;
    gap: 12px;
    grid-template-columns: 260px 1fr;
  }
}

.kpi {
  /* 原型 .kpi padding: 14px 16px；a-card 的 body 需穿透 scoped 才能覆盖。 */
  :deep(.ant-card-body) {
    padding: 14px 16px;
  }

  &__label {
    color: var(--s2s-color-muted);
    font-size: 12px;
    margin: 0;
  }

  &__value {
    color: var(--s2s-color-text);
    font-family: var(--s2s-font-mono);
    font-size: 24px;
    font-variant-numeric: tabular-nums;
    font-weight: 680;
    margin: 6px 0 0;

    &.is-warn {
      color: var(--s2s-color-warning);
    }

    &.is-muted {
      color: var(--s2s-color-muted);
    }
  }

  &__sub {
    color: var(--s2s-color-faint);
    font-family: var(--s2s-font-mono);
    font-size: 11px;
    margin: 4px 0 0;
  }
}

.cluster-name {
  color: var(--s2s-color-text);
  font-weight: 600;
}

.cluster-note {
  color: var(--s2s-color-muted);
  font-size: 11px;
  margin: 2px 0 0;
  white-space: pre-wrap;
}

.mono {
  font-family: var(--s2s-font-mono);
  font-size: 12px;
}

.legend {
  list-style: none;
  margin: 0;
  padding: 0;

  li {
    align-items: center;
    color: var(--s2s-color-text);
    display: flex;
    font-size: 12px;
    gap: 8px;
    padding: 2px 0;
  }

  &__dot {
    border-radius: 50%;
    height: 8px;
    width: 8px;

    &.is-ok {
      background: var(--s2s-color-success);
    }

    &.is-warn {
      background: var(--s2s-color-warning);
    }

    &.is-draining {
      background: var(--s2s-color-warning);
    }

    &.is-bad {
      background: var(--s2s-color-danger);
    }

    &.is-muted {
      background: var(--s2s-color-muted);
    }
  }

  &__lb {
    border: 1px solid var(--s2s-color-accent);
    border-radius: 3px;
    height: 10px;
    width: 14px;
  }

  &__flow {
    border-top: 2px dashed var(--s2s-color-accent);
    height: 0;
    width: 16px;
  }
}

.events-empty {
  color: var(--s2s-color-muted);
  font-size: 12px;
  margin: 0;
}

/* 原型 .tbl / .tag：最近事件表无表头，分类与结果用彩色标签。 */
.events-table {
  border-collapse: collapse;
  font-size: 12px;
  width: 100%;

  td {
    border-bottom: 1px solid var(--s2s-color-border);
    color: var(--s2s-color-text);
    padding: 9px 10px;
    vertical-align: middle;
  }

  tr:last-child td {
    border-bottom: 0;
  }
}

.tag {
  border: 1px solid var(--s2s-color-border);
  border-radius: 999px;
  display: inline-block;
  font-size: 11px;
  padding: 2px 8px;

  &--accent {
    border-color: var(--s2s-color-accent);
    color: var(--s2s-color-accent);
  }

  &--ok {
    border-color: var(--s2s-color-success);
    color: var(--s2s-color-success);
  }

  &--bad {
    border-color: var(--s2s-color-danger);
    color: var(--s2s-color-danger);
  }
}
</style>