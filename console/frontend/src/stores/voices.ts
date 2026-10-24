import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { AppError } from '@/api/client'
import * as voicesApi from '@/api/voices'
import type { CreateVoiceForm, VoiceBackend, VoiceFilter, VoiceRow } from '@/types/voice-library'

export const useVoicesStore = defineStore('voices', () => {
  const rows = ref<VoiceRow[]>([])
  const backends = ref<VoiceBackend[]>([])
  const total = ref(0)
  const filter = ref<VoiceFilter>({})
  const loading = ref(false)
  const saving = ref(false)
  /** `voice_in_use` 的 `detail` 原样留在这里，表格据此渲染「被 prod、v12 引用」。 */
  const error = ref<AppError | null>(null)

  /** 只有 `ready` 的音色能被参数页选中（§3.11.2 步骤 5）。 */
  const ready = computed(() => rows.value.filter((row) => row.status === 'ready'))
  const catalogued = computed(() => backends.value.filter((item) => item.catalogued))
  const uncatalogued = computed(() => backends.value.filter((item) => !item.catalogued))

  async function load(next: VoiceFilter = filter.value): Promise<void> {
    filter.value = next
    loading.value = true
    error.value = null
    try {
      const data = await voicesApi.listVoices(next)
      rows.value = data.list
      total.value = data.total
    } catch (caught) {
      error.value = caught instanceof AppError ? caught : new AppError('unknown', '音色库加载失败')
      rows.value = []
      total.value = 0
    } finally {
      loading.value = false
    }
  }

  async function loadBackends(): Promise<void> {
    try {
      backends.value = (await voicesApi.listVoiceBackends()).list
    } catch (caught) {
      error.value = caught instanceof AppError ? caught : new AppError('unknown', '后端清单加载失败')
    }
  }

  async function create(form: CreateVoiceForm): Promise<VoiceRow | null> {
    saving.value = true
    error.value = null
    try {
      const created = await voicesApi.createVoice(form)
      await load()
      return (await voicesApi.getVoice(created.id)) as VoiceRow
    } catch (caught) {
      error.value = caught instanceof AppError ? caught : new AppError('unknown', '上传失败')
      return null
    } finally {
      saving.value = false
    }
  }

  async function duplicate(id: string): Promise<boolean> {
    saving.value = true
    error.value = null
    try {
      await voicesApi.duplicateVoice(id)
      await load()
      return true
    } catch (caught) {
      error.value = caught instanceof AppError ? caught : new AppError('unknown', '复制失败')
      return false
    } finally {
      saving.value = false
    }
  }

  async function remove(id: string): Promise<boolean> {
    saving.value = true
    error.value = null
    try {
      await voicesApi.deleteVoice(id)
      await load()
      return true
    } catch (caught) {
      // 409 的 `detail` 是 [{field:"profiles",value:[…]},{field:"versions",value:N}]，
      // 不在这里翻译，交给 `describeInUse` 统一成一句固定文案。
      error.value = caught instanceof AppError ? caught : new AppError('unknown', '删除失败')
      return false
    } finally {
      saving.value = false
    }
  }

  /** 预计算进度轮询用：单行、不打整张表。 */
  async function refreshOne(id: string): Promise<VoiceRow | null> {
    try {
      const row = await voicesApi.getVoice(id)
      const index = rows.value.findIndex((item) => item.id === id)
      if (index >= 0) rows.value[index] = row
      return row
    } catch (caught) {
      error.value = caught instanceof AppError ? caught : new AppError('unknown', '音色详情读取失败')
      return null
    }
  }

  return {
    rows,
    backends,
    total,
    filter,
    loading,
    saving,
    error,
    ready,
    catalogued,
    uncatalogued,
    load,
    loadBackends,
    create,
    duplicate,
    remove,
    refreshOne
  }
})
