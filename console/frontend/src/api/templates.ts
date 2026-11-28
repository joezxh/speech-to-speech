import { api } from './client'

/** 模板字段快照（后端 normalize_fields 补齐 patch/hot/source）。 */
export interface TemplateField {
  key: string
  value: string
  patch: string
  source: string
  hot: boolean
}

export type TemplateEffect = 'runtime' | 'restart'

export interface TemplateRow {
  id: number
  name: string
  effect: TemplateEffect
  platform: string
  status: string
  scene: string
  minVramGb: number | null
  fields: TemplateField[]
  desc: string
  createdAt: string | null
  updatedAt: string | null
  createdBy: string
  updatedBy: string
}

export interface TemplateFilter {
  effect?: string
  platform?: string
  status?: string
  q?: string
}

export interface TemplatePayload {
  name: string
  effect: TemplateEffect
  platform: string
  status: string
  scene: string
  minVramGb: number | null
  fields: Array<{ key: string; value: string }>
  desc: string
}

export const templatesApi = {
  list: (filter: TemplateFilter = {}) =>
    api.get<{ templates: TemplateRow[]; total: number }>('/templates', { params: filter }),
  get: (id: number) => api.get<TemplateRow>(`/templates/${id}`),
  create: (payload: TemplatePayload) => api.post<TemplateRow>('/templates', payload),
  update: (id: number, payload: Partial<TemplatePayload>) => api.put<TemplateRow>(`/templates/${id}`, payload),
  remove: (id: number) => api.delete<void>(`/templates/${id}`)
}
