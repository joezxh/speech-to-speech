<script setup lang="ts">
import { computed, reactive, ref } from 'vue'

import { AppError } from '@/api/client'
import { updateSessions } from '@/api/sessions'
import ErrorBanner from '@/components/ErrorBanner.vue'
import { useConsoleStore } from '@/stores/console'
import { translate } from '@/utils/error'
import { buildSessionPatch } from '@/utils/session-patch'
import type { SessionScope, SessionUpdateResult } from '@/types/session'

const consoleStore = useConsoleStore()

type Tri = 'keep' | 'on' | 'off'

const TRI_OPTIONS: Array<{ value: Tri; label: string }> = [
  { value: 'keep', label: '不修改' },
  { value: 'on', label: '开启' },
  { value: 'off', label: '关闭' }
]

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
  if (form.scope === 'all' && form.targetText.trim()) list.push('scope=all 不需要 target')
  if (form.scope === 'pipeline' && !Number.isInteger(target.value)) {
    list.push('target 必须是 unit 序号（整数）')
  }
  if (form.scope === 'session' && !form.targetText.trim()) list.push('target 必须是 session id')
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
    failure.value = error instanceof AppError ? error : new AppError('unknown', '热更新失败，请重试')
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <div class="sessions">
    <a-alert message="热更新只改活跃连接，不写任何文件">
      <template #description>
        <ul class="sessions__rules">
          <li>只影响当前活跃连接；新连接仍读 <code>init_chat_prompt</code>，与这里下发的值可能不一致。</li>
          <li>空闲 unit 没有连接可下发；改默认人设必须同时改 YAML 并发布，否则重启后又回到旧默认。</li>
          <li>不支持 <code>transcription</code> 类型会话，必须是 <code>realtime</code> 会话。</li>
          <li><code>language</code> 必须被活跃后端支持；<code>auto</code> 需要后端支持自动重置，否则 400。</li>
          <li>不提供 <code>model</code> 与 <code>audio.output.voice</code>：它们在协议里只是回显，下发也不会改变音色或模型。</li>
        </ul>
      </template>
    </a-alert>

    <a-alert
      v-if="tokenMissing"
      type="warning"
      show-icon
      message="控制器未配置 S2S_INTERNAL_TOKEN，链路 B 不可用"
      description="在 config/prod.env 里设置 S2S_INTERNAL_TOKEN 后 docker compose up -d --force-recreate pipeline。"
    />

    <a-form layout="vertical" class="sessions__form">
      <a-form-item label="作用域">
        <a-radio-group v-model:value="form.scope" button-style="solid">
          <a-radio-button value="all">全部活跃连接</a-radio-button>
          <a-radio-button value="pipeline">单个 unit</a-radio-button>
          <a-radio-button value="session">单条会话</a-radio-button>
        </a-radio-group>
      </a-form-item>

      <a-form-item v-if="form.scope !== 'all'" :label="form.scope === 'pipeline' ? 'unit 序号' : 'session id'">
        <a-input v-model:value="form.targetText" :placeholder="form.scope === 'pipeline' ? '0' : '复现实时转写里的 session id'" />
      </a-form-item>

      <a-form-item label="instructions（人设）">
        <a-textarea v-model:value="form.instructions" :rows="3" placeholder="留空即不修改" />
      </a-form-item>

      <a-form-item label="turn_detection.create_response（自动应答）">
        <a-select v-model:value="form.createResponse" :options="TRI_OPTIONS" style="width: 160px" />
      </a-form-item>

      <a-form-item label="turn_detection.interrupt_response（允许打断）">
        <a-select v-model:value="form.interruptResponse" :options="TRI_OPTIONS" style="width: 160px" />
      </a-form-item>

      <a-form-item label="transcription.language">
        <a-input v-model:value="form.language" placeholder="auto / zh / en —— 必须是活跃后端支持的值" />
      </a-form-item>

      <a-form-item label="extensions（JSON，留空即不修改）">
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
        下发到活跃会话
      </a-button>
    </a-form>

    <a-card v-if="result" size="small" title="下发结果">
      <p>
        已更新 <strong>{{ result.updated.length }}</strong> 条连接；失败
        <strong>{{ result.failed.length }}</strong> 条。审计号 <code>{{ result.auditId }}</code>
      </p>
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
