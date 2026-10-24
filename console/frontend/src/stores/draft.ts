import { defineStore } from 'pinia'
import { ref } from 'vue'

import * as profilesApi from '@/api/profiles'
import type { ValidationResult } from '@/types/profile'
import type { Values } from '@/utils/draft-patch'

export const useDraftStore = defineStore('draft', () => {
  const profile = ref('')
  const draft = ref<Values>({})
  const masked = ref<string[]>([])
  const baseVersion = ref<number | null>(null)
  const updatedAt = ref<string | null>(null)
  const updatedBy = ref('')
  const validation = ref<ValidationResult | null>(null)
  const loading = ref(false)
  const saving = ref(false)

  async function load(name: string): Promise<void> {
    profile.value = name
    loading.value = true
    try {
      const data = await profilesApi.getDraft(name)
      draft.value = data.draft
      masked.value = data.masked
      baseVersion.value = data.baseVersion
      updatedAt.value = data.updatedAt
      updatedBy.value = data.updatedBy
    } finally {
      loading.value = false
    }
  }

  async function save(name: string, patch: Values): Promise<void> {
    saving.value = true
    try {
      const data = await profilesApi.saveDraft(name, patch, baseVersion.value)
      draft.value = data.draft
      baseVersion.value = data.baseVersion
      validation.value = data.validation
      // A fresh save is the new truth about which keys are secret.
      masked.value = Object.keys(data.draft).filter((key) => data.draft[key] === '***')
    } finally {
      saving.value = false
    }
  }

  async function discard(name: string): Promise<void> {
    await profilesApi.discardDraft(name)
    await load(name)
    validation.value = null
  }

  return {
    profile,
    draft,
    masked,
    baseVersion,
    updatedAt,
    updatedBy,
    validation,
    loading,
    saving,
    load,
    save,
    discard
  }
})
