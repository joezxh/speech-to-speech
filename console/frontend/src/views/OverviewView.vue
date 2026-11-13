<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { api, AppError } from '@/api/client'
import { clustersApi } from '@/api/clusters'
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
import { DASH, formatTime } from '@/utils/format'
import { hostOf } from '@/utils/host'
import { layoutTopo } from '@/utils/topoLayout'

/**
 * 集群总览（spec §5.2，原型 renderOverview/clusterRows/topoSVG）：
 * 五段=KPI 四卡 / 集群表 CRUD / 拓扑 / 图例+最近事件 / 全降级态。
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

// 机器层不是表：从当前集群实例的 base_url host 去重派生（spec §3）。
const topo = computed(() => {
  const hosts = new Map<string, boolean>()
  for (const row of instances.value) {
    const host = hostOf(row.base_url)
    hosts.set(host, (hosts.get(host) ?? false) || row.status === 'online')
  }
  return layoutTopo({
    cluster: clusterStore.current,
    machines: [...hosts].map(([host, online]) => ({ host, online })),
    instances: instances.value.map((row) => ({ id: row.instance_id, status: row.status, host: hostOf(row.base_url) }))
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

onMounted(async () => {
  await clusterStore.load()
  await loadClusterData()
})

watch(() => clusterStore.current, () => void loadClusterData())
watch(() => consoleStore.profile, () => void loadClusterData())

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
  await loadClusterData()
}

async function switchCluster(row: ClusterRow): Promise<void> {
  actionError.value = null
  const ok = await clusterStore.switchTo(row.name)
  if (!ok) actionError.value = clusterStore.error
  else await loadClusterData()
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
  } catch (caught) {
    actionError.value = caught instanceof AppError ? caught : new AppError('unknown', String(caught))
  }
  await loadClusterData()
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

const eventColumns = computed(() => [
  { title: t('overview.events.at'), key: 'at', width: 160 },
  { title: t('overview.events.actor'), dataIndex: 'actor', key: 'actor', width: 110 },
  { title: t('overview.events.action'), key: 'action', width: 140 },
  { title: t('overview.events.target'), dataIndex: 'profile', key: 'target', width: 130 },
  { title: t('overview.events.result'), key: 'result', width: 90 }
])
</script>

<template>
  <div class="overview">
    <ErrorBanner :error="instancesError" />
    <ErrorBanner :error="eventsError" />
    <ErrorBanner :error="clusterStore.error" />
    <ErrorBanner :error="actionError" />

    <section v-if="alerts.length" class="overview__alerts">
      <a-alert v-for="alert in alerts" :key="alert" type="warning" show-icon :message="alert" />
    </section>

    <!-- ① KPI 四卡：机器 / 实例 / 活跃会话 / 错误率(5m)，随当前集群联动。 -->
    <div class="overview__grid">
      <a-card v-for="kpi in kpis" :key="kpi.key" size="small" class="kpi">
        <p class="kpi__label">{{ t(`overview.kpi.${kpi.key === 'instances' ? 'pipelineInstances' : kpi.key === 'sessions' ? 'activeSessions' : kpi.key}`) }}</p>
        <p class="kpi__value" :class="`is-${kpi.tone}`" :data-metric="`kpi.${kpi.key}`">{{ kpi.primary }}</p>
        <p v-if="kpi.sub" class="kpi__sub">{{ kpi.sub }}</p>
      </a-card>
    </div>

    <!-- ② 集群表：当前行带「当前」标签且不摆切换按钮（场景 2）。 -->
    <a-card size="small" :title="t('shell.cluster')">
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
            <a-badge :status="record.healthy ? 'success' : 'error'" :text="t(record.healthy ? 'overview.status.healthy' : 'overview.status.unhealthy')" />
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
    <a-card size="small" :title="t('overview.topology.title')">
      <TopoChart :layout="topo" @machine="goMachine" />
    </a-card>

    <div class="overview__split">
      <!-- ④a 图例 -->
      <a-card size="small" :title="t('overview.legend.title')">
        <ul class="legend">
          <li><span class="legend__dot is-ok" />{{ t('overview.legend.online') }}</li>
          <li><span class="legend__dot is-warn" />{{ t('overview.legend.degraded') }}</li>
          <li><span class="legend__dot is-bad" />{{ t('overview.legend.offline') }}</li>
          <li><span class="legend__dot is-muted" />{{ t('overview.legend.muted') }}</li>
        </ul>
      </a-card>

      <!-- ④b 最近事件：audit action 代码态不翻译（spec §8.4 口径），结果列翻译。 -->
      <a-card size="small" :title="t('overview.events.title')">
        <a-table
          v-if="events.length"
          size="small"
          row-key="auditId"
          :pagination="false"
          :data-source="events"
          :columns="eventColumns"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'at'"><span class="mono">{{ formatTime(record.at) }}</span></template>
            <template v-else-if="column.key === 'action'"><span class="mono">{{ record.action }}</span></template>
            <template v-else-if="column.key === 'result'">
              <a-tag :color="record.result === 'ok' ? 'green' : 'red'">
                {{ t(record.result === 'ok' ? 'overview.events.ok' : 'overview.events.error') }}<template v-if="record.result === 'error' && record.errorCode"> · {{ record.errorCode }}</template>
              </a-tag>
            </template>
          </template>
        </a-table>
        <p v-else class="events-empty">{{ t('overview.events.empty') }}</p>
      </a-card>
    </div>

    <ClusterFormModal v-model:open="formOpen" :cluster="formCluster" @saved="onSaved" />
    <ConfirmDialog :open="confirmOpen" :title="confirmTitle" :content="confirmContent" @answer="answerConfirm" />
  </div>
</template>

<style scoped lang="less">
.overview {
  display: flex;
  flex-direction: column;
  gap: 16px;

  &__alerts {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  &__grid {
    display: grid;
    gap: 12px;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  }

  &__split {
    display: grid;
    gap: 12px;
    grid-template-columns: 260px 1fr;
  }
}

.kpi {
  &__label {
    color: var(--s2s-color-muted);
    font-size: 12px;
    margin: 0 0 4px;
  }

  &__value {
    color: var(--s2s-color-text);
    font-family: var(--s2s-font-mono);
    font-size: 18px;
    margin: 0;

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

    &.is-bad {
      background: var(--s2s-color-danger);
    }

    &.is-muted {
      background: var(--s2s-color-muted);
    }
  }
}

.events-empty {
  color: var(--s2s-color-muted);
  font-size: 12px;
  margin: 0;
}
</style>