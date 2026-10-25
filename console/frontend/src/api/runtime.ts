import { api } from './client'
import type { RuntimeSnapshot } from '@/types/runtime'

/**
 * A.14. `windowS` is the metrics window the percentiles come from; the caller
 * keeps it stable so `p95` does not jump between two polls for no reason.
 */
export const fetchRuntime = (profile: string, windowS = 300): Promise<RuntimeSnapshot> =>
  api.get<RuntimeSnapshot>('/runtime/models', { params: { profile, windowS } })
