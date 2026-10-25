<script setup lang="ts">
const props = defineProps<{ open: boolean; version: string }>()
const emit = defineEmits<{ (e: 'update:open', value: boolean): void }>()

const STAGES = [
  { tag: 'VAD', job: 'detects speech', model: 'silero-vad', href: 'https://github.com/snakers4/silero-vad' },
  { tag: 'STT', job: 'transcribes it', model: 'nvidia/parakeet-tdt-1.1b', href: 'https://huggingface.co/nvidia/parakeet-tdt-1.1b' },
  { tag: 'VLM', job: 'composes the reply', model: 'google/gemma-4-31B-it', href: 'https://huggingface.co/google/gemma-4-31B-it' },
  {
    tag: 'TTS',
    job: 'speaks it back',
    model: 'Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice',
    href: 'https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice'
  }
]
</script>

<template>
  <a-modal :open="props.open" title="About" :footer="null" :width="560" @cancel="emit('update:open', false)">
    <p class="v-hint">
      Speech-to-speech is Hugging Face's open framework for real-time voice agents. Rather than one end-to-end model, it
      chains four open models from the Hub, so any stage can be swapped or run locally.
    </p>
    <a class="v-account__link" href="https://github.com/huggingface/speech-to-speech" target="_blank" rel="noopener">
      View the project on GitHub
    </a>

    <p class="v-pipe__title">The pipeline</p>
    <ol class="v-pipe">
      <li class="v-pipe__end">You speak</li>
      <li v-for="stage in STAGES" :key="stage.tag" class="v-pipe__stage">
        <span class="v-pipe__tag">{{ stage.tag }}</span>
        <span class="v-pipe__job">{{ stage.job }}</span>
        <a :href="stage.href" target="_blank" rel="noopener">{{ stage.model }}</a>
      </li>
      <li class="v-pipe__end">The orb replies</li>
    </ol>

    <p class="v-about__version">Version {{ props.version || 'unknown' }}</p>
  </a-modal>
</template>
