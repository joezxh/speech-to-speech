import { api } from './client'

import type { Page } from '@/types/api'

export type TargetType = 'java' | 'python'
export type AuthType = 'none' | 'bearer' | 'header_token'
export type EventType = 'transcript' | 'segment_attributed' | 'session_end'

/** 字段名与后端 callback_service._to_out 逐字一致（camelCase）。 */
export interface CallbackTargetFilters {
  speakers?: string[]
  min_text_len?: number
}

export interface CallbackTarget {
  id: number
  name: string
  targetType: TargetType
  baseUrl: string
  authType: AuthType
  authHeaderName: string | null
  authToken: string
  extraHeaders: Record<string, string>
  timeoutMs: number
  retryMaxAttempts: number
  retryBackoffMs: number
  events: EventType[]
  filters: CallbackTargetFilters | null
  enabled: boolean
}

/** 字段名与后端 callback_service.send_test_event 逐字一致。 */
export interface CallbackTestResult {
  ok: boolean
  httpStatus: number | null
  durationMs: number
  error: string
}

/** 字段名与后端 callback_service._log_out 逐字一致（camelCase）。 */
export interface DeliveryLog {
  id: number
  targetId: number | null
  eventType: string
  triggeredAt: string | null
  requestUrl: string
  requestPayload: string
  attempt: number
  httpStatus: number | null
  responseSnippet: string
  durationMs: number
  status: 'success' | 'failed' | 'retrying'
  error: string
}

export const listTargets = (page: number, pageSize: number): Promise<Page<CallbackTarget>> =>
  api.get<Page<CallbackTarget>>('/callbacks/targets', { params: { page, pageSize } })

export const createTarget = (payload: Partial<CallbackTarget>): Promise<CallbackTarget> =>
  api.post<CallbackTarget>('/callbacks/targets', payload)

export const updateTarget = (id: number, payload: Partial<CallbackTarget>): Promise<CallbackTarget> =>
  api.put<CallbackTarget>(`/callbacks/targets/${id}`, payload)

export const deleteTarget = (id: number): Promise<void> => api.delete(`/callbacks/targets/${id}`)

export const batchTargets = (
  ids: number[],
  action: 'enable' | 'disable' | 'delete'
): Promise<{ updated?: number; deleted?: number }> =>
  api.post<{ updated?: number; deleted?: number }>('/callbacks/targets/batch', { ids, action })

export const testTarget = (id: number): Promise<CallbackTestResult> =>
  api.post<CallbackTestResult>(`/callbacks/targets/${id}/test`)

export const listLogs = (params: {
  page: number
  pageSize: number
  status?: string
  targetId?: number
}): Promise<Page<DeliveryLog>> => api.get<Page<DeliveryLog>>('/callbacks/logs', { params })
