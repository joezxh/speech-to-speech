<script setup lang="ts">
const emit = defineEmits<{ (e: 'about'): void }>()
const REPO = 'https://github.com/huggingface/speech-to-speech'
</script>

<template>
  <div class="v-ident">
    <div class="v-ident__head">
      <a class="v-ident__title" :href="REPO" target="_blank" rel="noopener">Hugging Face Realtime</a>
      <button class="v-icon v-icon--sm" title="About this space" aria-label="About this space" @click="emit('about')">
        <svg class="v-i" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-info" /></svg>
      </button>
    </div>
    <p class="v-ident__blurb">An open, real-time voice chat built on Hugging Face's speech-to-speech stack.</p>
    <div class="v-meta">
      <span>
        <span class="v-meta__label">Powered by</span>
        <a href="https://huggingface.co/inference-endpoints" target="_blank" rel="noopener">Inference Endpoints</a>
        <span class="v-sep" aria-hidden="true">·</span>
        <a href="https://cerebras.ai" target="_blank" rel="noopener">Cerebras</a>
      </span>
      <span>
        <span class="v-meta__label">Built by</span>
        <a href="https://huggingface.co" target="_blank" rel="noopener">Hugging Face</a>
        <span class="v-sep" aria-hidden="true">·</span>
        <a href="https://huggingface.co/tfrere" target="_blank" rel="noopener">tfrere</a>
        <span class="v-sep" aria-hidden="true">·</span>
        <a href="https://huggingface.co/A-Mahla" target="_blank" rel="noopener">A-Mahla</a>
        <span class="v-sep" aria-hidden="true">·</span>
        <a href="https://huggingface.co/andito" target="_blank" rel="noopener">andito</a>
      </span>
    </div>
  </div>
</template>
