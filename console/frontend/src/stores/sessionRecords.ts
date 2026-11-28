import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  clearSessionMessages,
  deleteSessionMessage,
  deleteSessionRecord,
  deleteSessionRecords,
  getSessionRecord,
  listRouteLogs,
  listSessionRecordInstances,
  listSessionRecords,
  saveSessionRecord,
  sessionRecordStats,
  updateSessionMessage,
  updateSessionRecord,
  type RouteLogRow,
  type SessionMessageRow,
  type SessionRecordRow,
  type SessionRecordStats,
  type SessionSavePayload
} from '@/api/sessionRecords'
import type { TranscriptEntry } from '@/features/voice/types'

/** 列表筛选 + 分页状态；一次拉一页，详情单独取。 */
export interface SessionRecordFilters {
  q: string
  state: '' | 'done' | 'failed'
  inst: string
  range: '' | 'all' | 'today' | '24h' | '7d'
  from: string
  to: string
}

/**
 * 通话转写 → 保存载荷（纯函数，可测）。
 * - 失败行保留（对齐原型 stt/tts fail）：text 非空，或用户行带 audio（STT 失败=
 *   有原音无转写），或助手行带 latency（TTS 失败=无文本有延迟记录）；纯占位行丢弃。
 * - turns = 助手轮数（含失败行）；durationMs 由调用方给（会话起止墙钟差）；
 * - ttfaMs 取第一条助手延迟的 tts_ttfa_s（秒 → 毫秒，四舍五入）。
 */
export function toSavePayload(
  entries: readonly TranscriptEntry[],
  opts: { title?: string; pipelineSessionId?: string; instanceId?: string; node?: string; state?: 'done' | 'failed'; durationMs?: number } = {}
): SessionSavePayload {
  const usable = entries.filter(
    (entry) =>
      entry.text.trim() !== '' ||
      (entry.role === 'user' && entry.audio != null) ||
      (entry.role === 'assistant' && entry.latency != null)
  )
  const messages = usable.map((entry) => ({
    role: entry.role,
    type: entry.audio ? 'audio' : 'text',
    content: entry.text,
    interrupted: entry.interrupted === true,
    status: (saveStatusOf(entry) === 'ok' ? 'ok' : 'fail') as 'ok' | 'fail',
    durationMs: saveDurationMsOf(entry)
  }))
  const firstAssistant = usable.find((entry) => entry.role === 'assistant' && entry.latency)
  const ttfaS = firstAssistant?.latency?.tts_ttfa_s
  return {
    title: opts.title ?? '',
    pipelineSessionId: opts.pipelineSessionId ?? '',
    instanceId: opts.instanceId ?? '',
    node: opts.node ?? '',
    state: opts.state ?? 'done',
    turns: usable.filter((entry) => entry.role === 'assistant').length,
    durationMs: Math.max(0, Math.round(opts.durationMs ?? 0)),
    ttfaMs: typeof ttfaS === 'number' ? Math.round(ttfaS * 1000) : null,
    messages
  }
}

/** 消息级 status 推导：用户行=STT（空转写=fail），助手行=TTS（空文本或被打断=fail），tool 行恒 ok。 */
function saveStatusOf(entry: TranscriptEntry): 'ok' | 'fail' {
  if (entry.role === 'tool') return 'ok'
  if (entry.text.trim() === '') return 'fail'
  if (entry.role === 'assistant' && entry.interrupted === true) return 'fail'
  return 'ok'
}

/** 消息级时长：用户行取 audio.durationMs，助手行取 latency.e2e_s，tool 行 0。 */
function saveDurationMsOf(entry: TranscriptEntry): number {
  if (entry.role === 'user') return Math.max(0, Math.round(entry.audio?.durationMs ?? 0))
  if (entry.role === 'assistant' && entry.latency?.e2e_s) return Math.round(entry.latency.e2e_s * 1000)
  return 0
}

/** 实例下拉数据源行（历史页筛选卡）。 */
export interface SessionInstanceRow {
  instanceId: string
  node: string
}

