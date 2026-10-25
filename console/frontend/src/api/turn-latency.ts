import { api } from './client'
import type { TurnLatencyPage } from '@/types/turn-latency'

/**
 * A.17. `status` is repeated keys for the same reason as A.15's filters, and
 * the string is normalised so `select` and `set` always get the same shape.
 */
export function turnLatencyQuery(from: string, to: string, status: string[], limit = 100): string {
  const params = new URLSearchParams()
  params.set('from', from)
  params.set('to', to)
  for (const value of status) params.append('status', value)
  params.set('limit', String(limit))
  return params.toString()
}

export const fetchTurnLatency = (
  from: string,
  to: string,
  status: string[] = [],
  limit = 100
): Promise<TurnLatencyPage> =>
  api.get<TurnLatencyPage>(`/turn-latency?${turnLatencyQuery(from, to, status, limit)}`)
