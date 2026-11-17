<template>
  <PModal :open="open" :title="mode === 'create' ? t('machines.form.createTitle') : t('machines.form.editTitle')" @close="emit('close')">
    <!-- 两步：① 机器字段 ② 负载声明（pipeline 锁定勾选） -->
    <div class="field">
      <label>{{ t('machines.form.machineId') }}</label>
      <input v-model="draft.machineId" class="fin" :disabled="mode === 'edit'" />
    </div>
    <div class="field">
      <label>{{ t('machines.form.addr') }}</label>
      <input v-model="draft.addr" class="fin" />
    </div>
    <div class="field">
      <label>{{ t('machines.form.gpu') }}</label>
      <input v-model="draft.gpu" class="fin" />
    </div>
    <div class="field">
      <label>{{ t('machines.form.gpuTotalGb') }}</label>
      <input v-model.number="draft.gpuTotalGb" class="fin" type="number" min="0" />
    </div>
    <div class="field">
      <label>{{ t('machines.form.clusterId') }}</label>
      <input v-model="draft.clusterId" class="fin" />
    </div>

    <h3>{{ t('machines.form.workloadsTitle') }}</h3>
    <p class="fhint">{{ t('machines.form.pipelineLocked') }}</p>
    <div class="svcbox">
      <div class="svcitem">
        <label class="cbr">
          <input type="checkbox" checked disabled />
          pipeline · {{ t('machines.form.autoDiscovered') }}
        </label>
      </div>
      <div class="svcitem" v-for="(wl, index) in draft.workloads" :key="index">
        <label class="cbr">
          <input v-model="wl.kind" class="fin" :placeholder="t('machines.form.kind')" style="max-width: 140px" />
          <input v-model="wl.model" class="fin" :placeholder="t('machines.form.model')" style="max-width: 220px" />
          <button type="button" class="btn sm ghost" @click="draft.workloads.splice(index, 1)">×</button>
        </label>
      </div>
    </div>
    <button type="button" class="btn sm" style="margin-top: 8px" @click="addWorkload">
      {{ t('machines.form.addWorkload') }}
    </button>

    <div v-if="createdCode" class="test-note-ok">
      {{ t('machines.form.created') }}<br />
      <span class="mono">{{ createdCode }}</span><br />
      <small>{{ t('machines.form.codeOnce') }}</small>
    </div>

    <div class="rowline" style="margin-top: 14px">
      <button type="button" class="btn primary" :disabled="busy" @click="submit">
        {{ mode === 'create' ? t('machines.form.submit') : t('machines.form.save') }}
      </button>
      <button type="button" class="btn ghost" @click="emit('close')">{{ t('machines.form.cancel') }}</button>
    </div>
  </PModal>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import PModal from './PModal.vue'
import { useMachineStore } from '@/stores/machine'
import type { MachineRow, WorkloadRow } from '@/views/machines.viewmodel'

const props = defineProps<{
  open: boolean
  mode: 'create' | 'edit'
  machine?: MachineRow | null
}>()

const emit = defineEmits<{ (e: 'close'): void; (e: 'saved'): void }>()
const { t } = useI18n()
const store = useMachineStore()

const draft = reactive({
  machineId: '',
  addr: '',
  gpu: '',
  gpuTotalGb: null as number | null,
  clusterId: 'default',
  workloads: [] as WorkloadRow[]
})
const busy = ref(false)
const createdCode = ref('')

watch(
  () => props.open,
  (open) => {
    if (!open) return
    createdCode.value = ''
    if (props.machine) {
      draft.machineId = props.machine.machineId
      draft.addr = props.machine.addr
      draft.gpu = props.machine.gpu
      draft.gpuTotalGb = props.machine.gpuTotalGb ?? null
      draft.clusterId = props.machine.clusterId
      draft.workloads = props.machine.workloads.filter((w) => w.kind !== 'pipeline')
    } else {
      draft.machineId = ''
      draft.addr = ''
      draft.gpu = ''
      draft.gpuTotalGb = null
      draft.clusterId = 'default'
      draft.workloads = []
    }
  }
)

function addWorkload(): void {
  draft.workloads.push({
    kind: 'llm',
    engine: '',
    model: '',
    port: null,
    listen: '',
    publicAddr: '',
    vramGb: null,
    healthPath: '',
    healthIntervalS: 30,
    note: ''
  })
}

async function submit(): Promise<void> {
  busy.value = true
  try {
    if (props.mode === 'create') {
      createdCode.value = await store.create({
        machineId: draft.machineId,
        addr: draft.addr,
        gpu: draft.gpu,
        gpuTotalGb: draft.gpuTotalGb,
        clusterId: draft.clusterId
      })
      // 负载声明（pipeline 之外的手工声明）在建档后补写。
      if (draft.workloads.length) {
        await store.saveWorkloads(draft.machineId, draft.workloads)
      }
      emit('saved')
    } else if (props.machine) {
      await store.update(props.machine.machineId, {
        addr: draft.addr,
        gpu: draft.gpu,
        gpuTotalGb: draft.gpuTotalGb,
        clusterId: draft.clusterId
      })
      await store.saveWorkloads(props.machine.machineId, [
        ...(props.machine.workloads.filter((w) => w.kind === 'pipeline')),
        ...draft.workloads
      ])
      createdCode.value = ''
      emit('close')
      emit('saved')
    }
  } finally {
    busy.value = false
  }
}
</script>
