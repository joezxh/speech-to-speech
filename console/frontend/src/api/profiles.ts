import { api } from './client'
import type {
  AuditRow,
  DraftResponse,
  DiscardResponse,
  DraftSaveResponse,
  PublishResult,
  RollbackResult,
  VersionRow
} from '@/types/profile'
import type { Page } from '@/types/api'
import type { Values } from '@/utils/draft-patch'

export const getDraft = (profile: string): Promise<DraftResponse> =>
  api.get<DraftResponse>(`/profiles/${profile}/draft`)

export const saveDraft = (
  profile: string,
  patch: Values,
  baseVersion: number | null
): Promise<DraftSaveResponse> =>
  api.post<DraftSaveResponse>(`/profiles/${profile}/draft`, { patch, baseVersion })

export const discardDraft = (profile: string): Promise<DiscardResponse> =>
  api.delete<DiscardResponse>(`/profiles/${profile}/draft`)

export interface AuditQuery {
  actor?: string
  action?: string
  result?: string
  field?: string
  from?: string
  to?: string
  page?: number
  pageSize?: number
}

export const getVersions = (
  profile: string,
  page = 1,
  pageSize = 20
): Promise<Page<VersionRow>> =>
  api.get<Page<VersionRow>>(`/profiles/${profile}/versions`, { params: { page, pageSize } })

export const getAudit = (profile: string, query: AuditQuery = {}): Promise<Page<AuditRow>> =>
  api.get<Page<AuditRow>>(`/profiles/${profile}/audit`, { params: query })

// 发布是同步的：重启 ≤60s + 探活 ≤180s（失败还要回滚再探一次）。默认 30s
// 超时会把一次成功的发布报成失败，而服务端其实已经写盘并重启了。
const LONG_RUNNING = { timeout: 480_000 }

export const publishProfile = (
  profile: string,
  body: { baseVersion: number | null; note: string }
): Promise<PublishResult> =>
  api.post<PublishResult>(`/profiles/${profile}/publish`, body, LONG_RUNNING)

export const rollbackProfile = (
  profile: string,
  body: { targetVersion: number; note: string }
): Promise<RollbackResult> =>
  api.post<RollbackResult>(`/profiles/${profile}/rollback`, body, LONG_RUNNING)
