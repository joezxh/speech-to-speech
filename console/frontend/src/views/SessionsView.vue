<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { AppError } from '@/api/client'
import { updateSessions } from '@/api/sessions'
import ErrorBanner from '@/components/ErrorBanner.vue'
import { useConsoleStore } from '@/stores/console'
import { translate } from '@/utils/error'
import { buildSessionPatch } from '@/utils/session-patch'
import type { SessionScope, SessionUpdateResult } from '@/types/session'

const { t } = useI18n()
const consoleStore = useConsoleStore()

type Tri = 'keep' | 'on' | 'off'

const TRI_OPTIONS = computed(() => [
  { value: 'keep', label: t('sessionUpdate.tri.keep') },
  { value: 'on', label: t('sessionUpdate.tri.on') },
  { value: 'off', label: t('sessionUpdate.tri.off') }
])

// 模板里的引号转义不被 Vue 属性解析器接受，所以示例 JSON 走绑定。
const EXTENSIONS_PLACEHOLDER = '{"speech_to_speech":{"input_audio_transcription":{"snapshot":true}}}'

const form = reactive({
  scope: 'all' as SessionScope,
  targetText: '',
  instructions: '',
  createResponse: 'keep' as Tri,
  interruptResponse: 'keep' as Tri,
  language: '',
  extensions: ''
})

const pending = ref(false)
const failure = ref<AppError | null>(null)
const result = ref<SessionUpdateResult | null>(null)

function tri(value: Tri): boolean | null {
  return value === 'keep' ? null : value === 'on'
}

const target = computed<number | string | null>(() => {
  const raw = form.targetText.trim()
  if (form.scope === 'all' || !raw) return null
  return form.scope === 'pipeline' ? Number(raw) : raw
})

const preview = computed(() =>
  buildSessionPatch({
    instructions: form.instructions,
    createResponse: tri(form.createResponse),
    interruptResponse: tri(form.interruptResponse),
    language: form.language,
    extensions: form.extensions
  })
)

const problems = computed<string[]>(() => {
  const list = [...preview.value.problems]
  if (form.scope === 'all' && form.targetText.trim()) list.push(t('sessionUpdate.problemScopeAllNoTarget'))
  if (form.scope === 'pipeline' && !Number.isInteger(target.value)) {
    list.push(t('sessionUpdate.problemPipelineTarget'))
  }
  if (form.scope === 'session' && !form.targetText.trim()) list.push(t('sessionUpdate.problemSessionTarget'))
  return list
})

// A.11: `internalTokenConfigured=false` means chain B cannot work at all, so the
// button is disabled and the variable name is shown instead of a 502 toast.
const tokenMissing = computed(() => consoleStore.status?.internalTokenConfigured === false)

async function submit(): Promise<void> {
  failure.value = null
  result.value = null
  pending.value = true
  try {
    result.value = await updateSessions({
      scope: form.scope,
      target: target.value,
      session: preview.value.session
    })
  } catch (error) {
    failure.value = error instanceof AppError ? error : new AppError('unknown', t('sessionUpdate.updateFailed'))
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <div class="sessions">
    <a-alert :message="t('sessionUpdate.rulesTitle')">
      <template #description>
        <ul class="sessions__rules">
          <li>{{ t('sessionUpdate.rules.r1') }}</li>
          <li>{{ t('sessionUpdate.rules.r2') }}</li>
          <li>{{ t('sessionUpdate.rules.r3') }}</li>
          <li>{{ t('sessionUpdate.rules.r4') }}</li>
          <li>{{ t('sessionUpdate.rules.r5') }}</li>
        </ul>
      </template>
    </a-alert>

    <a-alert
      v-if="tokenMissing"
      type="warning"
      show-icon
      :message="t('sessionUpdate.tokenMissingTitle')"
      :description="t('sessionUpdate.tokenMissingDesc')"
    />

    <a-form layout="vertical" class="sessions__form">
      <a-form-item :label="t('sessionUpdate.scopeLabel')">
        <a-radio-group v-model:value="form.scope" button-style="solid">
          <a-radio-button value="all">{{ t('sessionUpdate.scope.all') }}</a-radio-button>
          <a-radio-button value="pipeline">{{ t('sessionUpdate.scope.pipeline') }}</a-radio-button>
          <a-radio-button value="session">{{ t('sessionUpdate.scope.session') }}</a-radio-button>
        </a-radio-group>
      </a-form-item>

      <a-form-item v-if="form.scope !== 'all'" :label="form.scope === 'pipeline' ? t('sessionUpdate.targetLabelPipeline') : t('sessionUpdate.targetLabelSession')">
        <a-input v-model:value="form.targetText" :placeholder="form.scope === 'pipeline' ? '0' : t('sessionUpdate.targetPlaceholderSession')" />
      </a-form-item>

      <a-form-item :label="t('sessionUpdate.instructionsLabel')">
        <a-textarea v-model:value="form.instructions" :rows="3" :placeholder="t('sessionUpdate.blankPlaceholder')" />
      </a-form-item>

      <a-form-item :label="t('sessionUpdate.createResponseLabel')">
        <a-select v-model:value="form.createResponse" :options="TRI_OPTIONS" style="width: 160px" />
      </a-form-item>

      <a-form-item :label="t('sessionUpdate.interruptResponseLabel')">
        <a-select v-model:value="form.interruptResponse" :options="TRI_OPTIONS" style="width: 160px" />
      </a-form-item>

      <a-form-item label="transcription.language">
        <a-input v-model:value="form.language" :placeholder="t('sessionUpdate.languagePlaceholder')" />
      </a-form-item>

      <a-form-item :label="t('sessionUpdate.extensionsLabel')">
        <a-textarea
          v-model:value="form.extensions"
          :rows="3"
          :placeholder="EXTENSIONS_PLACEHOLDER"
        />
      </a-form-item>

      <a-alert v-if="problems.length" type="warning" show-icon :message="problems.join('；')" />

      <ErrorBanner :error="failure" />

      <a-button
        type="primary"
        :loading="pending"
        :disabled="tokenMissing || problems.length > 0"
        @click="submit"
      >
        {{ t('sessionUpdate.submit') }}
      </a-button>
    </a-form>

    <a-card v-if="result" size="small" :title="t('sessionUpdate.resultTitle')">
      <p>{{ t('sessionUpdate.resultSummary', { updated: result.updated.length, failed: result.failed.length, auditId: result.auditId }) }}</p>
      <a-list v-if="result.failed.length" size="small" bordered :data-source="result.failed">
        <template #renderItem="{ item }">
          <a-list-item><code>{{ item.sessionId }}</code> — {{ translate(item.error) }}</a-list-item>
        </template>
      </a-list>
      <a-alert type="info" :message="result.hint" />
    </a-card>
  </div>
</template>

<style scoped lang="less">
.sessions {
  display: flex;
  flex-direction: column;
  gap: 12px;

  &__rules {
    margin: 0;
    padding-left: 18px;
  }

  &__form {
    max-width: 640px;
  }
}
</style>
