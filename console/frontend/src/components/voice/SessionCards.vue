<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type { BadgeKind } from '@/components/proto/PBadge.vue'
import PBadge from '@/components/proto/PBadge.vue'
import type { SessionClipRow } from '@/api/sessionRecords'
import type { TranscriptEntry } from '@/features/voice/types'
import ClipPill from './ClipPill.vue'
import { useClipPlayback } from './useClipPlayback'

/**
 * 卡片流（原型 `.sess` 卡）：状态徽标 + 逐行转写（who/ASR/回复 + stt/tts 标记）
 * + 片段条。live 行播内存 blob URL；saved 行按 messageOrdinal 匹配 clips 后拉字节。
 */
export interface SessionCardLine {
  role: 'user' | 'assistant'
  /** 该行在保存 payload（usableEntriesOf）里的下标，与 clip.messageOrdinal 同键。 */
  ordinal: number
  asr: string
  text: string
  stt: 'ok' | 'fail' | 'none'
  tts: 'ok' | 'fail' | 'none'
  durMs: number
  audioUrl?: string | null
}

export interface SessionCardVM {
  key: string
  kind: 'live' | 'saved'
  state: 'live' | 'done' | 'failed' | 'unsaved' | 'partial'
  when: string
  inst: string
  node: string
  lines: SessionCardLine[]
  id: string
  turns: number
  durMs: number
  ttfaMs: number | null
  recordId?: number
  clips?: SessionClipRow[]
  /** 列表行（无逐行消息）的转写摘录。 */
  excerpt?: string
}

export type SessionCardState = SessionCardVM['state']

/** 通话中的 live 卡数据源（VoiceView → SessionLogPanel）。 */
export interface LiveCard {
  entries: TranscriptEntry[]
  pipelineSessionId: string
  instanceId: string
  node: string
  /** 本次通话起始墙钟（算 live 时长与 when 用）。 */
  startedAtMs?: number
}

const props = defineProps<{ cards: SessionCardVM[] }>()
const emit = defineEmits<{ (e: 'open', recordId: number): void }>()
const { t } = useI18n()

/** saved 卡可点开详情；live 卡无 recordId，点击无效。 */
function onCardClick(card: SessionCardVM): void {
  if (card.recordId != null) emit('open', card.recordId)
}

const { broken, playingKey, audioRef, play, onEnded } = useClipPlayback()

function badgeOf(state: SessionCardState): BadgeKind {
  switch (state) {
    case 'live': return 'accent'
    case 'done': return 'ok'
    case 'failed': return 'bad'
    case 'unsaved': return 'hot'
    case 'partial': return 'orange'
  }
}

function stateText(state: SessionCardState): string {
  return t(`sessions.card.state.${state}`)
}

function clipOf(card: SessionCardVM, line: SessionCardLine): SessionClipRow | undefined {
  return card.clips?.find((clip) => clip.messageOrdinal === line.ordinal)
}

function hasAudio(card: SessionCardVM, line: SessionCardLine): boolean {
  return Boolean(line.audioUrl) || Boolean(clipOf(card, line))
}

function lineKey(card: SessionCardVM, line: SessionCardLine): string {
  return `${card.key}:${line.ordinal}`
}

function onPlay(card: SessionCardVM, line: SessionCardLine): void {
  void play({
    key: lineKey(card, line),
    audioUrl: line.audioUrl,
    recordId: card.recordId,
    clipId: clipOf(card, line)?.id
  })
}

function flagOf(line: SessionCardLine): { which: 'stt' | 'tts'; value: 'ok' | 'fail' } | null {
  if (line.role === 'user') return line.stt === 'none' ? null : { which: 'stt', value: line.stt }
  return line.tts === 'none' ? null : { which: 'tts', value: line.tts }
}

/** 语音 {m}s（原型 conv.log.dur 语义，沿用面板的时长格式）。 */
function fmtDuration(ms: number): string {
  if (ms <= 0) return '0s'
  const totalSec = Math.round(ms / 1000)
  if (totalSec < 60) return `${totalSec}s`
  return `${Math.floor(totalSec / 60)}m${totalSec % 60}s`
}
</script>

