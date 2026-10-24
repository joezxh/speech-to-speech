<script setup lang="ts">
import { computed } from 'vue'

import type { AppError } from '@/api/client'

const props = defineProps<{ error: AppError | null }>()

const text = computed(() => props.error?.message ?? '')
const requestId = computed(() => props.error?.requestId ?? '')
</script>

<template>
  <a-alert v-if="text" class="error-banner" type="error" show-icon :message="text">
    <template v-if="requestId" #description>
      <span class="error-banner__id">requestId: {{ requestId }}</span>
    </template>
  </a-alert>
</template>