export const useSessionRecordsStore = defineStore('sessionRecords', () => {
  const rows = ref<SessionRecordRow[]>([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(20)
  const filters = ref<SessionRecordFilters>({ q: '', state: '', inst: '', range: '', from: '', to: '' })
  const stats = ref<SessionRecordStats | null>(null)
  const loading = ref(false)
  const error = ref('')
  // 当前打开的详情（含 messages）；null = 关闭。
  const detail = ref<SessionRecordRow | null>(null)
  const detailLoading = ref(false)
  // 实例下拉数据源（历史页筛选卡）；失败静默为空。
  const instances = ref<SessionInstanceRow[]>([])

  const hasFilters = computed(() => {
    const f = filters.value
    return f.q !== '' || f.state !== '' || f.inst !== '' || f.range !== '' || f.from !== '' || f.to !== ''
  })

  async function load(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      const f = filters.value
      const data = await listSessionRecords({
        q: f.q || undefined,
        state: f.state || undefined,
        inst: f.inst || undefined,
        range: f.range || undefined,
        from_date: f.from || undefined,
        to_date: f.to || undefined,
        page: page.value,
        pageSize: pageSize.value
      })
      rows.value = data.list
      total.value = data.total
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : String(caught)
      rows.value = []
    } finally {
      loading.value = false
    }
  }

  async function loadInstances(): Promise<void> {
    try {
      instances.value = await listSessionRecordInstances()
    } catch {
      instances.value = []
    }
  }

  async function loadStats(): Promise<void> {
    try {
      stats.value = await sessionRecordStats()
    } catch {
      stats.value = null
    }
  }

  // 「访问路由」tab：最近 LB 路由决策（失败静默为空表）。
  const routeLogs = ref<RouteLogRow[]>([])
  async function loadRouteLogs(): Promise<void> {
    try {
      routeLogs.value = await listRouteLogs(50)
    } catch {
      routeLogs.value = []
    }
  }

  function resetAndLoad(): void {
    page.value = 1
    void load()
    void loadStats()
  }

  async function openDetail(id: number): Promise<SessionRecordRow | null> {
    detailLoading.value = true
    error.value = ''
    try {
      detail.value = await getSessionRecord(id)
      return detail.value
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : String(caught)
      return null
    } finally {
      detailLoading.value = false
    }
  }

  function closeDetail(): void {
    detail.value = null
  }

  /** 详情内消息就地更新（列表摘要不变）。 */
  function applyMessage(message: SessionMessageRow): void {
    const current = detail.value
    if (!current?.messages) return
    detail.value = {
      ...current,
      messages: current.messages.map((m) => (m.id === message.id ? message : m))
    }
  }

  async function patchRecord(id: number, patch: { title?: string; note?: string }): Promise<void> {
    const updated = await updateSessionRecord(id, patch)
    detail.value = detail.value && detail.value.id === id ? { ...detail.value, ...patch } : detail.value
    const row = rows.value.find((r) => r.id === id)
    if (row) {
      row.title = updated.title
      row.note = updated.note
      row.updatedAt = updated.updatedAt
    }
  }

  async function patchMessage(recordId: number, messageId: number, content: string): Promise<void> {
    const message = await updateSessionMessage(recordId, messageId, content)
    applyMessage(message)
  }

  async function removeMessage(recordId: number, messageId: number): Promise<void> {
    await deleteSessionMessage(recordId, messageId)
    const current = detail.value
    if (current?.messages) {
      detail.value = { ...current, messages: current.messages.filter((m) => m.id !== messageId) }
    }
    syncRowCount(recordId, -1)
  }

  async function clearMessages(recordId: number): Promise<void> {
    await clearSessionMessages(recordId)
    const current = detail.value
    if (current) detail.value = { ...current, messages: [] }
    const row = rows.value.find((r) => r.id === recordId)
    if (row) row.messageCount = 0
  }

  /** 消息增删后同步列表行的 messageCount（excerpt 交由调用方 load() 刷新）。 */
  function syncRowCount(recordId: number, delta: number): void {
    const row = rows.value.find((r) => r.id === recordId)
    if (row) row.messageCount = Math.max(0, row.messageCount + delta)
  }

  async function remove(id: number): Promise<void> {
    await deleteSessionRecord(id)
    rows.value = rows.value.filter((r) => r.id !== id)
    total.value = Math.max(0, total.value - 1)
    if (detail.value?.id === id) closeDetail()
    void loadStats()
  }

  async function removeMany(ids: number[]): Promise<void> {
    const { deleted } = await deleteSessionRecords(ids)
    const dropped = new Set(ids)
    rows.value = rows.value.filter((r) => !dropped.has(r.id))
    total.value = Math.max(0, total.value - deleted)
    if (detail.value && dropped.has(detail.value.id)) closeDetail()
    void loadStats()
    return
  }

  /** 通话结束自动保存；失败抛给调用方降级（不清空内存转写）。 */
  async function saveFromCall(payload: SessionSavePayload): Promise<SessionRecordRow> {
    const saved = await saveSessionRecord(payload)
    // 保存成功后刷新列表首屏，让右侧面板立刻看到新记录。
    page.value = 1
    void load()
    void loadStats()
    return saved
  }

  return {
    rows,
    total,
    page,
    pageSize,
    filters,
    stats,
    loading,
    error,
    detail,
    detailLoading,
    hasFilters,
    instances,
    routeLogs,
    load,
    loadStats,
    loadInstances,
    loadRouteLogs,
    resetAndLoad,
    openDetail,
    closeDetail,
    patchRecord,
    patchMessage,
    removeMessage,
    clearMessages,
    remove,
    removeMany,
    saveFromCall
  }
})
