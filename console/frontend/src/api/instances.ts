import { api } from './client'
import type { InstanceSnapshot } from '@/types/api'

export const getInstances = (profile: string): Promise<InstanceSnapshot> =>
  api.get<InstanceSnapshot>('/instances', { params: { profile } })
