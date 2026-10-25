import axios from 'axios'

import type { MeResponse } from '@/features/voice/types'
import type { DemoConfig } from '@/types/demo'

/** The demo face has its own contract (A.13): bare objects, no JWT.
 *
 * Deliberately not `api/client.ts`: that instance unwraps `ApiResponse`, redirects
 * to `/console/login` on 401, and retries through a refresh token — none of which
 * apply to an anonymous `/api/*` call.
 */
export const getDemoConfig = async (): Promise<DemoConfig> =>
  (await axios.get<DemoConfig>('/api/config', { timeout: 10_000 })).data

/** A 404 means “metering is off for this deploy”, not a failure to report. */
export async function getMe(): Promise<MeResponse> {
  const res = await fetch('/api/me')
  if (!res.ok) return { enabled: false }
  return (await res.json()) as MeResponse
}

export async function postSession(): Promise<Response> {
  return fetch('/api/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}'
  })
}

/** 后端只回 `expired`；`remainingSec` 是可选透传，缺了页面就不更新徽标。 */
export async function heartbeat(sessionId: string): Promise<{ expired: boolean; remainingSec?: number | null }> {
  const res = await fetch('/api/session/heartbeat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId })
  })
  if (!res.ok) return { expired: false }
  return (await res.json()) as { expired: boolean; remainingSec?: number | null }
}

/** sendBeacon can only POST: it survives the tab close that a fetch does not. */
export function endSessionBeacon(sessionId: string): void {
  const body = new Blob([JSON.stringify({ sessionId })], { type: 'application/json' })
  if (!navigator.sendBeacon('/api/session/end', body)) {
    void fetch('/api/session/end', { method: 'POST', body, keepalive: true })
  }
}

export function leaveQueueBeacon(queueId: string): void {
  const body = new Blob([JSON.stringify({ queueId })], { type: 'application/json' })
  if (!navigator.sendBeacon('/api/queue/end', body)) {
    void fetch('/api/queue/end', { method: 'POST', body, keepalive: true })
  }
}

export async function search(query: string, key: string, sessionId: string): Promise<string> {
  const res = await fetch('/api/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, ...(key ? { key } : {}), ...(sessionId ? { sessionId } : {}) })
  })
  if (!res.ok) throw new Error(`search failed (${res.status})`)
  const body = (await res.json()) as { answer?: string; results?: { title: string; snippet: string; url: string }[] }
  // Date-stamp the header so the model treats hits as fresh facts, not memory.
  const today = new Date().toISOString().slice(0, 10)
  const lines = [`Google search result from ${today}:`]
  if (body.answer) lines.push(`Answer: ${body.answer}`)
  for (const hit of body.results ?? []) lines.push(`- ${hit.title}: ${hit.snippet} (${hit.url})`)
  return lines.length > 1 ? lines.join('\n') : `${lines[0]}\nNo results found.`
}
