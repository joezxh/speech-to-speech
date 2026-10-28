<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { AppError } from '@/api/client'
import ErrorBanner from '@/components/ErrorBanner.vue'
import VoiceAudition from '@/components/VoiceAudition.vue'
import { useVoicesStore } from '@/stores/voices'
import type { PrecomputeError, VoiceRow, VoiceSource } from '@/types/voice-library'
import { precomputeText, sourceLabel } from '@/utils/voice-text'
import { toWav } from '@/utils/wav'

const props = defineProps<{
  open: boolean
  /** 当前后端（`qwen3` / `openai_compatible` / `kokoro`）。 */
  backend: string
  /** 该后端支持的来源，来自 `GET /voices/backends` 的 `sources`。 */
  sources: VoiceSource[]
}>()

const emit = defineEmits<{
  created: [voice: VoiceRow]
  'update:open': [open: boolean]
}>()

const store = useVoicesStore()
const { t } = useI18n()

const STEPS = computed(() => [
  { title: t('voices.create.steps.source') },
  { title: t('voices.create.steps.audio') },
  { title: t('voices.create.steps.audition') },
  { title: t('voices.create.steps.name') }
])

const step = ref(0)
const source = ref<VoiceSource>('builtin')
const name = ref('')
const refText = ref('')
const instruct = ref('')
const retentionDays = ref(30)
const consent = ref(false)
const audio = ref<Blob | null>(null)
const audioUrl = ref('')
const durationMs = ref(0)
const trimStartMs = ref(0)
const trimEndMs = ref(0)
const recording = ref(false)
const error = ref<AppError | null>(null)
const createdId = ref('')
const precompute = ref<{ stage: string; progress: number; errorCode: string | null } | null>(null)
let recorder: MediaRecorder | null = null
let recorderChunks: Blob[] = []
let poller: number | null = null

watch(
  () => props.open,
  (open) => {
    if (!open) return
    reset()
  },
  { immediate: true }
)

watch(
  () => props.sources,
  (sources) => {
    if (!sources.includes(source.value)) source.value = sources[0] ?? 'builtin'
  },
  { immediate: true }
)

function reset(): void {
  step.value = 0
  source.value = props.sources[0] ?? 'builtin'
  name.value = ''
  refText.value = ''
  instruct.value = ''
  retentionDays.value = 30
  consent.value = false
  error.value = null
  createdId.value = ''
  precompute.value = null
  clearAudio()
  stopPolling()
}

function clearAudio(): void {
  if (audioUrl.value) URL.revokeObjectURL(audioUrl.value)
  audio.value = null
  audioUrl.value = ''
  durationMs.value = 0
  trimStartMs.value = 0
  trimEndMs.value = 0
}

/** 只接受 WAV：`<input>` 的 accept 只是提示，后端仍会用 `wave` 再校验一次。 */
function onPick(file: File): boolean {
  clearAudio()
  audio.value = file
  audioUrl.value = URL.createObjectURL(file)
  void probeDuration(audioUrl.value)
  return false
}

function probeDuration(url: string): void {
  const element = new Audio()
  element.addEventListener('loadedmetadata', () => {
    durationMs.value = Number.isFinite(element.duration) ? Math.round(element.duration * 1000) : 0
    trimEndMs.value = durationMs.value
  })
  element.src = url
}

async function startRecording(): Promise<void> {
  error.value = null
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } })
    recorderChunks = []
    recorder = new MediaRecorder(stream)
    recorder.ondataavailable = (event: BlobEvent) => {
      if (event.data.size > 0) recorderChunks.push(event.data)
    }
    recorder.onstop = async () => {
      stream.getTracks().forEach((track) => track.stop())
      recording.value = false
      // MediaRecorder 给的是 webm/opus，后端只收 PCM16 WAV，所以这里必须转一遍。
      const wav = await toWav(new Blob(recorderChunks, { type: recorder?.mimeType ?? 'audio/webm' }))
      clearAudio()
      audio.value = wav
      audioUrl.value = URL.createObjectURL(wav)
      probeDuration(audioUrl.value)
    }
    recorder.start()
    recording.value = true
  } catch (caught) {
    error.value = caught instanceof AppError ? caught : new AppError('voice_audio_invalid', t('voices.create.micDenied'))
  }
}

