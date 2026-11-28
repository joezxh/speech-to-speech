<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { AppError } from '@/api/client'
import { getAudit } from '@/api/profiles'
import AuditTable from '@/components/AuditTable.vue'
import ErrorBanner from '@/components/ErrorBanner.vue'
import { useConsoleStore } from '@/stores/console'
import type { AuditRow } from '@/types/profile'

const { t } = useI18n()
const consoleStore = useConsoleStore()

const rows = ref<AuditRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const loading = ref(false)
const error = ref<AppError | null>(null)

const actor = ref('')
const action = ref('')
const result = ref('')
const field = ref('')
// 原型审计页的分类 chips（audit.cat.*）：点选即按 action 前缀过滤。
const CATEGORIES = ['', 'machine', 'lb', 'deploy', 'release', 'voice', 'cluster', 'template', 'smart']
const category = ref('')

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const data = await getAudit(consoleStore.profile, {
      actor: actor.value || undefined,
      action: action.value || undefined,
      result: result.value || undefined,
      field: field.value || undefined,
      category: category.value || undefined,
      page: page.value,
      pageSize: pageSize.value
    })
    rows.value = data.list
    total.value = data.total
  } catch (caught) {
    error.value = caught instanceof AppError ? caught : new AppError('unknown', t('audit.loadFailed'))
    rows.value = []
  } finally {
    loading.value = false
  }
}

watch([() => consoleStore.profile, page, pageSize], () => void load(), { immediate: true })
</script>

<template>
  <div class="audit">
    <div class="audit__cats">
      <button
        v-for="item in CATEGORIES"
        :key="item"
        class="audit__cat"
        :class="{ active: category === item }"
        @click="category = item; page = 1; void load()"
      >
        {{ item ? t(`audit.cat.${item}`) : t('audit.cat.all') }}
      </button>
    </div>
    <form class="audit__filters" @submit.prevent="page = 1; void load()">
      <a-input v-model:value="actor" :placeholder="t('audit.filters.actor')" allow-clear />
      <a-input v-model:value="action" :placeholder="t('audit.filters.actionPlaceholder')" allow-clear />
      <a-select
        v-model:value="result"
        :options="[
          { value: '', label: t('audit.filters.allResults') },
          { value: 'ok', label: 'ok' },
          { value: 'failed', label: 'failed' }
        ]"
      />
      <a-input v-model:value="field" :placeholder="t('audit.filters.fieldPlaceholder')" allow-clear />
      <a-button type="primary" html-type="submit">{{ t('audit.filters.search') }}</a-button>
    </form>

    <ErrorBanner :error="error" />
    <AuditTable :rows="rows" :loading="loading" />
    <a-pagination
      v-model:current="page"
      v-model:page-size="pageSize"
      :total="total"
      size="small"
      show-size-changer
      :page-size-options="['50', '100', '200']"
    />
  </div>
</template>

<style scoped lang="less">
.audit {
  display: flex;
  flex-direction: column;
  gap: 12px;

  &__cats {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  &__cat {
    border: 1px solid var(--border);
    background: transparent;
    border-radius: 999px;
    padding: 3px 12px;
    cursor: pointer;
    font-size: 12px;
    &.active {
      background: var(--accent);
      color: var(--surface);
    }
  }
  &__filters {
    display: flex;
    gap: 8px;
    max-width: 900px;
  }
}
</style>
