import { api } from '@/api/client'
import type { ClusterEventRow, ClusterRow, ClusterWritePayload } from '@/types/api'

/** `/api/v1/clusters` 的唯一前端出入口（spec §4）；信封解包由 api/client 完成。 */
const path = (name: string) => `/clusters/${encodeURIComponent(name)}`

export const clustersApi = {
  list: (): Promise<ClusterRow[]> => api.get<ClusterRow[]>('/clusters'),
  events: (limit = 4): Promise<ClusterEventRow[]> =>
    api.get<ClusterEventRow[]>('/clusters/events', { params: { limit } }),
  create: (payload: ClusterWritePayload): Promise<ClusterRow> => api.post<ClusterRow>('/clusters', payload),
  update: (name: string, payload: Omit<ClusterWritePayload, 'name'>): Promise<ClusterRow> =>
    api.put<ClusterRow>(path(name), payload),
  remove: (name: string): Promise<{ name: string; deleted: boolean }> =>
    api.delete<{ name: string; deleted: boolean }>(path(name)),
  switchTo: (name: string): Promise<{ name: string; switched: boolean }> =>
    api.post<{ name: string; switched: boolean }>(`${path(name)}/switch`)
}