<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<template>
  <div class="v-ident">
    <div class="v-ident__head">
      <!-- 标题不再外链上游仓库：本页是全双工语音对话，不是 Hugging Face 展示页。 -->
      <span class="v-ident__title">{{ t('voice.identity.title') }}</span>
    </div>
    <p class="v-ident__blurb">{{ t('voice.identity.blurb') }}</p>
  </div>
</template>
