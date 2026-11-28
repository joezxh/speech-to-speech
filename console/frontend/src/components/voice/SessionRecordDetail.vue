<template>
  <div class="srd">
    <div class="srd__head">
      <div class="srd__titlebox">
        <input v-if="editingTitle" v-model="titleDraft" class="fin srd__title-input" @keyup.enter="saveTitle" />
        <h3 v-else class="srd__title">{{ detail?.title || t('sessions.untitled') }}</h3>
        <div class="srd__badges">
          <PBadge :kind="detail?.state === 'failed' ? 'bad' : 'ok'" :text="detail?.state ?? ''" />
          <PBadge kind="accent" :text="t('sessions.turnsBadge', { n: detail?.turns ?? 0 })" />
          <PBadge kind="ro" :text="fmtDuration(detail?.durationMs ?? 0)" />
          <PBadge v-if="detail?.ttfaMs != null" kind="hot" :text="`TTFA ${detail.ttfaMs}ms`" />
        </div>
      </div>
      <div class="srd__headbtns">
        <button v-if="!editingTitle" type="button" class="btn sm" @click="startEditTitle">
          {{ t('common.edit') }}
        </button>
        <button v-else type="button" class="btn sm primary" @click="saveTitle">
          {{ t('common.save') }}
        </button>
        <button type="button" class="btn sm danger" @click="removeRecord">
          {{ t('sessions.deleteRecord') }}
        </button>
        <button type="button" class="btn sm ghost" @click="emit('close')">×</button>
      </div>
    </div>

    <div class="srd__meta">
      <span class="mono">{{ detail?.pipelineSessionId || '—' }}</span>
      <span v-if="detail?.node" class="srd__node">{{ detail.instanceId || detail.node }}</span>
      <span class="srd__time">{{ detail?.createdAt }}</span>
    </div>
    <p v-if="detail?.note" class="srd__note">{{ detail.note }}</p>

    <div class="srd__toolbar">
      <input
        v-model="keyword"
        class="fin"
        :placeholder="t('sessions.messageSearch')"
        style="max-width: 220px"
      />
      <button type="button" class="btn sm danger" :disabled="!detail?.messages?.length" @click="clearAll">
        {{ t('sessions.clearMessages') }}
      </button>
    </div>

    <div class="srd__msgs">
      <div v-for="row in visibleRows" :key="row.msg.id" class="srd__msg" :data-role="row.msg.role">
        <div class="srd__msghead">
          <PBadge kind="equal" :text="row.msg.role" />
          <small class="srd__msgtime">#{{ row.msg.ordinal }} · {{ row.msg.createdAt }}</small>
          <span class="srd__msgbtns">
            <button type="button" class="btn sm" @click="startEdit(row.msg)">{{ t('common.edit') }}</button>
            <button type="button" class="btn sm danger" @click="removeMsg(row.msg.id)">{{ t('common.delete') }}</button>
          </span>
        </div>
        <textarea
          v-if="editingId === row.msg.id"
          v-model="contentDraft"
          class="fin srd__editor"
          rows="3"
          @keydown.ctrl.enter.prevent="saveMsg(row.msg.id)"
        ></textarea>
        <p v-else class="srd__content">{{ row.msg.content }}</p>
        <div v-if="row.clip" class="srd__clip">
          <ClipPill
            :seed="clipKey(row.clip)"
            :duration-ms="row.clip.durationMs"
            :disabled="broken.has(clipKey(row.clip))"
            :playing="playingKey === clipKey(row.clip)"
            @play="onPlayClip(row.clip)"
          />
        </div>
        <div v-if="editingId === row.msg.id" class="rowline srd__editorbtns">
          <button type="button" class="btn sm primary" @click="saveMsg(row.msg.id)">{{ t('common.save') }}</button>
          <button type="button" class="btn sm ghost" @click="editingId = null">{{ t('common.cancel') }}</button>
        </div>
      </div>
      <p v-if="!visibleRows.length" class="srd__empty">{{ t('sessions.noMessages') }}</p>
    </div>
    <audio ref="audioRef" class="srd__player" @ended="onEnded" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import PBadge from '@/components/proto/PBadge.vue'
import ClipPill from '@/components/voice/ClipPill.vue'
import { useClipPlayback } from '@/components/voice/useClipPlayback'
import { useConfirm } from '@/composables/useConfirm'
import type { SessionClipRow, SessionMessageRow } from '@/api/sessionRecords'
import { useSessionRecordsStore } from '@/stores/sessionRecords'

const props = defineProps<{ recordId: number }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'changed'): void }>()

const { t } = useI18n()
const store = useSessionRecordsStore()
const { ask } = useConfirm()

const editingTitle = ref(false)
const titleDraft = ref('')
const editingId = ref<number | null>(null)
const contentDraft = ref('')
const keyword = ref('')

const detail = computed(() => store.detail)

