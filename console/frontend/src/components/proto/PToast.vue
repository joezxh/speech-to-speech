<template>
  <div class="toast" :class="{ show: state.visible }">{{ state.msg }}</div>
</template>

<script setup lang="ts">
import { useToast } from '../../composables/useToast'

const { state } = useToast()
</script>
