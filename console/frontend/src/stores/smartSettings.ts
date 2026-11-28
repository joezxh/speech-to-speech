import { defineStore } from 'pinia'
import { reactive } from 'vue'

import { AppError } from '@/api/client'
import { smartSettingsApi, type SmartAnalyzeResult, type SmartFetchResult } from '@/api/smartSettings'
import i18n from '@/i18n'

/**
 * 智能设置（原型 smartPanel）：前台「对话态热更」与运维「部署」两处共用。
 * fetch 一次拿全机器参数与日志；analyze 是付费 LLM 副作用，由后端限流与单飞，
 * 前端不做节流，失败（429/超时）原样透出。
 */
export const useSmartSettingsStore = defineStore('smartSettings', () => {
  const data = reactive<{
    machineId: string
    fetched: SmartFetchResult | null
    analysis: SmartAnalyzeResult | null
    loading: boolean
    analyzing: boolean
    error: AppError | null
  }>({ machineId: '', fetched: null, analysis: null, loading: false, analyzing: false, error: null })

  function reset(): void {
    data.fetched = null
    data.analysis = null
    data.error = null
  }

  async function fetch(machineId: string): Promise<SmartFetchResult | null> {
    data.machineId = machineId
    data.loading = true
    data.error = null
    try {
      data.fetched = await smartSettingsApi.fetch(machineId)
      return data.fetched
    } catch (caught) {
      data.error = caught instanceof AppError ? caught : new AppError('unknown', i18n.global.t('smart.loadFailed'))
      data.fetched = null
      return null
    } finally {
      data.loading = false
    }
  }

  async function analyze(machineId: string, fault: string): Promise<SmartAnalyzeResult | null> {
    if (!fault.trim()) {
      data.error = new AppError('invalid_parameter', i18n.global.t('smart.emptyFault'))
      return null
    }
    const params: Record<string, string> = {}
    const logs: string[] = []
    for (const row of data.fetched?.params ?? []) {
      const value = row.actual ?? row.expected ?? ''
      if (value !== '') params[row.key] = value
    }
    for (const line of data.fetched?.logs ?? []) {
      logs.push(line.ts ? `[${line.ts}] ${line.text}` : line.text)
    }
    data.analyzing = true
    data.error = null
    try {
      data.analysis = await smartSettingsApi.analyze({ machineId, fault: fault.trim(), params, logs })
      return data.analysis
    } catch (caught) {
      data.error = caught instanceof AppError ? caught : new AppError('unknown', i18n.global.t('smart.loadFailed'))
      return null
    } finally {
      data.analyzing = false
    }
  }

  return { data, reset, fetch, analyze }
})