<template>
  <div class="scards">
    <article
      v-for="card in props.cards"
      :key="card.key"
      class="scard"
      :class="{ 'scard--clickable': card.recordId != null }"
      :data-kind="card.kind"
      :data-state="card.state"
      @click="onCardClick(card)"
    >
      <div class="scard__top">
        <span class="scard__dot" :data-state="card.state" />
        <span class="scard__when">{{ card.when }}</span>
        <span class="scard__inst">{{ card.inst || '—' }} · {{ card.node || '—' }}</span>
        <span class="scard__spacer" />
        <PBadge :kind="badgeOf(card.state)" :text="stateText(card.state)" />
      </div>

      <div v-if="card.lines.length" class="scard__lines">
        <div v-for="line in card.lines" :key="line.ordinal" class="scard__line">
          <span class="scard__who">
            {{ line.role === 'user' ? t('sessions.card.caller') : t('sessions.card.bot') }}
          </span>
          <div class="scard__body">
            <div class="scard__text">
              <span class="scard__lbl">
                {{ line.role === 'user' ? t('sessions.card.asr') : t('sessions.card.reply') }}
              </span>{{ line.role === 'user' ? line.asr : line.text }}
            </div>
            <div class="scard__audio">
              <ClipPill
                v-if="hasAudio(card, line)"
                :seed="lineKey(card, line)"
                :duration-ms="line.durMs || clipOf(card, line)?.durationMs || 0"
                :disabled="broken.has(lineKey(card, line))"
                :playing="playingKey === lineKey(card, line)"
                @play="onPlay(card, line)"
              />
              <PBadge v-else kind="ro" :text="t('sessions.card.noAudio')" />
              <span
                v-if="flagOf(line)"
                class="scard__flag"
                :data-flag="flagOf(line)!.value"
              >
                {{ t(`sessions.card.${flagOf(line)!.which}.${flagOf(line)!.value}`) }}
              </span>
            </div>
          </div>
        </div>
      </div>
      <p v-else-if="card.excerpt" class="scard__excerpt">{{ card.excerpt }}</p>

      <div class="scard__foot">
        <span class="scard__mono">{{ card.id }}</span>
        <span>{{ t('sessions.turnsBadge', { n: card.turns }) }}</span>
        <span>{{ fmtDuration(card.durMs) }}</span>
        <span v-if="card.ttfaMs != null" class="scard__mono">TTFA {{ card.ttfaMs }}ms</span>
      </div>
    </article>
    <audio ref="audioRef" class="scards__player" @ended="onEnded" />
  </div>
</template>

<style scoped lang="less">
.scards {
  display: flex;
  flex-direction: column;
  gap: 10px;
  &__player {
    display: none;
  }
}
.scard {
  border: 1px solid var(--voice-border);
  border-radius: 10px;
  background: var(--voice-surface-2);
  padding: 10px 12px;
  color: var(--voice-text);
  &--clickable {
    cursor: pointer;
  }
  &[data-state='live'] {
    border-color: rgba(139, 125, 255, 0.5);
  }
  &__top {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 11.5px;
    color: var(--voice-faint);
  }
  &__dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
    background: var(--voice-ready);
    &[data-state='live'] {
      background: var(--voice-accent);
    }
    &[data-state='failed'],
    &[data-state='unsaved'] {
      background: var(--voice-error);
    }
    &[data-state='partial'] {
      background: var(--voice-processing);
    }
  }
  &__inst {
    color: var(--voice-dim);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  &__spacer {
    flex: 1;
  }
  &__lines {
    margin-top: 4px;
  }
  &__line {
    display: flex;
    gap: 9px;
    margin-top: 9px;
    align-items: flex-start;
  }
  &__who {
    flex: 0 0 32px;
    font-size: 10.5px;
    color: var(--voice-faint);
    padding-top: 2px;
  }
  &__body {
    flex: 1;
    min-width: 0;
  }
  &__text {
    font-size: 12.5px;
    line-height: 1.55;
    color: var(--voice-text);
    word-break: break-word;
  }
  &__lbl {
    font-size: 10.5px;
    color: var(--voice-faint);
    margin-right: 5px;
    letter-spacing: 0.04em;
  }
  &__audio {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 6px;
  }
  &__flag {
    font-size: 10.5px;
    padding: 1px 8px;
    border-radius: 999px;
    border: 1px solid var(--voice-border);
    color: var(--voice-faint);
    &[data-flag='ok'] {
      color: var(--voice-ready);
      border-color: rgba(52, 211, 153, 0.4);
    }
    &[data-flag='fail'] {
      color: var(--voice-error);
      border-color: rgba(240, 101, 92, 0.45);
    }
  }
  &__excerpt {
    margin: 8px 0 0;
    font-size: 12px;
    color: var(--voice-dim);
    line-height: 1.5;
    word-break: break-word;
  }
  &__foot {
    margin-top: 9px;
    padding-top: 7px;
    border-top: 1px dashed var(--voice-border);
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    font-size: 11px;
    color: var(--voice-faint);
  }
  &__mono {
    font-family: var(--mono);
  }
  &__when {
    font-family: var(--mono);
  }
}
</style>
