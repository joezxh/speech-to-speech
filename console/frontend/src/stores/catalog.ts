import { defineStore } from 'pinia'
import { ref } from 'vue'

import { getCatalog } from '@/api/catalog'
import { AppError } from '@/api/client'
import type { CatalogEntry, Exposure } from '@/types/catalog'

export const useCatalogStore = defineStore('catalog', () => {
  const entries = ref<CatalogEntry[]>([])
  const schema = ref('')
  const generatedFrom = ref('')
  const generatedAt = ref<string | null>(null)
  const exposureCounts = ref<Record<string, number>>({})
  const loading = ref(false)
  const error = ref<AppError | null>(null)

  async function load(options: { exposure?: Exposure; stage?: string } = {}): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const data = await getCatalog(options)
      entries.value = data.parameters
      schema.value = data.schema
      generatedFrom.value = data.generatedFrom
      generatedAt.value = data.generatedAt
      exposureCounts.value = data.exposureCounts
    } catch (caught) {
      error.value = caught instanceof AppError ? caught : new AppError('unknown', '参数目录加载失败')
      entries.value = []
    } finally {
      loading.value = false
    }
  }

  return { entries, schema, generatedFrom, generatedAt, exposureCounts, loading, error, load }
})
