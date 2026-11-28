import { api } from './client'

export type ToolType = 'web_search' | 'calendar' | 'weather' | 'kb' | 'http'
export type ToolScope = 'global' | 'session' | 'tenant'

export interface ToolParam {
  k: string
  t: string
  req: boolean
}

export interface ToolRow {
  id: string
  name: string
  type: ToolType
  description: string
  endpoint: string
  method: 'GET' | 'POST'
  scope: ToolScope
  enabled: boolean
  builtin: boolean
  owner: string
  params: ToolParam[]
  config: Record<string, unknown>
  /** null = 由浏览器 localStorage 决定（scope=session）。 */
  effectiveEnabled: boolean | null
  writable: boolean
  createdAt: string | null
  updatedAt: string | null
  createdBy: string
  updatedBy: string
}

export interface ToolFilter {
  q?: string
  type?: string
  scope?: string
  on?: string
}

export interface ToolPayload {
  name: string
  type: ToolType
  description: string
  endpoint: string
  method: 'GET' | 'POST'
  scope: ToolScope
  enabled?: boolean
  params: ToolParam[]
  config?: Record<string, unknown>
}

export interface ToolInvokeResult {
  mode: 'live' | 'demo' | 'local'
  provider: string
  data: Record<string, unknown>
}

export const toolsApi = {
  list: (filter: ToolFilter = {}) => api.get<{ tools: ToolRow[] }>('/tools', { params: filter }),
  create: (payload: ToolPayload) => api.post<ToolRow>('/tools', payload),
  update: (id: string, payload: Partial<ToolPayload>) => api.put<ToolRow>(`/tools/${id}`, payload),
  remove: (id: string) => api.delete<void>(`/tools/${id}`),
  copy: (id: string) => api.post<ToolRow>(`/tools/${id}/copy`),
  toggle: (id: string, enabled: boolean) => api.put<ToolRow>(`/tools/${id}/enabled`, { enabled }),
  invoke: (id: string, args: Record<string, unknown>) =>
    api.post<ToolInvokeResult>(`/tools/${id}/invoke`, { arguments: args })
}
