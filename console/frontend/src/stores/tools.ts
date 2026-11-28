import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { AppError } from '@/api/client'
import { toolsApi, type ToolFilter, type ToolInvokeResult, type ToolPayload, type ToolRow } from '@/api/tools'
import i18n from '@/i18n'

const SESSION_KEY = 's2s.tools.session.enabled'

function readSessionEnabled(): Record<string, boolean> {
  try {
    return JSON.parse(localStorage.getItem(SESSION_KEY) || '{}') as Record<string, boolean>
  } catch {
    return {}
  }
}

/** 会话工具（原型「工具」页）：一次全量拉取，筛选与 KPI 在前端算。 */
export const useToolsStore = defineStore('tools', () => {
  const rows = ref<ToolRow[]>([])
  const loading = ref(false)
  const saving = ref(false)
  const error = ref<AppError | null>(null)
  const sessionEnabled = ref<Record<string, boolean>>(readSessionEnabled())

  const kpi = computed(() => ({
    total: rows.value.length,
    on: rows.value.filter((row) => isEnabled(row)).length,
    builtin: rows.value.filter((row) => row.builtin).length,
    custom: rows.value.filter((row) => !row.builtin).length
  }))

  function isEnabled(row: ToolRow): boolean {
    return row.effectiveEnabled === null ? Boolean(sessionEnabled.value[row.id]) : Boolean(row.effectiveEnabled)
  }

  function applyFilter(filter: ToolFilter): ToolRow[] {
    const q = (filter.q ?? '').trim().toLowerCase()
    return rows.value.filter(
      (row) =>
        (!filter.type || filter.type === 'all' || row.type === filter.type) &&
        (!filter.scope || filter.scope === 'all' || row.scope === filter.scope) &&
        (!filter.on || filter.on === 'all' || String(isEnabled(row)) === filter.on) &&
        (!q || `${row.name} ${row.id} ${row.description} ${row.type}`.toLowerCase().includes(q))
    )
  }

  const enabledTools = computed(() => rows.value.filter(isEnabled))

  async function load(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const data = await toolsApi.list()
      rows.value = data.tools
    } catch (caught) {
      error.value = caught instanceof AppError ? caught : new AppError('unknown', i18n.global.t('tools.loadFailed'))
      rows.value = []
    } finally {
      loading.value = false
    }
  }

  async function create(payload: ToolPayload): Promise<ToolRow | null> {
    saving.value = true
    try {
      const created = await toolsApi.create(payload)
      await load()
      return created
    } catch (caught) {
      error.value = caught instanceof AppError ? caught : new AppError('unknown', i18n.global.t('tools.saveFailed'))
      return null
    } finally {
      saving.value = false
    }
  }

  async function update(id: string, payload: Partial<ToolPayload>): Promise<ToolRow | null> {
    saving.value = true
    try {
      const updated = await toolsApi.update(id, payload)
      await load()
      return updated
    } catch (caught) {
      error.value = caught instanceof AppError ? caught : new AppError('unknown', i18n.global.t('tools.saveFailed'))
      return null
    } finally {
      saving.value = false
    }
  }

  async function remove(id: string): Promise<boolean> {
    saving.value = true
    try {
      await toolsApi.remove(id)
      await load()
      return true
    } catch (caught) {
      error.value = caught instanceof AppError ? caught : new AppError('unknown', i18n.global.t('tools.deleteFailed'))
      return false
    } finally {
      saving.value = false
    }
  }

  async function copy(id: string): Promise<ToolRow | null> {
    saving.value = true
    try {
      const created = await toolsApi.copy(id)
      await load()
      return created
    } catch (caught) {
      error.value = caught instanceof AppError ? caught : new AppError('unknown', i18n.global.t('tools.saveFailed'))
      return null
    } finally {
      saving.value = false
    }
  }

  async function toggle(id: string, enabled: boolean): Promise<void> {
    const row = rows.value.find((item) => item.id === id)
    if (row?.effectiveEnabled === null) {
      sessionEnabled.value = { ...sessionEnabled.value, [id]: enabled }
      localStorage.setItem(SESSION_KEY, JSON.stringify(sessionEnabled.value))
      return
    }
    await toolsApi.toggle(id, enabled)
    await load()
  }

  async function invoke(id: string, args: Record<string, unknown>): Promise<ToolInvokeResult> {
    return toolsApi.invoke(id, args)
  }

  return {
    rows, loading, saving, error, sessionEnabled, kpi, enabledTools,
    isEnabled, applyFilter, load, create, update, remove, copy, toggle, invoke
  }
})
