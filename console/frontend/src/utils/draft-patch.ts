import type { CatalogEntry } from '@/types/catalog'

export const MASK = '***'

/** 表单值的集合，键是 catalog 的 `key`（`<stage>.<name>`）。 */
export type Values = Record<string, unknown>

function draftHas(draft: Values, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(draft, key) && draft[key] !== null
}

/** 字段当前应显示的值：草稿优先（`null` 视为未设），否则 catalog 默认值。 */
export function baseline(entries: CatalogEntry[], draft: Values): Values {
  const values: Values = {}
  for (const entry of entries) {
    values[entry.key] = draftHas(draft, entry.key) ? draft[entry.key] : entry.default
  }
  return values
}

/**
 * 交给 `POST /draft` 的 patch。
 *
 * 三个「不发」：没改的、还是掩码的、本来就没值却要「恢复默认」的。第一个
 * 让审计表可读，第二个是为了不让没动过的密钥反复出现在 `fields` 里，第三个
 * 是因为 `null` 只对「草稿里已有值」才有意义（否则服务端会收到一条空操作）。
 */
export function buildPatch(entries: CatalogEntry[], values: Values, draft: Values): Values {
  const base = baseline(entries, draft)
  const patch: Values = {}
  for (const entry of entries) {
    // catalog 的 17 条 fixed 是源码常量：即便调用方把它们塞进 values，也不进 patch（§6.1）。
    if (entry.type === 'fixed') continue
    const key = entry.key
    if (!Object.prototype.hasOwnProperty.call(values, key)) continue
    const next = values[key]
    if (next === MASK) continue
    if (next === base[key]) continue
    if (next === null && !draftHas(draft, key)) continue
    patch[key] = next
  }
  return patch
}

/** 「恢复默认」按钮要写入表单的值：草稿里有值就发 `null`，否则回到默认值。 */
export function resetValue(entry: CatalogEntry, draft: Values): unknown {
  return draftHas(draft, entry.key) ? null : entry.default
}
