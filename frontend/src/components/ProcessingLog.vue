<script setup lang="ts">
// Live processing log for one snapshot: streams pipeline events (parse → store → profile → discovery →
// mapping → compute) over SSE and renders a progress bar, stage chips and a scrolling console.
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { streamSse } from '@/api/client'

export interface ProgressEvent {
  seq: number
  run: string
  ts: string
  elapsed_ms: number
  stage: string
  level: 'info' | 'ok' | 'warn' | 'error' | 'stream'
  message: string
  pct: number | null
  data: Record<string, unknown> | null
}

const props = withDefaults(defineProps<{ snapshotId: number; title?: string; compact?: boolean }>(), {
  title: '',
  compact: false,
})
const emit = defineEmits<{ (e: 'finished', status: string | null): void; (e: 'dismiss'): void }>()

const STAGES = ['upload', 'parse', 'store', 'profile', 'discovery', 'mapping', 'compute', 'done'] as const
const STAGE_LABEL: Record<string, string> = {
  upload: 'Upload', queue: 'Queue', parse: 'Parse', store: 'Store', profile: 'Profile', discovery: 'Discovery',
  mapping: 'Mapping', compute: 'KPIs', done: 'Done',
}

const events = ref<ProgressEvent[]>([])
const ended = ref(false)
const endStatus = ref<string | null>(null)
const connError = ref('')
const follow = ref(true)
const logEl = ref<HTMLElement | null>(null)
let stop: (() => void) | null = null

const pct = computed(() => {
  for (let i = events.value.length - 1; i >= 0; i--) if (events.value[i].pct != null) return events.value[i].pct as number
  return 0
})
// Streamed model output arrives as level="stream" events (start / delta… / done) sharing a stream id (sid);
// they are folded into one live block per model attempt, placed where the stream started.
interface StreamBlock {
  sid: string
  title: string
  text: string
  thinking: string
  done: boolean
  ok: boolean
  note: string
}
type LogItem = { kind: 'line'; e: ProgressEvent } | { kind: 'stream'; b: StreamBlock }

const items = computed<LogItem[]>(() => {
  const out: LogItem[] = []
  const blocks = new Map<string, StreamBlock>()
  for (const e of events.value) {
    if (e.level !== 'stream') {
      out.push({ kind: 'line', e })
      continue
    }
    const d = (e.data || {}) as Record<string, unknown>
    const sid = String(d.sid || '')
    let b = blocks.get(sid)
    if (!b) {
      b = { sid, title: String(d.title || 'AI response'), text: '', thinking: '', done: false, ok: false, note: '' }
      blocks.set(sid, b)
      out.push({ kind: 'stream', b })
    }
    if (typeof d.delta === 'string') {
      if (d.channel === 'thinking') b.thinking += d.delta
      else b.text += d.delta
    }
    if (d.done) {
      b.done = true
      b.ok = Boolean(d.ok)
      b.note = String(d.note || '')
    }
  }
  return out
})
const openStreams = ref<Record<string, boolean>>({})
function streamOpen(b: StreamBlock) {
  return openStreams.value[b.sid] ?? !b.done // live: expanded; finished: collapsed unless opened
}
function toggleStream(b: StreamBlock) {
  openStreams.value = { ...openStreams.value, [b.sid]: !streamOpen(b) }
}
const streamEls = new Map<string, HTMLElement>()
function setStreamEl(sid: string, el: unknown) {
  if (el instanceof HTMLElement) streamEls.set(sid, el)
  else streamEls.delete(sid)
}

const last = computed(() => {
  for (let i = events.value.length - 1; i >= 0; i--) if (events.value[i].level !== 'stream') return events.value[i]
  return undefined
})
const lastElapsed = computed(() => events.value[events.value.length - 1]?.elapsed_ms ?? 0)
const streaming = computed(() => items.value.some((i) => i.kind === 'stream' && !i.b.done))
const failed = computed(() => events.value.some((e) => e.stage === 'done' && e.level === 'error'))
const warned = computed(() => events.value.filter((e) => e.level === 'warn').length)
const stageState = computed(() => {
  const seen = new Set(events.value.map((e) => (e.stage === 'queue' ? 'upload' : e.stage)))
  const errStages = new Set(events.value.filter((e) => e.level === 'error').map((e) => e.stage))
  const current = last.value ? (last.value.stage === 'queue' ? 'upload' : last.value.stage) : null
  return STAGES.map((s) => ({
    key: s,
    label: STAGE_LABEL[s],
    state: errStages.has(s) ? 'bad' : s === current && !ended.value && s !== 'done' ? 'active' : seen.has(s) ? 'done' : 'todo',
  }))
})

