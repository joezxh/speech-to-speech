<script setup lang="ts">
import { ref, watch } from 'vue'

import { dbToPercent, GATE_MAX_DB, GATE_OFF_DB } from '../audio/meter'
import type { VoiceSettings } from '../types'

const props = defineProps<{
  open: boolean
  serverUrl: string
  transportLocked: boolean
  voices: string[]
  inputs: Array<{ id: string; label: string }>
  outputs: Array<{ id: string; label: string }>
  settings: VoiceSettings
  connected: boolean
}>()
const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'save', value: VoiceSettings): void
  (e: 'restart'): void
}>()

const draft = ref<VoiceSettings>({ ...props.settings, tools: { ...props.settings.tools } })

// 每次打开都从 store 重取：面板是「照镜子」，不是第二个状态容器。
watch(
  () => props.open,
  (open) => {
    if (open) draft.value = { ...props.settings, tools: { ...props.settings.tools } }
  }
)

const gateLabel = () => (draft.value.noiseGateDb <= GATE_OFF_DB ? 'Off' : `${draft.value.noiseGateDb} dB`)
const gatePercent = () => dbToPercent(draft.value.noiseGateDb)

function save(): void {
  emit('save', {
    ...draft.value,
    noiseGateDb: Math.round(draft.value.noiseGateDb),
    playbackBufferMs: Math.max(0, Number(draft.value.playbackBufferMs) || 0)
  })
  emit('update:open', false)
}
</script>

<template>
  <a-modal :open="props.open" title="Settings" :width="520" ok-text="Save" @ok="save" @cancel="emit('update:open', false)">
    <a-form layout="vertical">
      <a-form-item label="Speech-to-speech server URL">
        <a-input :value="props.serverUrl" disabled />
        <small class="v-hint">Same origin as this page. The address is pinned by the deployment, not typed here.</small>
      </a-form-item>

      <a-form-item label="Transport">
        <a-select v-model:value="draft.transport" :disabled="props.transportLocked">
          <a-select-option value="ws">WebSocket</a-select-option>
          <a-select-option value="webrtc">WebRTC</a-select-option>
        </a-select>
        <small class="v-hint">
          {{
            props.transportLocked
              ? 'Locked to WebSocket: this deployment pins the upstream URL.'
              : 'How audio travels to the server. Applies on the next conversation.'
          }}
        </small>
      </a-form-item>

      <a-form-item label="Voice">
        <a-select v-model:value="draft.voice">
          <a-select-option v-for="name in props.voices" :key="name" :value="name">{{ name }}</a-select-option>
        </a-select>
      </a-form-item>

      <a-form-item label="Microphone">
        <a-select v-model:value="draft.audioInputId">
          <a-select-option value="">System default</a-select-option>
          <a-select-option v-for="device in props.inputs" :key="device.id" :value="device.id">{{ device.label }}</a-select-option>
        </a-select>
        <small class="v-hint">Applies on the next conversation (or Restart).</small>
      </a-form-item>

      <a-form-item label="Speakers">
        <a-select v-model:value="draft.audioOutputId">
          <a-select-option value="">System default</a-select-option>
          <a-select-option v-for="device in props.outputs" :key="device.id" :value="device.id">{{ device.label }}</a-select-option>
        </a-select>
        <small class="v-hint">Where assistant audio plays. Chrome/Edge support switching outputs.</small>
      </a-form-item>

      <a-form-item label="Faster interruptions">
        <a-select :value="draft.localVad ? 'on' : 'off'" @change="(value: string) => (draft.localVad = value === 'on')">
          <a-select-option value="on">On</a-select-option>
          <a-select-option value="off">Off</a-select-option>
        </a-select>
        <small class="v-hint">Lowers the assistant's volume when you start speaking. Applies on the next conversation.</small>
      </a-form-item>

      <a-form-item label="Playback startup buffer (ms)">
        <a-input-number v-model:value="draft.playbackBufferMs" :min="0" :step="50" class="v-wide" />
        <small class="v-hint">
          WebSocket only. 0 starts immediately; larger values delay playback to absorb delivery gaps.
        </small>
      </a-form-item>

      <a-form-item :label="`Noise gate  ·  ${gateLabel()}`">
        <a-slider
          v-model:value="draft.noiseGateDb"
          :min="GATE_OFF_DB"
          :max="GATE_MAX_DB"
          :tip-formatter="(value: number) => (value <= GATE_OFF_DB ? 'Off' : `${value} dB`)"
        />
        <div class="v-gate-meter" aria-hidden="true"><span :style="{ width: `${gatePercent()}%` }" /></div>
        <div class="v-gate-ends"><span>Off</span><span>−3 dB</span></div>
        <small class="v-hint">
          Mutes the mic below the handle so room noise isn't sent. Slide fully left to turn it off; the arc around the
          mic shows your live input while in a call.
        </small>
      </a-form-item>

      <a-form-item label="Instructions">
        <a-textarea v-model:value="draft.instructions" :rows="5" placeholder="You are a friendly voice assistant..." />
      </a-form-item>

      <a-form-item>
        <a-button class="v-wide" :disabled="!props.connected" @click="emit('restart')">
          Restart conversation with these settings
        </a-button>
        <small class="v-hint">
          {{
            props.connected
              ? 'Drops this call and reconnects with the settings above.'
              : 'Connect first, then come back here to apply live changes.'
          }}
        </small>
      </a-form-item>
    </a-form>
  </a-modal>
</template>
