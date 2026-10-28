<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import { AppError } from '@/api/client'
import { getDemoConfig } from '@/api/demo'
import {
  deleteVoiceSession,
  fetchVoiceTurnAudio,
  getVoiceSession,
  listVoiceSessions,
  type VoiceSessionRow,
  type VoiceTurnRow
} from '@/api/voiceSessions'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ErrorBanner from '@/components/ErrorBanner.vue'
import { useConfirm } from '@/composables/useConfirm'
import type { SessionRecordConfig } from '@/features/voice/types'
import { useAuthStore } from '@/stores/auth'
import { DASH, formatBytes, formatDuration, formatTime } from '@/utils/format'

const auth = useAuthStore()
const { open: confirmOpen, title: confirmTitle, content: confirmContent, ask, answer } = useConfirm()

/** 与后端 `Query(20, ge=1, le=100)` 的默认值对齐；游标是 keyset，不能跳页。 */
const PAGE_SIZE = 20

const STATUS_LABELS: Record<string, string> = { recording: '录制中', closed: '已结束' }
const ROLE_LABELS: Record<string, string> = { user: '用户', assistant: '助手', tool: '工具' }
const AUDIO_STATE_LABELS: Record<string, string> = {
  none: '未保存',
  available: '已保存',
  deleted: '文件已清理'
}

const gate = ref<SessionRecordConfig | null>(null)
const rows = ref<VoiceSessionRow[]>([])
const cursor = ref('')
const statusFilter = ref('')
const loading = ref(false)
const loadingMore = ref(false)
const error = ref<AppError | null>(null)
const notice = ref('')

const detailOpen = ref(false)
const detailLoading = ref(false)
const detailError = ref<AppError | null>(null)
const session = ref<VoiceSessionRow | null>(null)
const turns = ref<VoiceTurnRow[]>([])
const total = ref(0)

/**
 * turn id → 已下载的 Object URL。一条会话可能有几十段音频，而每段最大 8 MiB，
 * 所以点开哪段才取哪段，而不是一次拉完整会话的音频。
 */
const urls = reactive<Record<string, string>>({})
const audioLoading = reactive<Record<string, boolean>>({})
const audioFailed = reactive<Record<string, boolean>>({})

const filterOptions = [
  { value: '', label: '全部状态' },
  { value: 'recording', label: STATUS_LABELS.recording },
  { value: 'closed', label: STATUS_LABELS.closed }
]

const columns = [
  { title: '标题', dataIndex: 'title', key: 'title' },
  { title: '状态', dataIndex: 'status', key: 'status', width: 100 },
  { title: '轮次', dataIndex: 'turnCount', key: 'turnCount', width: 80 },
  { title: '音频', dataIndex: 'audioBytes', key: 'audioBytes', width: 110 },
  { title: '登记人', dataIndex: 'createdBy', key: 'createdBy', width: 120 },
  { title: '开始时间', dataIndex: 'startedAt', key: 'startedAt', width: 170 },
  { title: '到期', dataIndex: 'expiresAt', key: 'expiresAt', width: 170 },
  { title: '操作', key: 'actions', width: 150 }
]

const hasMore = computed(() => cursor.value !== '')
const audioTurns = computed(() => turns.value.filter((turn) => turn.audioUrl).length)

async function reload(): Promise<void> {
  loading.value = true
  cursor.value = ''
  try {
    const page = await listVoiceSessions({ limit: PAGE_SIZE, status: statusFilter.value })
    rows.value = page.list
    cursor.value = page.nextCursor
  } catch (caught) {
    error.value = caught instanceof AppError ? caught : new AppError('unknown', '归档列表加载失败')
  } finally {
    loading.value = false
  }
}

/** 追加下一页：游标是「最后一条的 (created_at, id)」，新写入的行不会挤掉已看过的。 */
async function loadMore(): Promise<void> {
  if (!cursor.value) return
  loadingMore.value = true
  try {
    const page = await listVoiceSessions({
      limit: PAGE_SIZE,
      cursor: cursor.value,
      status: statusFilter.value
    })
    rows.value = [...rows.value, ...page.list]
    cursor.value = page.nextCursor
  } catch (caught) {
    error.value = caught instanceof AppError ? caught : new AppError('unknown', '加载下一页失败')
  } finally {
    loadingMore.value = false
  }
}

async function openDetail(row: VoiceSessionRow): Promise<void> {
  notice.value = ''
  detailError.value = null
  session.value = row
  turns.value = []
  total.value = 0
  detailOpen.value = true
  detailLoading.value = true
  try {
    const detail = await getVoiceSession(row.id)
    session.value = detail.session
    turns.value = detail.turns
    total.value = detail.total
  } catch (caught) {
    detailError.value = caught instanceof AppError ? caught : new AppError('unknown', '会话详情加载失败')
  } finally {
    detailLoading.value = false
  }
}

