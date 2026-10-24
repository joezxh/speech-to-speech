<script setup lang="ts">
import { themeConfig } from './styles/theme'
</script>

<template>
  <a-config-provider :theme="themeConfig">
    <router-view />
  </a-config-provider>
</template>
