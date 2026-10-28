import { api } from './client'
import type { TrafficSettings } from '@/types/traffic'

export const getTrafficSettings = (): Promise<TrafficSettings> =>
  api.get<TrafficSettings>('/traffic/settings')
