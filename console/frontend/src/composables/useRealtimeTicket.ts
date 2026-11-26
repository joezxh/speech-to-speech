/** WS 短票据（Task 28，spec §7.4）：呼叫前换一张一次性票据拼进 WS URL。
 * 失败（401/过期/网络）返回 null——匿名继续，绝不阻塞呼叫。 */

import { readToken } from '@/utils/storage'

export async function fetchRealtimeTicket(): Promise<string | null> {
  try {
    const token = readToken()
    const response = await fetch('/api/v1/realtime/ticket', {
      method: 'POST',
      credentials: 'include',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (!response.ok) return null
    const payload = (await response.json()) as { data?: { ticket?: string } }
    return payload.data?.ticket ?? null
  } catch {
    return null
  }
}

export async function appendRealtimeTicket(url: string): Promise<string> {
  const ticket = await fetchRealtimeTicket()
  if (!ticket) return url
  const joiner = url.includes('?') ? '&' : '?'
  return `${url}${joiner}ticket=${encodeURIComponent(ticket)}`
}
