<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { AppError } from '@/api/client'
import { getInstances, postInstanceAction } from '@/api/instances'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ErrorBanner from '@/components/ErrorBanner.vue'
import InstanceCard from '@/components/InstanceCard.vue'
import LogAnalysisCard from '@/components/LogAnalysisCard.vue'
import LogPanel from '@/components/LogPanel.vue'
import RuntimeGrid from '@/components/RuntimeGrid.vue'
import TurnLatencyPanel from '@/components/TurnLatencyPanel.vue'
import { useConfirm } from '@/composables/useConfirm'
import { usePolling } from '@/composables/usePolling'
import { useAuthStore } from '@/stores/auth'
import { useConsoleStore } from '@/stores/console'
import { useLogsStore } from '@/stores/logs'
import { useRuntimeStore } from '@/stores/runtime'
import type { InstanceRow, InstanceSnapshot } from '@/types/api'
import { capacityPercent, statusColor } from '@/utils/instances-view'

const consoleStore = useConsoleStore()
const runtime = useRuntimeStore()
const logs = useLogsStore()
const auth = useAuthStore()
const router = useRouter()
const {
  open: confirmOpen,
  title: confirmTitle,
  content: confirmContent,
  ask: askConfirm,
  answer: answerConfirm
} = useConfirm()

const snapshot = ref<InstanceSnapshot | null>(null)
const error = ref('')
const actionError = ref<AppError | null>(null)

// 机器级状态的中文标签：与 unit 级 (idle/active/…) 无关，来自 registry 巡检推导。
const STATUS_LABEL: Record<string, string> = {
  unknown: '未探测',
  online: '在线',
  degraded: '降级',
  offline: '离线',
  draining: '摘除中'
}
const statusLabel = (status: string) => STATUS_LABEL[status] ?? status

// badge 只吃 antd 的四个状态色，把 statusColor 的橙/蓝并到 processing/warning。
const BADGE_STATUS: Record<string, 'success' | 'warning' | 'error' | 'processing' | 'default'> = {
  green: 'success',
  orange: 'warning',
  red: 'error',
  blue: 'processing',
  default: 'default'
}
const badgeStatus = (status: string) => BADGE_STATUS[statusColor(status)] ?? 'default'

// drain/undrain/probe 需要 operator 及以上；后端 require_operator 兜底，前端只是少摆按钮。
const canOperate = computed(() => auth.user?.role === 'operator' || auth.user?.role === 'admin')
const instances = computed(() => snapshot.value?.instances ?? [])
const summary = computed(() => snapshot.value?.summary ?? null)

async function poll(): Promise<void> {
  try {
    snapshot.value = await getInstances(consoleStore.profile)
    error.value = ''
  } catch (caught) {
    snapshot.value = null
    error.value = caught instanceof AppError ? caught.message : '实例状态不可读'
  }
}

const { active, start: startInstances, stop: stopInstances, refresh } = usePolling(poll, 5000)

/**
 * 两个端点各有各的节奏，但只有一个「暂停」按钮：停一半会让徽标说谎。
 * `/instances` 说容器，`/runtime/models` 说模型，一起刷新一起停。
 */
function startAll(): void {
  startInstances()
  runtime.startPolling(consoleStore.profile)
}

function stopAll(): void {
  stopInstances()
  runtime.stopPolling()
}

watch(() => consoleStore.profile, startAll, { immediate: true })

/**
 * §3.9.1 第 4 条：页签切走就停。console 与 pipeline 同容器，一个被遗忘的
 * 后台标签页每 5s 跑一次 `nvidia-smi` 加一次日志尾读，是这个面板唯一可能
 * 伤到语音的地方。
 */
function onVisibility(): void {
  if (document.hidden) stopAll()
  else startAll()
}

document.addEventListener('visibilitychange', onVisibility)

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', onVisibility)
  stopAll()
})

async function runAction(row: InstanceRow, action: 'drain' | 'undrain' | 'probe'): Promise<void> {
  if (action !== 'probe') {
    const confirmed = await askConfirm({
      title: action === 'drain' ? `摘除 ${row.instance_id}` : `恢复 ${row.instance_id}`,
      content:
        action === 'drain'
          ? '摘除后分配器不再把新会话派给这台，已连接的会话不受影响。'
          : '恢复后这台重新参与分配（仍需探测为在线/降级才会被选中）。'
    })
    if (!confirmed) return
  }
  actionError.value = null
  try {
    await postInstanceAction(row.instance_id, action)
    await refresh()
  } catch (caught) {
    actionError.value = caught instanceof AppError ? caught : new AppError('unknown', '操作失败')
  }
}

// 「趋势」独立成页：只跳转到负载均衡菜单下的趋势页并带上这台实例。
function goTrends(row: InstanceRow): void {
  void router.push({ name: 'instance-trends', query: { id: row.instance_id } })
}
</script>

