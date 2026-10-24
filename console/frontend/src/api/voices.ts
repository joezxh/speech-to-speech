import { api, client } from './client'
import type { Page } from '@/types/api'
import type {
  CreateVoiceForm,
  CreateVoiceResult,
  VoiceBackend,
  VoiceFilter,
  VoiceRow
} from '@/types/voice-library'

/** 列表与 A.0 的分页包络同形（`{list,total,page,pageSize}`）。 */
export function listVoices(filter: VoiceFilter = {}): Promise<Page<VoiceRow>> {
  return api.get<Page<VoiceRow>>('/voices', { params: filter })
}

export function listVoiceBackends(): Promise<{ list: VoiceBackend[] }> {
  return api.get<{ list: VoiceBackend[] }>('/voices/backends')
}

export function getVoice(id: string): Promise<VoiceRow> {
  return api.get<VoiceRow>(`/voices/${id}`)
}

/**
 * 上传必须是 `FormData`：`client` 没有默认 `Content-Type`，axios 才会自己补上
 * 带 boundary 的 `multipart/form-data`。`consent` 由这一层固定填，界面上勾了
 * 复选框才调到这里（§3.11.5 的生物特征授权）。
 */
export function createVoice(form: CreateVoiceForm): Promise<CreateVoiceResult> {
  const body = new FormData()
  for (const [key, value] of Object.entries(form)) {
    if (value === undefined || value === null) continue
    body.append(key, value instanceof Blob ? value : String(value))
  }
  body.append('consent', 'biometric-ack')
  return api.post<CreateVoiceResult>('/voices', body)
}

export function duplicateVoice(id: string, name?: string): Promise<{ id: string; name: string; status: string }> {
  return api.post<{ id: string; name: string; status: string }>(`/voices/${id}/duplicate`, { name: name ?? '' })
}

export function deleteVoice(id: string): Promise<{ deleted: boolean }> {
  return api.delete<{ deleted: boolean }>(`/voices/${id}`)
}

export function voiceAudioUrl(id: string): string {
  return `/api/v1/voices/${id}/audio`
}

/**
 * `<audio src>` 带不上 `Authorization`，所以先 fetch 成 blob URL：既保住鉴权，
 * 也不新增契约。调用方负责 `URL.revokeObjectURL`。
 */
export async function fetchVoiceAudio(id: string): Promise<string> {
  const response = await client.get(voiceAudioUrl(id), { responseType: 'blob' })
  return URL.createObjectURL(response.data as Blob)
}
