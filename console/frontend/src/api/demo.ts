import axios from 'axios'

import type { DemoConfig } from '@/types/demo'

/** The demo face has its own contract (A.13): bare objects, no JWT.
 *
 * Deliberately not `api/client.ts`: that instance unwraps `ApiResponse`, redirects
 * to `/console/login` on 401, and retries through a refresh token — none of which
 * apply to an anonymous `/api/*` call.
 */
export const getDemoConfig = async (): Promise<DemoConfig> =>
  (await axios.get<DemoConfig>('/api/config', { timeout: 10_000 })).data
