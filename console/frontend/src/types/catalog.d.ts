export type Exposure = 'basic' | 'advanced' | 'expert' | 'ops'

/** One catalog row: `parameter-catalog.yaml` 的直映，字段名保持 snake_case（§6 / A.0）。 */
export interface CatalogEntry {
  key: string
  stage: string
  backend: string | null
  name: string
  type: string
  default: unknown
  choices: unknown[]
  required: boolean
  effect: string
  exposure: Exposure
  impact: string
  change_cost: string
  risk: string | null
  source_ref: string
  source_priority: string[]
}

/** A.1 的 `data`（Task 8 多给了几个计数/变体字段，前端用处不大但类型要完整）。 */
export interface CatalogResponse {
  schema: string
  generatedFrom: string
  generatedAt: string | null
  total: number
  returned: number
  exposureLevels: Exposure[]
  exposureCounts: Record<string, number>
  variantKeys: string[]
  parameters: CatalogEntry[]
}
