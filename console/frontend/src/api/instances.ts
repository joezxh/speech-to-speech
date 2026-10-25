import { api } from './client'
import type { InstanceMetricPoint, InstanceSnapshot } from '@/types/api'

export const getInstances = (profile: string): Promise<InstanceSnapshot> =>
  api.get<InstanceSnapshot>('/instances', { params: { profile } })

export const getInstance = (id: string): Promise<Record<string, unknown>> =>
  api.get<Record<string, unknown>>(`/instances/${id}`)

export const getInstanceMetrics = (
  id: string,
  window: '1h' | '6h' | '24h' | '7d'
): Promise<{ instance_id: string; window: string; points: InstanceMetricPoint[] }> =>
  api.get<{ instance_id: string; window: string; points: InstanceMetricPoint[] }>(
    `/instances/${id}/metrics`,
    { params: { window } }
  )

export const postInstanceAction = (id: string, action: 'drain' | 'undrain' | 'probe') =>
  api.post<Record<string, unknown>>(`/instances/${id}/${action}`)