// 片段回放：clips 按 messageOrdinal（= 保存 payload 的 0-based 下标）对齐消息行。
const { broken, playingKey, audioRef, play, onEnded } = useClipPlayback()

const clipByOrdinal = computed<Map<number, SessionClipRow>>(() => {
  const map = new Map<number, SessionClipRow>()
  for (const clip of detail.value?.clips ?? []) map.set(clip.messageOrdinal, clip)
  return map
})

function clipKey(clip: SessionClipRow): string {
  return `m:${clip.id}`
}

function onPlayClip(clip: SessionClipRow): void {
  if (!detail.value) return
  void play({ key: clipKey(clip), recordId: detail.value.id, clipId: clip.id })
}

watch(
  () => props.recordId,
  (id) => {
    editingTitle.value = false
    editingId.value = null
    keyword.value = ''
    if (id) void store.openDetail(id)
  },
  { immediate: true }
)

/** 消息内搜索：标题关键词过滤（详情一次取全，本地过滤）。 */
const visibleMessages = computed<SessionMessageRow[]>(() => {
  const messages = detail.value?.messages ?? []
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return messages
  return messages.filter((m) => m.content.toLowerCase().includes(kw))
})

/** 消息行 + 对齐的音频片段（clip.messageOrdinal = 保存 payload 的 0-based 下标）。 */
const visibleRows = computed(() =>
  visibleMessages.value.map((msg) => ({ msg, clip: clipByOrdinal.value.get(msg.ordinal) }))
)

function fmtDuration(ms: number): string {
  if (ms <= 0) return '0s'
  const totalSec = Math.round(ms / 1000)
  if (totalSec < 60) return `${totalSec}s`
  return `${Math.floor(totalSec / 60)}m${totalSec % 60}s`
}

function startEditTitle(): void {
  titleDraft.value = detail.value?.title ?? ''
  editingTitle.value = true
}

async function saveTitle(): Promise<void> {
  const title = titleDraft.value.trim()
  if (!title || !detail.value) return
  await store.patchRecord(detail.value.id, { title })
  editingTitle.value = false
  emit('changed')
}

function startEdit(msg: SessionMessageRow): void {
  editingId.value = msg.id
  contentDraft.value = msg.content
}

async function saveMsg(messageId: number): Promise<void> {
  const content = contentDraft.value.trim()
  if (!content || !detail.value) return
  await store.patchMessage(detail.value.id, messageId, content)
  editingId.value = null
  emit('changed')
}

async function removeMsg(messageId: number): Promise<void> {
  if (!detail.value) return
  if (!(await ask({ title: t('sessions.deleteMsgTitle'), content: t('sessions.deleteMsgBody') }))) return
  await store.removeMessage(detail.value.id, messageId)
  emit('changed')
}

async function clearAll(): Promise<void> {
  if (!detail.value) return
  if (!(await ask({ title: t('sessions.clearTitle'), content: t('sessions.clearBody') }))) return
  await store.clearMessages(detail.value.id)
  emit('changed')
}

async function removeRecord(): Promise<void> {
  if (!detail.value) return
  if (!(await ask({ title: t('sessions.deleteTitle'), content: t('sessions.deleteBody') }))) return
  await store.remove(detail.value.id)
  emit('close')
}
</script>

<style scoped lang="less">
.srd {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;

  &__head {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    align-items: flex-start;
  }
  &__title {
    margin: 0 0 6px;
    font-size: 16px;
  }
  &__badges {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }
  &__headbtns {
    display: flex;
    gap: 6px;
    flex-shrink: 0;
  }
  &__meta {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    font-size: 12px;
    color: var(--muted);
  }
  &__node {
    &::before {
      content: '· ';
    }
  }
  &__note {
    margin: 0;
    font-size: 13px;
    color: var(--muted);
  }
  &__toolbar {
    display: flex;
    justify-content: space-between;
    gap: 8px;
  }
  &__msgs {
    display: flex;
    flex-direction: column;
    gap: 8px;
    overflow-y: auto;
    min-height: 0;
  }
  &__msg {
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 13px;
    &[data-role='user'] {
      border-left: 3px solid var(--accent);
    }
    &[data-role='assistant'] {
      border-left: 3px solid var(--ok-text);
    }
    &[data-role='tool'] {
      border-left: 3px solid var(--warn-text);
    }
  }
  &__msghead {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
  }
  &__msgtime {
    color: var(--muted);
  }
  &__msgbtns {
    margin-left: auto;
    display: flex;
    gap: 4px;
  }
  &__content {
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
  }
  &__editor {
    width: 100%;
  }
  &__editorbtns {
    margin-top: 6px;
  }
  &__empty {
    color: var(--muted);
    font-size: 12px;
    text-align: center;
  }
  &__clip {
    margin-top: 6px;
  }
  &__player {
    display: none;
  }
}
</style>