async function loadAudio(turn: VoiceTurnRow): Promise<void> {
  if (!turn.audioUrl || urls[turn.id]) return
  audioLoading[turn.id] = true
  audioFailed[turn.id] = false
  try {
    urls[turn.id] = URL.createObjectURL(await fetchVoiceTurnAudio(turn.audioUrl))
  } catch (caught) {
    // `audio_missing` 是合法结局：保留期扫描会把文件删掉并把行降级成 `deleted`。
    audioFailed[turn.id] = true
    if (caught instanceof AppError && caught.code === 'audio_missing') {
      turn.audioState = 'deleted'
    }
  } finally {
    audioLoading[turn.id] = false
  }
}

/**
 * 归档属于录音的那个人（后端 `delete_session` 只放过本人或 admin）。
 * 这里提前把按钮关掉，免得点下去才收到 403。
 */
const canDelete = computed(() => (row: VoiceSessionRow): boolean => auth.isAdmin || row.createdBy === auth.user?.username)

async function remove(row: VoiceSessionRow): Promise<void> {
  notice.value = ''
  error.value = null
  const label = row.title || row.pipelineSessionId || row.id
  const confirmed = await ask({
    title: '删除归档',
    content: `将删除「${label}」的转写与全部音频文件，物理删除、不可恢复；到期前它也不会被保留期扫描动过。`
  })
  if (!confirmed) return
  try {
    await deleteVoiceSession(row.id)
    notice.value = `已删除「${label}」`
    if (session.value?.id === row.id) closeDetail()
    await reload()
  } catch (caught) {
    error.value = caught instanceof AppError ? caught : new AppError('unknown', '删除失败')
  }
}

function closeDetail(): void {
  detailOpen.value = false
  for (const [turnId, url] of Object.entries(urls)) {
    URL.revokeObjectURL(url)
    delete urls[turnId]
    delete audioLoading[turnId]
    delete audioFailed[turnId]
  }
}

onMounted(reload)

onBeforeUnmount(() => {
  for (const url of Object.values(urls)) URL.revokeObjectURL(url)
})

// 闸门只影响「新通话会不会写进来」：GET 列表/详情/音频与删除都不受它限制，
// 所以关掉录音时这一页仍然要能用，文案也就只说这一点。
void getDemoConfig()
  .then((config) => {
    gate.value = config.sessionRecord
  })
  .catch(() => undefined)
</script>

