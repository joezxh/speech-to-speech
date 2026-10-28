import { api, client } from './client'

/**
 * `/api/v1/voice-sessions` 是录音归档（spec 2026-10-26 session-archive）的读侧契约。
 * 行字段全部 camelCase，与控制台其余快照一致；`audioUrl` 是后端下发的绝对路径，
 * 播放时要用 `turnAudioRequestPath` 摘掉 baseURL 已经带上的 `/api/v1` 前缀。
 */
export interface VoiceSessionRow {
  id: string
  title: string | null
  pipelineSessionId: string | null
  status: string
  turnCount: number
  audioBytes: number
  createdBy: string | null
  clientKind: string | null
  startedAt: string
  expiresAt: string | null
}

export interface VoiceTurnRow {
  id: string
  ordinal: number
  role: string
  speakerLabel: string | null
  rev: number
  startedAt: string
  text: string | null
  audioUrl: string | null
  audioState: 'none' | 'available' | 'deleted'
  audioBytes: number
  audioSeconds: number
  audioTruncated: boolean
}

/** keyset 游标分页：`nextCursor` 为空串代表到底。 */
export interface VoiceSessionPage {
  list: VoiceSessionRow[]
  nextCursor: string
}

export interface VoiceSessionDetail {
  session: VoiceSessionRow
  turns: VoiceTurnRow[]
  total: number
}

const PREFIX = '/api/v1'

/**
 * `turn_payload.audioUrl` 是绝对路径，而 `client` 的 baseURL 同为 `/api/v1`：
 * 只摘一整段前缀（`/api/v1/…` 或恰为 `/api/v1`），`/api/v1preview` 这种同名单词不动。
 */
export function turnAudioRequestPath(url: string): string {
  if (url === PREFIX) return ''
  if (url.startsWith(`${PREFIX}/`)) return url.slice(PREFIX.length)
  return url
}

export async function listVoiceSessions(params: {
  limit: number
  cursor?: string
  status?: string
}): Promise<VoiceSessionPage> {
  const query: Record<string, string> = { limit: String(params.limit) }
  if (params.cursor) query.cursor = params.cursor
  if (params.status) query.status = params.status
  return api.get<VoiceSessionPage>('/voice-sessions', { params: query })
}

export async function getVoiceSession(id: string): Promise<VoiceSessionDetail> {
  return api.get<VoiceSessionDetail>(`/voice-sessions/${id}`)
}

/** 音频流走 bearer token，`<audio src>` 直链取不到，只能带拦截器下载成 Blob。 */
export async function fetchVoiceTurnAudio(audioUrl: string): Promise<Blob> {
  const response = await client.get<Blob>(turnAudioRequestPath(audioUrl), { responseType: 'blob' })
  return response.data
}

export async function deleteVoiceSession(id: string): Promise<void> {
  await api.delete<null>(`/voice-sessions/${id}`)
}
