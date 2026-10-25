import { defineStore } from 'pinia'
import { ref } from 'vue'

import { AppError } from '@/api/client'
import { analyzeLogs, fetchLogs } from '@/api/logs'
import type { LogAnalysis, LogLine, LogScanned, LogSource } from '@/types/logs'

/**
 * A.15 的「尾部跟随」就是每 2s 拉一次 `after=nextCursor`——日志本来就是轮询
 * 语义，而 console 只有一个 worker，一条 SSE 长连接会把它钉住（§3.1）。
 */
const POLL_MS = 2000
const WINDOW_MINUTES = 15
const LIMIT = 500
/** 跟随会一直追加；超过这个量就丢最早的，页面不会越滚越慢。 */
const MAX_LINES = 2000

export const useLogsStore = defineStore('logs', () => {
  const lines = ref<LogLine[]>([])
  const nextCursor = ref('')
  /** 服务端说「文件轮转过了」：旧游标作废，本次是整页重读。 */
  const reset = ref(false)
  const truncated = ref(false)
  const scanned = ref<LogScanned>({ files: 0, bytes: 0 })
  const sources = ref<LogSource[]>([])
  const loading = ref(false)
  const error = ref('')

  const live = ref(false)
  const filters = ref({
    process: ['console', 'pipeline'] as string[],
    level: [] as string[],
    from: '',
    to: '',
    q: ''
  })

  const analysis = ref<LogAnalysis | null>(null)
  const pending = ref(false)
  const analysisError = ref('')

  let timer: number | undefined
  let inFlight = false

  /** 缺省最近 15 分钟：A.15 的默认窗口由客户端给出，服务端不猜。 */
  function isoWindow(): { from: string; to: string } {
    if (filters.value.from && filters.value.to) {
      return { from: filters.value.from, to: filters.value.to }
    }
    const end = new Date()
    const start = new Date(end.getTime() - WINDOW_MINUTES * 60_000)
    return { from: start.toISOString(), to: end.toISOString() }
  }

  async function load(resetPage = false): Promise<void> {
    if (inFlight) return
    inFlight = true
    loading.value = true
    try {
      const page = await fetchLogs({
        ...isoWindow(),
        process: [...filters.value.process],
        level: [...filters.value.level],
        q: filters.value.q,
        after: resetPage ? '' : nextCursor.value,
        limit: LIMIT
      })
      nextCursor.value = page.nextCursor
      reset.value = page.reset
      truncated.value = page.truncated
      scanned.value = page.scanned
      sources.value = page.sources
      const replaced = resetPage || page.reset || lines.value.length === 0
      lines.value = replaced ? page.lines : [...lines.value, ...page.lines]
      if (lines.value.length > MAX_LINES) lines.value = lines.value.slice(-MAX_LINES)
      error.value = ''
    } catch (caught) {
      // 一次读取失败不清空已加载的行：这正是需要看历史的时候。
      error.value = caught instanceof AppError ? caught.message : '日志不可读'
    } finally {
      loading.value = false
      inFlight = false
    }
  }

  function clearTimer(): void {
    if (timer !== undefined) window.clearInterval(timer)
    timer = undefined
  }

  function follow(): void {
    clearTimer()
    live.value = true
    void load(false)
    timer = window.setInterval(() => void load(false), POLL_MS)
  }

  function stop(): void {
    clearTimer()
    live.value = false
  }

  function setLive(value: boolean): void {
    if (value) follow()
    else stop()
  }

  /** 换筛选条件 = 从头读一页，否则游标会接着旧条件的位置读。 */
  async function reload(): Promise<void> {
    nextCursor.value = ''
    lines.value = []
    await load(true)
  }

  async function analyze(): Promise<void> {
    if (pending.value) return
    pending.value = true
    analysisError.value = ''
    try {
      analysis.value = await analyzeLogs({
        ...isoWindow(),
        process: [...filters.value.process],
        level: [...filters.value.level],
        q: filters.value.q,
        maxLines: 800,
        includeTurnLatency: true
      })
    } catch (caught) {
      // A.16：失败只在结果卡里说，不动左边的日志区。
      analysisError.value = caught instanceof AppError ? caught.message : '日志归纳失败'
    } finally {
      pending.value = false
    }
  }

  return {
    lines,
    nextCursor,
    reset,
    truncated,
    scanned,
    sources,
    loading,
    error,
    live,
    filters,
    analysis,
    pending,
    analysisError,
    load,
    reload,
    follow,
    stop,
    setLive,
    analyze
  }
})
