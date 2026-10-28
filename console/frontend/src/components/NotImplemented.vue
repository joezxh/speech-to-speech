<script setup lang="ts">
import { useI18n } from 'vue-i18n'

defineProps<{ targetSubproject: string; reasonKey: string }>()
const { t } = useI18n()
</script>

<template>
  <div class="ni">
    <a-tag color="default">{{ targetSubproject }}</a-tag>
    <span class="ni__reason">{{ t(reasonKey) }}</span>
  </div>
</template>

<style scoped>
.ni {
  align-items: center;
  color: var(--s2s-color-muted);
  display: flex;
  gap: 8px;
}
.ni__reason {
  font-size: 12px;
}
</style>
