import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { AppError } from '@/api/client'
import { clustersApi } from '@/api/clusters'
import type { ClusterRow } from '@/types/api'
import { readCluster, saveCluster } from '@/utils/storage'

/**
 * 当前集群是纯前端视图态（spec §5.1）：持久在 sessionStorage，切换动作走
 * `POST /clusters/{name}/switch` 只留审计。失败（含审计失败）不切换。
 */
export const useClusterStore = defineStore('cluster', () => {
  const rows = ref<ClusterRow[]>([])
  const current = ref(readCluster())
  const error = ref<AppError | null>(null)
  const currentRow = computed(() => rows.value.find((row) => row.name === current.value) ?? null)
  let inFlight: Promise<void> | null = null

  function select(name: string): void {
    current.value = name
    saveCluster(name)
  }

  /** 存量视图里找不到保存的当前集群（改名/删除/换标签页数据漂移）→ 回落第一个。 */
  function syncCurrent(): void {
    if (!rows.value.length) return
    if (!rows.value.some((row) => row.name === current.value)) select(rows.value[0].name)
  }

  async function load(): Promise<void> {
    if (inFlight) return inFlight
    inFlight = (async () => {
      try {
        rows.value = await clustersApi.list()
        error.value = null
        syncCurrent()
      } catch (caught) {
        error.value = caught instanceof AppError ? caught : new AppError('unknown', String(caught))
      } finally {
        inFlight = null
      }
    })()
    return inFlight
  }

  async function switchTo(name: string): Promise<boolean> {
    try {
      await clustersApi.switchTo(name)
      select(name)
      return true
    } catch (caught) {
      error.value = caught instanceof AppError ? caught : new AppError('unknown', String(caught))
      return false
    }
  }

  async function remove(name: string): Promise<void> {
    await clustersApi.remove(name)
    await load()
  }

  return { rows, current, currentRow, error, load, select, switchTo, remove }
})