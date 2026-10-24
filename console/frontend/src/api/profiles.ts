import { api } from './client'
import type {
  AuditRow,
  DraftResponse,
  DiscardResponse,
  DraftSaveResponse,
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
