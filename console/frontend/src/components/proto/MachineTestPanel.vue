<template>
  <div class="test-steps">
    <div class="rowline" style="padding: 8px 0">
      <label class="cbr">
        <input v-model="simulate" type="checkbox" />
        {{ t('machines.test.simulate') }}
      </label>
      <span class="spacer"></span>
      <button type="button" class="btn sm primary" :disabled="busy" @click="run">
        {{ t('machines.test.start') }}
      </button>
    </div>
    <div v-for="step in view" :key="step.key" class="tstep" :class="step.state">
      <span class="tdot"></span>
      <span>{{ step.label }}</span>
      <span class="tstat">
        {{ step.state === 'ok' ? t('machines.test.stepOk') : step.state === 'fail' ? t('machines.test.stepFail') : t('machines.test.stepRunning') }}
      </span>
    </div>
    <div v-if="registerCode" class="fhint">
      {{ t('machines.test.registerCode') }}: <span class="mono">{{ registerCode }}</span>
    </div>
    <div v-if="allOk" class="test-note-ok">{{ t('machines.test.ok') }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { useMachineStore } from '@/stores/machine'
import { testStepsToView, type TestStepIn } from '@/views/machines.viewmodel'

const props = defineProps<{ machineId: string; addr?: string }>()
const { t } = useI18n()
const store = useMachineStore()

const simulate = ref(false)
const busy = ref(false)
const steps = ref<TestStepIn[]>([])
const registerCode = ref('')

const view = computed(() => testStepsToView(steps.value))
const allOk = computed(() => steps.value.length > 0 && steps.value.every((s) => s.state === 'pass'))

async function run(): Promise<void> {
  busy.value = true
  try {
    const result = await store.runRegisterTest({
      machineId: props.machineId,
      addr: props.addr,
      simulate: simulate.value
    })
    steps.value = result.steps
    registerCode.value = result.register_code ?? ''
  } finally {
    busy.value = false
  }
}
</script>
