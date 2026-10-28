<script setup lang="ts">
import enUS from 'ant-design-vue/es/locale/en_US'
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import { computed } from 'vue'

import { useLocaleStore } from './stores/locale'
import { themeConfig } from './styles/theme'

const localeStore = useLocaleStore()
const antLocale = computed(() => (localeStore.locale === 'zh-CN' ? zhCN : enUS))
</script>

<template>
  <a-config-provider :theme="themeConfig" :locale="antLocale">
    <router-view />
  </a-config-provider>
</template>