<template>
  <div class="recordings">
    <a-alert v-if="gate && !gate.enabled" type="warning" show-icon message="录音闸门已关闭：新的通话不会写入归档">
      <template #description>
        这里列出的是此前已经落库的会话，仍可回看与删除。要恢复写入，把
        <code>SESSION_RECORD_ENABLED</code> 设为 <code>true</code> 并重启控制器。
      </template>
    </a-alert>
    <a-alert v-else-if="gate" type="info">
      <template #message>
        转写与双向音频保存在控制台库和 <code>SESSION_DATA_DIR</code>，默认保留
        {{ gate.retentionDays || DASH }} 天
      </template>
      <template #description>
        <ul class="recordings__rules">
          <li>只有对话页勾了「录制」的通话才会写入；未勾选时音频与转写都不出浏览器。</li>
          <li>保留期从会话结束（或最后一轮）起算，到期后连文件带行一起物理删除。</li>
          <li>
            单轮音频超过 {{ formatBytes(gate.maxAudioBytes) }} 或
            {{ gate.maxAudioSeconds || DASH }} 秒时浏览器会放弃这段音频，只留转写。
          </li>
          <li>删除是物理删除：归档是别人的声音，只有本人或管理员能动。</li>
        </ul>
      </template>
    </a-alert>

    <a-alert v-if="notice" type="success" show-icon :message="notice" />
    <ErrorBanner :error="error" />

    <div class="recordings__bar">
      <a-select
        v-model:value="statusFilter"
        :options="filterOptions"
        style="width: 160px"
        @change="reload"
      />
      <a-button size="small" :loading="loading" @click="reload">刷新</a-button>
    </div>

    <a-table
      size="small"
      :data-source="rows"
      :loading="loading"
      :pagination="false"
      :columns="columns"
      :row-key="(row: VoiceSessionRow) => row.id"
      :custom-row="(row: VoiceSessionRow) => ({ onClick: () => openDetail(row) })"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'title'">
          <span>{{ record.title || record.pipelineSessionId || DASH }}</span>
          <a-tag v-if="record.clientKind" class="recordings__tag">{{ record.clientKind }}</a-tag>
        </template>
        <template v-else-if="column.key === 'status'">
          <a-tag :color="record.status === 'closed' ? 'default' : 'processing'">
            {{ STATUS_LABELS[record.status] ?? record.status }}
          </a-tag>
        </template>
        <template v-else-if="column.key === 'turnCount'">{{ record.turnCount }}</template>
        <template v-else-if="column.key === 'audioBytes'">{{ formatBytes(record.audioBytes) }}</template>
        <template v-else-if="column.key === 'startedAt'">{{ formatTime(record.startedAt) }}</template>
        <template v-else-if="column.key === 'expiresAt'">{{ formatTime(record.expiresAt) }}</template>
        <template v-else-if="column.key === 'actions'">
          <a-button type="link" size="small" @click.stop="openDetail(record)">查看</a-button>
          <a-button v-if="canDelete(record)" type="link" size="small" danger @click.stop="remove(record)">
            删除
          </a-button>
        </template>
      </template>
    </a-table>

    <div v-if="hasMore" class="recordings__more">
      <a-button :loading="loadingMore" @click="loadMore">加载更多</a-button>
    </div>
    <a-empty v-if="!loading && rows.length === 0" description="还没有归档：在对话页勾上「录制」跑一通电话" />

    <a-drawer
      :open="detailOpen"
      placement="right"
      :width="560"
      :body-style="{ padding: '12px 16px' }"
      @close="closeDetail"
    >
      <template #title>
        {{ session?.title || session?.pipelineSessionId || session?.id || DASH }}
      </template>

      <a-alert v-if="detailError" type="error" show-icon :message="detailError.message" />
      <a-spin :spinning="detailLoading">
        <p v-if="session" class="recordings__meta">
          {{ STATUS_LABELS[session.status] ?? session.status }} · {{ total }} 轮 ·
          {{ formatBytes(session.audioBytes) }} · 登记人 {{ session.createdBy || DASH }} ·
          到期 {{ formatTime(session.expiresAt) }}
        </p>

        <a-empty v-if="!detailLoading && turns.length === 0" description="这条会话还没有落任何轮次" />

        <ol v-else class="recordings__turns">
          <li v-for="turn in turns" :key="turn.id" class="recordings__turn">
            <div class="recordings__turn-head">
              <a-tag :color="turn.role === 'user' ? 'blue' : turn.role === 'assistant' ? 'green' : 'purple'">
                {{ ROLE_LABELS[turn.role] ?? turn.role }}
              </a-tag>
              <span v-if="turn.speakerLabel" class="recordings__speaker">{{ turn.speakerLabel }}</span>
              <span class="recordings__muted">#{{ turn.ordinal }}</span>
              <span class="recordings__muted">{{ formatTime(turn.startedAt) }}</span>
              <span v-if="turn.rev > 0" class="recordings__muted">rev {{ turn.rev }}</span>
              <span v-if="turn.audioTruncated" class="recordings__muted">已截断开头</span>
            </div>

            <p class="recordings__text">{{ turn.text || DASH }}</p>

            <div class="recordings__audio">
              <audio v-if="urls[turn.id]" :src="urls[turn.id]" controls preload="auto" />
              <template v-else-if="turn.audioUrl">
                <a-button
                  size="small"
                  :loading="audioLoading[turn.id]"
                  :disabled="audioFailed[turn.id]"
                  @click="loadAudio(turn)"
                >
                  {{ audioFailed[turn.id] ? '取不到音频' : `播放 ${formatBytes(turn.audioBytes)} · ${formatDuration(turn.audioSeconds)}` }}
                </a-button>
              </template>
              <span v-else class="recordings__muted">{{ AUDIO_STATE_LABELS[turn.audioState] ?? turn.audioState }}</span>
            </div>
          </li>
        </ol>

        <p v-if="turns.length > 0 && audioTurns > 0" class="recordings__hint">
          共 {{ audioTurns }} 段音频，点「播放」按需取流；带 bearer token 的请求走不了
          <code>&lt;audio src&gt;</code> 直链。
        </p>
      </a-spin>
    </a-drawer>

    <ConfirmDialog :open="confirmOpen" :title="confirmTitle" :content="confirmContent" danger @answer="answer" />
  </div>
</template>

<style scoped lang="less">
.recordings {
  display: flex;
  flex-direction: column;
  gap: 12px;

  &__rules {
    margin: 0;
    padding-left: 18px;
  }

  &__bar {
    align-items: center;
    display: flex;
    gap: 8px;
  }

  &__more {
    display: flex;
    justify-content: center;
  }

  &__tag {
    margin-left: 6px;
  }

  &__meta {
    color: #6f7891;
    font-size: 12px;
    margin: 0 0 12px;
  }

  &__turns {
    display: flex;
    flex-direction: column;
    gap: 10px;
    list-style: none;
    margin: 0;
    padding: 0;
  }

  &__turn {
    background: #101728;
    border-radius: 8px;
    padding: 10px 12px;
  }

  &__turn-head {
    align-items: center;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 6px;
  }

  &__speaker {
    font-weight: 600;
  }

  &__muted {
    color: #6f7891;
    font-size: 12px;
  }

  &__text {
    margin: 0 0 8px;
    white-space: pre-wrap;
  }

  &__audio {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;

    audio {
      width: 100%;
    }
  }

  &__hint {
    color: #6f7891;
    font-size: 12px;
    margin: 12px 0 0;
  }
}
</style>
