import { api } from './client'
import type { DraftResponse, DiscardResponse, DraftSaveResponse } from '@/types/profile'
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
