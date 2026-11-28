<script setup lang="ts">
// 原型 templateSelectBar：部署页顶部的模板 chips，点击只读查看（不在页内展开参数）。
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import TemplateViewModal from './TemplateViewModal.vue'
import type { TemplateRow } from '@/api/templates'
import { useTemplatesStore } from '@/stores/templates'

const { t } = useI18n()
const store = useTemplatesStore()
const viewOpen = ref(false)
const viewRow = ref<TemplateRow | null>(null)

onMounted(() => {
  void store.load()
})
</script>

<template>
  <div class="tsb">
    <div class="tsb__head">
      <b>{{ t('templates.bar.title') }}</b>
      <span class="tsb__hint">{{ t('templates.bar.hint') }}</span>
    </div>
    <div class="tsb__chips">
      <button
        v-for="template in store.rows"
        :key="template.id"
        class="tsb__chip"
        :data-effect="template.effect"
        @click="viewRow = template; viewOpen = true"
      >
        {{ template.name }}
        <small>{{ t(`templates.effect.${template.effect}`) }}</small>
      </button>
      <span v-if="!store.loading && !store.rows.length" class="tsb__hint">{{ t('templates.panel.noTemplates') }}</span>
    </div>
    <TemplateViewModal :open="viewOpen" :template="viewRow" @close="viewOpen = false" />
  </div>
</template>

<style scoped lang="less">
.tsb {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;

  &__head {
    display: flex;
    gap: 12px;
    align-items: baseline;
    flex-wrap: wrap;
  }
  &__hint {
    color: var(--muted);
    font-size: 12px;
  }
  &__chips {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-top: 8px;
  }
  &__chip {
    border: 1px solid var(--border);
    background: transparent;
    border-radius: 999px;
    padding: 4px 12px;
    cursor: pointer;
    small {
      color: var(--muted);
      font-size: 11px;
      margin-left: 6px;
    }
    &[data-effect='restart'] small {
      color: var(--warn-text);
    }
  }
}
</style>