function fmtElapsed(ms: number) {
  return ms < 60000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.floor(ms / 60000)}m${Math.round((ms % 60000) / 1000)}s`
}
function scrollToEnd() {
  if (!follow.value) return
  nextTick(() => {
    if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
    for (const el of streamEls.values()) el.scrollTop = el.scrollHeight // keep live AI output tailed
  })
}
function onScroll() {
  const el = logEl.value
  if (el) follow.value = el.scrollHeight - el.scrollTop - el.clientHeight < 24
}

function connect() {
  stop?.()
  events.value = []
  ended.value = false
  endStatus.value = null
  connError.value = ''
  stop = streamSse(
    `/snapshots/${props.snapshotId}/events/stream`,
    (event, data) => {
      connError.value = ''
      if (event === 'reset') {
        events.value = []
        openStreams.value = {}
      } else if (event === 'progress') {
        const e = data as ProgressEvent
        if (!events.value.length || e.seq > events.value[events.value.length - 1].seq) events.value.push(e)
        scrollToEnd()
      } else if (event === 'end') {
        ended.value = true
        endStatus.value = (data as { status?: string | null })?.status ?? null
        emit('finished', endStatus.value)
      }
    },
    { onError: (e) => (connError.value = e instanceof Error ? e.message : 'Connection lost, retrying…') },
  )
}

watch(() => props.snapshotId, connect, { immediate: true })
onBeforeUnmount(() => stop?.())
defineExpose({ reconnect: connect })
</script>

<template>
  <div class="plog" :class="{ compact }">
    <div class="plog-head">
      <div class="plog-title">
        <span v-if="!ended" class="spinner" style="width: 14px; height: 14px" />
        <span v-else class="pill plain" :class="failed ? 'bad' : warned || endStatus === 'awaiting_mapping' ? 'warn' : 'ok'">
          {{ failed ? 'Failed' : endStatus === 'awaiting_mapping' ? 'Awaiting mapping' : endStatus === 'ready' ? 'Ready' : 'Finished' }}
        </span>
        <strong>{{ title || `Snapshot #${snapshotId}` }}</strong>
        <span v-if="last" class="muted small">· {{ streaming ? 'AI is writing its proposal…' : last.message }}</span>
      </div>
      <div class="row" style="gap: 6px; flex-wrap: nowrap">
        <span class="muted small tnum">{{ Math.round(pct) }}%<template v-if="events.length"> · {{ fmtElapsed(lastElapsed) }}</template></span>
        <button v-if="ended" class="btn btn-sm btn-ghost" @click="emit('dismiss')">Dismiss</button>
      </div>
    </div>

    <div class="plog-bar" role="progressbar" :aria-valuenow="Math.round(pct)" aria-valuemin="0" aria-valuemax="100">
      <div :class="{ bad: failed, done: ended && !failed }" :style="{ width: `${pct}%` }" />
    </div>

    <ol class="plog-stages">
      <li v-for="s in stageState" :key="s.key" :class="s.state">{{ s.label }}</li>
    </ol>

    <div ref="logEl" class="plog-console mono" role="log" aria-live="polite" @scroll="onScroll">
      <div v-if="!events.length" class="muted">{{ ended ? 'No processing log is available for this snapshot (it may have been processed before a server restart).' : 'Waiting for the worker…' }}</div>
      <template v-for="it in items" :key="it.kind === 'line' ? it.e.seq : it.b.sid">
        <div v-if="it.kind === 'line'" class="line" :class="it.e.level">
          <span class="t">+{{ fmtElapsed(it.e.elapsed_ms) }}</span>
          <span class="s">{{ STAGE_LABEL[it.e.stage] || it.e.stage }}</span>
          <span class="m">{{ it.e.message }}</span>
        </div>
        <div v-else class="stream" :class="{ live: !it.b.done, bad: it.b.done && !it.b.ok }">
          <button type="button" class="stream-head" :aria-expanded="streamOpen(it.b)" @click="toggleStream(it.b)">
            <span class="caret">{{ streamOpen(it.b) ? '▾' : '▸' }}</span>
            <span v-if="!it.b.done" class="dot" aria-hidden="true" />
            <span class="stream-title">AI · {{ it.b.title }}</span>
            <span class="muted tnum">{{ (it.b.text.length + it.b.thinking.length).toLocaleString() }} chars</span>
            <span v-if="it.b.done" class="stream-note" :class="it.b.ok ? 'ok' : 'warn'">
              {{ it.b.ok ? '✓ valid' : '✗ rejected' }}<template v-if="it.b.note"> · {{ it.b.note }}</template>
            </span>
          </button>
          <div v-if="streamOpen(it.b)" :ref="(el) => setStreamEl(it.b.sid, el)" class="stream-body">
            <div v-if="it.b.thinking" class="thinking">{{ it.b.thinking }}</div>
            <span class="stream-text">{{ it.b.text }}</span><span v-if="!it.b.done" class="cursor" aria-hidden="true" />
            <span v-if="!it.b.done && !it.b.text && !it.b.thinking" class="muted">waiting for the first tokens…</span>
          </div>
        </div>
      </template>
    </div>
    <div v-if="connError && !ended" class="muted small" style="margin-top: 4px">⚠ {{ connError }}</div>
  </div>