<template>
  <div class="instances">
    <div class="instances__bar">
      <a-badge :status="active ? 'processing' : 'default'" :text="active ? '每 5s 刷新' : '已暂停'" />
      <a-button size="small" @click="active ? stopAll() : startAll()">
        {{ active ? '暂停' : '继续' }}
      </a-button>
    </div>

    <RuntimeGrid :snapshot="runtime.snapshot" :loading="runtime.loading" :error="runtime.error" />

    <ErrorBanner :error="actionError" />

    <!--
      注册表非空才有多实例视图；单实例 legacy 直连时 snapshot 不带 summary/instances，
      下面的卡片/表格/趋势整段跳过，InstanceCard 继续说容器与会话池。
    -->
    <section v-if="summary" class="instances__summary">
      <div class="instances__grid">
        <div class="instances__cell">
          <span class="instances__k">实例总数</span>
          <span class="instances__v">{{ summary.instances_total }}</span>
        </div>
        <div class="instances__cell">
          <span class="instances__k">在线 · 降级 · 离线 · 摘除</span>
          <span class="instances__v">
            {{ summary.online }} / {{ summary.degraded }} / {{ summary.offline }} /
            {{ summary.draining }}
          </span>
        </div>
        <div class="instances__cell">
          <span class="instances__k">槽位（总/占/闲）</span>
          <span class="instances__v">
            {{ summary.slots_total }} / {{ summary.slots_in_use }} / {{ summary.slots_free }}
          </span>
        </div>
        <div class="instances__cell">
          <span class="instances__k">待领取授权</span>
          <span class="instances__v">{{ summary.pending_grants }}</span>
        </div>
      </div>
    </section>

    <a-table
      v-if="instances.length"
      class="instances__table"
      size="small"
      row-key="instance_id"
      :pagination="false"
      :data-source="instances"
      :scroll="{ x: 900 }"
      :columns="[
        { title: '实例', key: 'instance_id', width: 180 },
        { title: '状态', key: 'status', width: 110 },
        { title: '容量', key: 'capacity', width: 140 },
        { title: '占用/空闲', key: 'slots', width: 110 },
        { title: '权重', dataIndex: 'weight', key: 'weight', width: 70 },
        { title: '探测(ms)', key: 'probe', width: 110 },
        { title: '操作', key: 'actions', width: 210 }
      ]"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'instance_id'">
          <a @click="goTrends(record)">{{ record.instance_id }}</a>
          <div class="instances__url">{{ record.base_url }}</div>
        </template>
        <template v-else-if="column.key === 'status'">
          <a-badge :status="badgeStatus(record.status)" :text="statusLabel(record.status)" />
          <div v-if="record.declared_mismatch" class="instances__warn">声明容量与实际不符</div>
          <div v-else-if="record.last_error" class="instances__err" :title="record.last_error">
            {{ record.last_error }}
          </div>
        </template>
        <template v-else-if="column.key === 'capacity'">
          <a-progress
            :percent="capacityPercent(record)"
            :stroke-color="statusColor(record.status)"
            size="small"
            :format="() => `${record.size ?? '—'} 槽`"
          />
        </template>
        <template v-else-if="column.key === 'slots'">
          {{ record.in_use ?? '—' }} / {{ record.free ?? '—' }}
          <span v-if="record.stuck"> · 卡 {{ record.stuck }}</span>
        </template>
        <template v-else-if="column.key === 'probe'">
          {{ record.probe_ms ?? '—' }}
          <span v-if="record.p95_probe_ms != null" class="instances__p95">
            p95 {{ record.p95_probe_ms }}
          </span>
        </template>
        <template v-else-if="column.key === 'actions'">
          <a-space>
            <a-button size="small" @click="goTrends(record)">趋势</a-button>
            <template v-if="canOperate">
              <a-button
                v-if="!record.drain_requested"
                size="small"
                @click="runAction(record, 'drain')"
              >
                摘除
              </a-button>
              <a-button v-else size="small" @click="runAction(record, 'undrain')">恢复</a-button>
              <a-button size="small" @click="runAction(record, 'probe')">探测</a-button>
            </template>
          </a-space>
        </template>
      </template>
    </a-table>

    <InstanceCard :snapshot="snapshot" :error="error" />

    <!--
      同一列、固定顺序：轮次面板先说「整体多慢」，日志面板给细文，归纳卡给结论。
      归纳结果必须挨着它基于的那个日志窗口；两块的时间窗各自独立、不联动。
    -->
    <TurnLatencyPanel />
    <LogPanel
      :live="logs.live"
      @follow="logs.setLive($event)"
      @refresh="logs.reload()"
      @analyze="logs.analyze()"
    />
    <LogAnalysisCard
      :analysis="logs.analysis"
      :pending="logs.pending"
      :error="logs.analysisError"
      @retry="logs.analyze()"
    />

    <ConfirmDialog
      :open="confirmOpen"
      :title="confirmTitle"
      :content="confirmContent"
      danger
      @answer="answerConfirm"
    />
  </div>
</template>

<style scoped lang="less">
.instances {
  display: flex;
  flex-direction: column;
  gap: 12px;

  &__bar {
    align-items: center;
    display: flex;
    gap: 12px;
  }

  &__summary {
    background: #171b26;
    border: 1px solid #1c2130;
    border-radius: 8px;
    padding: 10px 12px;
  }

  &__grid {
    display: grid;
    gap: 8px 16px;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  }

  &__cell {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  &__k {
    color: #8b93a7;
    font-size: 12px;
  }

  &__v {
    font-size: 13px;
  }

  &__url {
    color: #8b93a7;
    font-size: 12px;
  }

  &__warn {
    color: #f59e0b;
    font-size: 12px;
  }

  &__err {
    color: #ff6a75;
    font-size: 12px;
    max-width: 180px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__p95 {
    color: #8b93a7;
    font-size: 12px;
    margin-left: 6px;
  }
}
</style>
