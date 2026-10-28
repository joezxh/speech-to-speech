import i18n from '@/i18n'

import type { CatalogEntry } from '@/types/catalog'

export interface FieldGroup {
  /** `${stage}::${backend ?? ''}`，直接当 `a-menu-item` 的 key。 */
  key: string
  stage: string
  backend: string | null
  readOnly: boolean
  items: CatalogEntry[]
}

export interface Deduped {
  items: CatalogEntry[]
  /** 被合并的条目，只在详情里展示（`aliases`），树与表单各只出现一次。 */
  aliases: Record<string, CatalogEntry[]>
  multiBackend: number
}

/** 这三级不在运维面可写范围（§6.1），但必须在树上可见。 */
export const READ_ONLY_STAGES = new Set(['deploy', 'env', 'client'])

/** 3 条重名保留哪一条（§6.1）：服务端优先、前缀所属 backend 优先、通用组优先。 */
const PREFERRED: Record<string, (entry: CatalogEntry) => boolean> = {
  log_transcripts: (entry) => entry.stage === 'runtime',
  model_name: (entry) => entry.backend === null,
  responses_api_reasoning_effort: (entry) => entry.backend === 'responses-api'
}

export function dedupe(entries: CatalogEntry[]): Deduped {
  const kept = new Map<string, CatalogEntry>()
  const aliases: Record<string, CatalogEntry[]> = {}
  const multi = new Set<string>()

  for (const entry of entries) {
    const current = kept.get(entry.name)
    if (!current) {
      kept.set(entry.name, entry)
      continue
    }

    const prefer = PREFERRED[entry.name]
    const keepNew = prefer ? prefer(entry) && !prefer(current) : false
    const winner = keepNew ? entry : current
    const loser = keepNew ? current : entry

    kept.set(entry.name, winner)
    aliases[entry.name] = [...(aliases[entry.name] ?? []), loser]

    // 「多后端」只算同一 stage 内跨 backend；跨 stage 的（client ↔ runtime）不算。
    if (winner.stage === loser.stage && winner.backend !== loser.backend) multi.add(entry.name)
  }

  return { items: [...kept.values()], aliases, multiBackend: multi.size }
}

/** 两级分组：stage → backend，保持 catalog 的出现顺序；17 组（§6.1）。 */
export function groupByStage(entries: CatalogEntry[]): FieldGroup[] {
  const order: string[] = []
  const buckets = new Map<string, FieldGroup>()

  for (const entry of entries) {
    const key = `${entry.stage}::${entry.backend ?? ''}`
    if (!buckets.has(key)) {
      order.push(key)
      buckets.set(key, {
        key,
        stage: entry.stage,
        backend: entry.backend,
        readOnly: READ_ONLY_STAGES.has(entry.stage),
        items: []
      })
    }
    buckets.get(key)!.items.push(entry)
  }

  return order.map((key) => buckets.get(key)!)
}

/** 只读行：源码常量（`type=fixed`）与三个不在运维面的 stage，一律不套用分级表（§7.3）。 */
export function isReadOnlyRow(entry: CatalogEntry): boolean {
  return entry.type === 'fixed' || READ_ONLY_STAGES.has(entry.stage)
}

/** 计数行唯一文案：不得手写数字（§14.7）。 */
export function countLabel(total: number, deduped: Deduped): string {
  return i18n.global.t('deploy.countLabel', {
    total,
    unique: deduped.items.length,
    multi: deduped.multiBackend
  })
}