</template>

<style scoped>
.plog { border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); padding: 12px; }
.plog-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
.plog-title { display: flex; align-items: center; gap: 8px; min-width: 0; }
.plog-title .muted { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.plog-bar { height: 6px; border-radius: 3px; background: var(--surface-3); overflow: hidden; }
.plog-bar > div { height: 100%; background: var(--brand-2); transition: width 0.35s var(--ease); }
.plog-bar > div.done { background: var(--ok); }
.plog-bar > div.bad { background: var(--bad); }
.plog-stages { display: flex; flex-wrap: wrap; gap: 4px; list-style: none; padding: 0; margin: 8px 0; }
.plog-stages li { font-size: 11px; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--border); color: var(--muted); }
.plog-stages li.done { color: var(--ok); border-color: color-mix(in srgb, var(--ok) 40%, transparent); }
.plog-stages li.active { color: var(--info); border-color: var(--info); font-weight: 600; }
.plog-stages li.bad { color: var(--bad); border-color: var(--bad); }
.plog-console { max-height: 260px; overflow: auto; font-size: 12px; line-height: 1.55; background: var(--surface-2); border-radius: var(--radius-sm); padding: 8px 10px; }
.compact .plog-console { max-height: 160px; }
.line { display: grid; grid-template-columns: 58px 76px 1fr; gap: 8px; }
.line .t { color: var(--muted); text-align: end; }
.line .s { color: var(--text-2); }
.line .m { word-break: break-word; }
.line.ok .m { color: var(--ok); }
.line.warn .m { color: var(--warn); }
.line.error .m { color: var(--bad); font-weight: 600; }
.stream { margin: 4px 0; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface); }
.stream.live { border-color: color-mix(in srgb, var(--info) 55%, var(--border)); }
.stream.bad { border-color: color-mix(in srgb, var(--warn) 55%, var(--border)); }
.stream-head { all: unset; box-sizing: border-box; display: flex; align-items: center; gap: 8px; width: 100%; padding: 4px 8px; cursor: pointer; font-size: 12px; flex-wrap: wrap; }
.stream-head:focus-visible { outline: 2px solid var(--info); outline-offset: -2px; }
.stream-title { font-weight: 600; color: var(--text-2); }
.stream-note { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; }
.stream-note.ok { color: var(--ok); }
.stream-note.warn { color: var(--warn); }
.caret { color: var(--muted); width: 10px; }
.dot { width: 7px; height: 7px; border-radius: 50%; background: var(--info); animation: pulse 1s ease-in-out infinite; }
.stream-body { max-height: 220px; overflow: auto; padding: 6px 10px 8px; border-top: 1px solid var(--border); white-space: pre-wrap; word-break: break-word; font-size: 11.5px; line-height: 1.5; }
.thinking { color: var(--muted); font-style: italic; margin-bottom: 6px; padding-bottom: 6px; border-bottom: 1px dashed var(--border); }
.cursor { display: inline-block; width: 7px; height: 1.1em; vertical-align: text-bottom; background: var(--info); margin-inline-start: 1px; animation: blink 1s steps(1) infinite; }
@keyframes blink { 50% { opacity: 0; } }
@keyframes pulse { 50% { opacity: 0.35; } }
@media (prefers-reduced-motion: reduce) { .cursor, .dot { animation: none; } }
@media (max-width: 560px) { .line { grid-template-columns: 1fr; gap: 0; } .line .t, .line .s { display: none; } }
</style>