function stopRecording(): void {
  recorder?.stop()
}

const isClone = computed(() => source.value === 'clone')
const needsAudio = computed(() => source.value === 'clone')

/** §3.11.2 步骤 4：克隆必须逐字转写，非空才允许保存。 */
const refTextMissing = computed(() => isClone.value && refText.value.trim().length === 0)
const audioMissing = computed(() => needsAudio.value && audio.value === null)
const instructMissing = computed(() => source.value === 'design' && instruct.value.trim().length === 0)

/**
 * 计划原文的 gate 是 `precompute.stage === 'done'`——那是「先算后命名」的顺序。
 * A.18 只有一个 `POST /voices`，预计算在创建之后才跑，所以等价的 gate 是
 * 「必填项齐 + 已勾选生物特征授权」，预计算进度在提交后单独呈现。
 */
const canSave = computed(
  () => name.value.trim().length > 0 && consent.value && !refTextMissing.value && !audioMissing.value && !instructMissing.value
)

function next(): void {
  if (step.value === 1 && (audioMissing.value || refTextMissing.value || instructMissing.value)) {
    error.value = new AppError('invalid_parameter', t('voices.create.requiredMissing'))
    return
  }
  error.value = null
  step.value = Math.min(STEPS.value.length - 1, step.value + 1)
}

function back(): void {
  error.value = null
  step.value = Math.max(0, step.value - 1)
}

async function save(): Promise<void> {
  error.value = null
  const row = await store.create({
    name: name.value.trim(),
    source: source.value,
    backend: props.backend,
    refText: isClone.value ? refText.value.trim() : undefined,
    instruct: source.value === 'design' ? instruct.value.trim() : undefined,
    retentionDays: retentionDays.value,
    trimStartMs: trimStartMs.value,
    trimEndMs: trimEndMs.value > 0 ? trimEndMs.value : undefined,
    audio: audio.value
  })
  if (row === null) {
    error.value = store.error
    return
  }
  createdId.value = row.id
  precompute.value = row.precompute ?? { stage: 'queued', progress: 0, errorCode: null }
  emit('created', row)
  startPolling()
}

/** 预计算最长 300 s（`voice_precompute_timeout_s`），2 s 一次足够，且只打单行。 */
function startPolling(): void {
  stopPolling()
  poller = window.setInterval(() => {
    void poll()
  }, 2000)
}

function stopPolling(): void {
  if (poller !== null) {
    window.clearInterval(poller)
    poller = null
  }
}

async function poll(): Promise<void> {
  if (!createdId.value) return
  const row = await store.refreshOne(createdId.value)
  if (row === null) return
  precompute.value = row.precompute ?? precompute.value
  if (row.status !== 'precomputing') stopPolling()
}

const errorText = computed(() => precomputeText(precompute.value?.errorCode as PrecomputeError | null))

/** 重试只重跑预计算——A.18 没有重试端点，所以让用户重新上传同一段音频是不诚实的。 */
const canRetry = computed(() => precompute.value?.errorCode === 'timeout' || precompute.value?.errorCode === 'oom_cpu')

function close(): void {
  stopPolling()
  emit('update:open', false)
}
</script>

