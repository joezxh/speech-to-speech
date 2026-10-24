import { api } from './client'
import type { SessionUpdateRequest, SessionUpdateResult } from '@/types/session'

export const updateSessions = (body: SessionUpdateRequest): Promise<SessionUpdateResult> =>
  api.post<SessionUpdateResult>('/sessions/update', body)
