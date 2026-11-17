import { api } from './client'

export interface ReleaseRow {
  release_id: string
  version: string
  profile: string
  status: string
  stage: string
  created_by: string
  artifact_ref: string
  changes: Array<Record<string, unknown>>
}

export const releasesApi = {
  list: () => api.get<{ releases: ReleaseRow[] }>('/releases'),
  summary: () => api.get<{ pending_backfill: number; releases: number }>('/releases/summary'),
  create: (name: string, profile: string, artifactRef = '') =>
    api.post('/releases', { name, profile, artifactRef }),
  advance: (releaseId: string, stage: string, result = 'ok', note = '') =>
    api.post(`/releases/${releaseId}/advance`, { stage, result, note }),
  stageResult: (releaseId: string, stage: string, result = 'ok', artifactRef = '', note = '', signature: string | null = null) =>
    api.post(`/releases/${releaseId}/stage-result`, { stage, result, artifactRef, note, signature }),
  rollback: (releaseId: string) => api.post(`/releases/${releaseId}/rollback`),
}
