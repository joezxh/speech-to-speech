import { api } from './client'
import type { Page } from '@/types/api'

/**
 * `/api/v1/session-records`：会话记录管理（一次通话 = 一条记录 + 逐行消息）。
 * 保存入口在通话结束（stop()）时由前端调用，带 JWT；行字段 camelCase。
 */
export interface SessionMessageRow {
  id: number
  ordinal: number
  role: 'user' | 'assistant' | 'tool'
  type: 'text' | 'audio'
  content: string
  interrupted: boolean
  /** ok | fail —— 用户行=STT 结果，助手行=TTS 结果。 */
  status: 'ok' | 'fail'
  /** 该条语音时长（毫秒）；无音频来源时为 0，展示层显示 —。 */
  durationMs: number
  createdAt: string
}

export interface SessionRecordRow {
  id: number
  userId: string
  title: string
  note: string
  pipelineSessionId: string
  instanceId: string
  node: string
  state: 'done' | 'failed'
  turns: number
  durationMs: number
  ttfaMs: number | null
  createdAt: string
  updatedAt: string
  /** 列表/详情行始终带（原型历史页列：消息数 + 转写摘录）。 */
  messageCount: number
  excerpt: string
  messages?: SessionMessageRow[]
}

export interface SessionRecordStats {
  total: number
  done: number
  failed: number
  turns: number
  avgDurationMs: number
  avgTtfaMs: number
}

export interface SessionRecordQuery {
  q?: string
  state?: string
  inst?: string
  range?: string
  from_date?: string
  to_date?: string
  page?: number
  pageSize?: number
}

export interface SessionSavePayload {
  title: string
  note?: string
  pipelineSessionId?: string
  instanceId?: string
  node?: string
  state?: 'done' | 'failed'
  turns?: number
  durationMs?: number
  ttfaMs?: number | null
  messages: Array<{
    role: string
    type: string
    content: string
    interrupted?: boolean
    status?: 'ok' | 'fail'
    durationMs?: number
  }>
}

export const listSessionRecords = (query: SessionRecordQuery = {}): Promise<Page<SessionRecordRow>> =>
  api.get<Page<SessionRecordRow>>('/session-records', { params: query })

/** 实例下拉数据源（历史页筛选卡）：非空 (instanceId, node) 对去重。 */
export const listSessionRecordInstances = (): Promise<Array<{ instanceId: string; node: string }>> =>
  api.get<Array<{ instanceId: string; node: string }>>('/session-records/instances')

/** LB 路由决策行（对话页「访问路由」tab）。 */
export interface RouteLogRow {
  at: string
  sessionKey: string
  ruleId: number | null
  matched: boolean
  instanceId: string | null
  stickyHit: boolean
  isCanary: boolean
  inputTokens: number
  outputTokens: number
}

export const listRouteLogs = (limit = 50): Promise<RouteLogRow[]> =>
  api.get<RouteLogRow[]>('/session-records/route-logs', { params: { limit } })

export const sessionRecordStats = (): Promise<SessionRecordStats> =>
  api.get<SessionRecordStats>('/session-records/stats')

export const getSessionRecord = (id: number): Promise<SessionRecordRow> =>
  api.get<SessionRecordRow>(`/session-records/${id}`)

export const saveSessionRecord = (payload: SessionSavePayload): Promise<SessionRecordRow> =>
  api.post<SessionRecordRow>('/session-records', payload)

export const updateSessionRecord = (
  id: number,
  patch: { title?: string; note?: string }
): Promise<SessionRecordRow> => api.patch<SessionRecordRow>(`/session-records/${id}`, patch)

export const deleteSessionRecord = (id: number): Promise<void> =>
  api.delete<undefined>(`/session-records/${id}`).then(() => undefined)

export const deleteSessionRecords = (ids: number[]): Promise<{ deleted: number }> =>
  api.post<{ deleted: number }>('/session-records/batch-delete', { ids })

export const updateSessionMessage = (
  recordId: number,
  messageId: number,
  content: string
): Promise<SessionMessageRow> =>
  api.patch<SessionMessageRow>(`/session-records/${recordId}/messages/${messageId}`, { content })

export const deleteSessionMessage = (recordId: number, messageId: number): Promise<void> =>
  api.delete<undefined>(`/session-records/${recordId}/messages/${messageId}`).then(() => undefined)

export const clearSessionMessages = (recordId: number): Promise<{ cleared: number }> =>
  api.post<{ cleared: number }>(`/session-records/${recordId}/messages/clear`)
