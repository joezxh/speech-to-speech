<script setup lang="ts">
const props = defineProps<{
  open: boolean
  searchAvailable: boolean
  serverKey: boolean
  webSearch: boolean
  camera: boolean
  searchKey: string
}>()
const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'update:webSearch', value: boolean): void
  (e: 'update:camera', value: boolean): void
  (e: 'update:searchKey', value: string): void
}>()
</script>

<template>
  <a-modal :open="props.open" title="Tools" :footer="null" @cancel="emit('update:open', false)">
    <p class="v-hint">Let the assistant act during the conversation. Changes apply live.</p>

    <div class="v-tool">
      <div class="v-tool__info">
        <span class="v-tool__name">Web search</span>
        <span class="v-tool__desc">Look things up on Google, via Serper.</span>
      </div>
      <a-switch
        :checked="props.webSearch"
        :disabled="!props.searchAvailable"
        @change="(value: boolean) => emit('update:webSearch', value)"
      />
    </div>

    <!-- 服务端已握 key 时既不回显也不受输入：B5 -->
    <div class="v-field">
      <label class="v-field__label" for="v-search-key">Search API key</label>
      <a-input-password
        id="v-search-key"
        :value="props.serverKey ? '' : props.searchKey"
        :disabled="props.serverKey"
        :placeholder="props.serverKey ? '••••••••  · provided by the server' : 'Serper API key (stays in this browser)'"
        autocomplete="off"
        @change="(event: Event) => emit('update:searchKey', (event.target as HTMLInputElement).value)"
      />
      <small class="v-hint">
        {{
          props.serverKey
            ? 'Ready. The search key is held server-side and never sent to the page.'
            : props.searchAvailable
              ? 'Ready.'
              : 'This deployment has no search key. Add your own above to use it anyway.'
        }}
      </small>
    </div>

    <div class="v-tool v-tool--sep">
      <div class="v-tool__info">
        <span class="v-tool__name">Camera</span>
        <span class="v-tool__desc">Let the assistant see through your webcam.</span>
      </div>
      <a-switch :checked="props.camera" @change="(value: boolean) => emit('update:camera', value)" />
    </div>
    <small class="v-hint">A live preview shows bottom-left while the camera is on.</small>
  </a-modal>
</template>