<template>
  <a-modal :open="open" :title="t('voices.create.title')" :width="640" :footer="null" @cancel="close">
    <a-steps :current="step" size="small" :items="STEPS" class="voice-create__steps" />

    <ErrorBanner :error="error" />

    <div v-if="createdId" class="voice-create__progress">
      <a-progress
        :percent="precompute?.progress ?? 0"
        :status="precompute?.errorCode ? 'exception' : precompute?.stage === 'done' ? 'success' : 'active'"
      />
      <p class="voice-create__stage">{{ t('voices.create.stage', { stage: precompute?.stage ?? 'queued' }) }}</p>
      <a-alert v-if="errorText" type="error" show-icon :message="errorText" />
      <p v-if="canRetry" class="voice-create__hint">{{ t('voices.create.retryHint') }}</p>
      <div class="voice-create__actions">
        <a-button type="primary" @click="close">{{ t('voices.create.done') }}</a-button>
      </div>
    </div>

    <template v-else>
      <section v-if="step === 0" class="voice-create__body">
        <a-radio-group v-model:value="source" button-style="solid">
          <a-radio-button v-for="item in sources" :key="item" :value="item">
            {{ sourceLabel(item) }}
          </a-radio-button>
        </a-radio-group>
        <p class="voice-create__hint">
          {{ t('voices.create.backendSupport', { backend, list: sources.length ? sources.map((item) => sourceLabel(item)).join(' / ') : t('voices.create.backendNone') }) }}
        </p>
      </section>

      <section v-else-if="step === 1" class="voice-create__body">
        <template v-if="isClone">
          <div class="voice-create__row">
            <a-upload :before-upload="onPick" :show-upload-list="false" accept="audio/wav,.wav">
              <a-button>{{ t('voices.create.uploadWav') }}</a-button>
            </a-upload>
            <a-button v-if="!recording" @click="startRecording">{{ t('voices.create.record') }}</a-button>
            <a-button v-else danger @click="stopRecording">{{ t('voices.create.stopRecord') }}</a-button>
            <span v-if="audio" class="voice-create__picked">{{ t('voices.create.selected', { sec: (durationMs / 1000).toFixed(2) }) }}</span>
          </div>
          <p class="voice-create__hint">
            {{ t('voices.create.audioFormatHint') }}
          </p>
          <a-textarea
            v-model:value="refText"
            :rows="3"
            :placeholder="t('voices.create.refTextPlaceholder')"
          />
          <a-alert v-if="refTextMissing" type="warning" show-icon :message="t('voices.create.refTextRequired')" />
        </template>

        <template v-else-if="source === 'design'">
          <a-textarea
            v-model:value="instruct"
            :rows="3"
            :placeholder="t('voices.create.instructPlaceholder')"
          />
          <a-alert v-if="instructMissing" type="warning" show-icon :message="t('voices.create.instructRequired')" />
        </template>

        <p v-else class="voice-create__hint">{{ t('voices.create.builtinHint') }}</p>
      </section>

      <section v-else-if="step === 2" class="voice-create__body">
        <VoiceAudition
          v-if="audioUrl"
          :src="audioUrl"
          :duration-ms="durationMs"
          :trim-start-ms="trimStartMs"
          :trim-end-ms="trimEndMs"
          @update:trim="(start: number, end: number) => { trimStartMs = start; trimEndMs = end }"
        />
        <p v-else class="voice-create__hint">{{ t('voices.create.noAudioStep') }}</p>
      </section>

      <section v-else class="voice-create__body">
        <a-input v-model:value="name" :placeholder="t('voices.create.namePlaceholder')" :maxlength="64" />
        <label class="voice-create__row">
          <span class="voice-create__hint">{{ t('voices.create.retentionDays') }}</span>
          <a-input-number v-model:value="retentionDays" :min="1" :max="180" />
        </label>
        <a-checkbox v-model:checked="consent">
          {{ t('voices.create.consent') }}
        </a-checkbox>
        <a-alert v-if="!consent" type="warning" show-icon :message="t('voices.create.consentRequired')" />
      </section>

      <div class="voice-create__actions">
        <a-button v-if="step > 0" @click="back">{{ t('voices.create.back') }}</a-button>
        <a-button v-if="step < STEPS.length - 1" type="primary" @click="next">{{ t('voices.create.next') }}</a-button>
        <a-button v-else type="primary" :disabled="!canSave" :loading="store.saving" @click="save">{{ t('voices.create.save') }}</a-button>
      </div>
    </template>
  </a-modal>
</template>

<style scoped lang="less">
.voice-create {
  &__steps {
    margin-bottom: 16px;
  }

  &__body {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  &__row {
    align-items: center;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  &__picked {
    color: #8b93a7;
    font-size: 12px;
  }

  &__hint {
    color: #8b93a7;
    font-size: 12px;
    margin: 0;
  }

  &__actions {
    display: flex;
    gap: 8px;
    justify-content: flex-end;
    margin-top: 16px;
  }

  &__progress {
    margin-top: 8px;
  }

  &__stage {
    color: #8b93a7;
    font-size: 12px;
    margin: 4px 0 8px;
  }
}
</style>
