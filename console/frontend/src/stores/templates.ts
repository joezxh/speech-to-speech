import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { AppError } from '@/api/client'
import { templatesApi, type TemplateFilter, type TemplatePayload, type TemplateRow } from '@/api/templates'
import i18n from '@/i18n'

/** 模板管理（原型「模板管理」页）：一次全量拉取，筛选在前端做（数据量小）。 */
export const useTemplatesStore = defineStore('templates', () => {
  const rows = ref<TemplateRow[]>([])
  const loading = ref(false)
  const saving = ref(false)
  const error = ref<AppError | null>(null)

  const runtimeCount = computed(() => rows.value.filter((row) => row.effect === 'runtime').length)
  const restartCount = computed(() => rows.value.filter((row) => row.effect === 'restart').length)
  const platformCount = computed(() => new Set(rows.value.map((row) => row.platform)).size)

  async function load(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const data = await templatesApi.list()
      rows.value = data.templates
    } catch (caught) {
      error.value = caught instanceof AppError ? caught : new AppError('unknown', i18n.global.t('templates.loadFailed'))
      rows.value = []
    } finally {
      loading.value = false
    }
  }

  function applyFilter(filter: TemplateFilter): TemplateRow[] {
    const q = (filter.q ?? '').trim().toLowerCase()
    return rows.value.filter(
      (row) =>
        (!filter.effect || row.effect === filter.effect) &&
        (!filter.platform || row.platform === filter.platform) &&
        (!filter.status || row.status === filter.status) &&
        (!q || `${row.name} ${row.id} ${row.desc}`.toLowerCase().includes(q))
    )
  }

  async function create(payload: TemplatePayload): Promise<TemplateRow | null> {
    saving.value = true
    error.value = null
    try {
      const created = await templatesApi.create(payload)
      await load()
      return created
    } catch (caught) {
      error.value = caught instanceof AppError ? caught : new AppError('unknown', i18n.global.t('templates.saveFailed'))
      return null
    } finally {
      saving.value = false
    }
  }

  async function update(id: number, payload: Partial<TemplatePayload>): Promise<TemplateRow | null> {
    saving.value = true
    error.value = null
    try {
      const updated = await templatesApi.update(id, payload)
      await load()
      return updated
    } catch (caught) {
      error.value = caught instanceof AppError ? caught : new AppError('unknown', i18n.global.t('templates.saveFailed'))
      return null
    } finally {
      saving.value = false
    }
  }

  async function remove(id: number): Promise<boolean> {
    saving.value = true
    error.value = null
    try {
      await templatesApi.remove(id)
      await load()
      return true
    } catch (caught) {
      error.value = caught instanceof AppError ? caught : new AppError('unknown', i18n.global.t('templates.deleteFailed'))
      return false
    } finally {
      saving.value = false
    }
  }

  return {
    rows,
    loading,
    saving,
    error,
    runtimeCount,
    restartCount,
    platformCount,
    load,
    applyFilter,
    create,
    update,
    remove
  }
})
