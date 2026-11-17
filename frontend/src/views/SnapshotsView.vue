<script setup lang="ts">
// Ingestion: single/bulk upload (per-file as-of date, optional password), hash duplicate check,
// async processing with live status, parse-error reports, reprocess, download original.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { Snapshot } from '@/api/types'
import Modal from '@/components/Modal.vue'
import ProcessingLog from '@/components/ProcessingLog.vue'
import { bytes, date, datetime } from '@/format'
import { useAuth } from '@/stores/auth'
import { useProgram } from '@/stores/program'
import { useUi } from '@/stores/ui'

interface Pending { file: File; asOf: string }
interface UploadResult { filename: string; ok: boolean; status_code?: number; error?: unknown; snapshot?: Snapshot }

const store = useProgram()
const auth = useAuth()
const ui = useUi()
const router = useRouter()
const pending = ref<Pending[]>([])
const password = ref('')
const uploading = ref(false)
const results = ref<UploadResult[]>([])
const dragging = ref(false)
const reproc = ref<Snapshot | null>(null)
const reprocPwd = ref('')
const detail = ref<Snapshot | null>(null)
const live = ref<{ id: number; title: string }[]>([])
let timer: number | undefined

const ACTIVE = ['queued', 'parsing', 'processing']
function watchLive(s: Pick<Snapshot, 'id' | 'version_no' | 'filename'>) {
  if (!live.value.some((l) => l.id === s.id)) live.value.unshift({ id: s.id, title: `v${s.version_no} · ${s.filename}` })
}
function trackActive() {
  for (const s of store.snapshots) if (ACTIVE.includes(s.status)) watchLive(s)
}
async function onLiveFinished() {
  await store.refreshSnapshots().catch(() => undefined)
  if (!busy.value) await store.loadDashboard(true).catch(() => undefined)
}

const busy = computed(() => store.snapshots.some((s) => ['queued', 'parsing', 'processing'].includes(s.status)))
const awaiting = computed(() => store.snapshots.some((s) => s.status === 'awaiting_mapping'))
const STATUS: Record<string, { label: string; cls: string }> = {
  queued: { label: 'Queued', cls: 'neutral' }, parsing: { label: 'Parsing', cls: 'info' }, processing: { label: 'Computing', cls: 'info' },
  awaiting_mapping: { label: 'Awaiting mapping', cls: 'warn' }, ready: { label: 'Ready', cls: 'ok' }, failed: { label: 'Failed', cls: 'bad' },
}

function guessDate(name: string): string {
  const m = /(\d{4})[-_.]?(\d{2})[-_.]?(\d{2})/.exec(name)
  return m ? `${m[1]}-${m[2]}-${m[3]}` : ''
}
function addFiles(list: FileList | File[] | null) {
  if (!list) return
  for (const f of Array.from(list)) pending.value.push({ file: f, asOf: guessDate(f.name) })
}
function onDrop(e: DragEvent) {
  dragging.value = false
  addFiles(e.dataTransfer?.files || null)
}
async function upload() {
  if (!pending.value.length || !store.program) return
  uploading.value = true
  results.value = []
  try {
    const fd = new FormData()
    for (const p of pending.value) fd.append('files', p.file)
    const anyDate = pending.value.some((p) => p.asOf)
    if (anyDate) for (const p of pending.value) fd.append('as_of', p.asOf || '')
    if (password.value) fd.append('password', password.value)
    const res = await api.upload<{ results: UploadResult[] }>(`/programs/${store.program.id}/snapshots`, fd)
    results.value = res.results
    for (const r of res.results) if (r.ok && r.snapshot) watchLive(r.snapshot)
    pending.value = []
    password.value = ''
    const ok = res.results.filter((r) => r.ok).length
    ui.toast(`${ok} of ${res.results.length} file(s) accepted for processing`, ok ? 'ok' : 'warn')
  } catch (e) {
    ui.error(e)
  } finally {
    uploading.value = false
    await store.refreshSnapshots()
  }
}
function errText(e: unknown): string {
  if (!e) return ''
  if (typeof e === 'string') return e
  if (typeof e === 'object' && e && 'message' in e) return String((e as { message: string }).message)
  return JSON.stringify(e)
}
async function poll() {
  const wasBusy = busy.value
  await store.refreshSnapshots().catch(() => undefined)
  trackActive()
  if (wasBusy && !busy.value) await store.loadDashboard(true)
}
async function doReprocess() {
  if (!reproc.value) return
  try {
    const fd = new FormData()
    if (reprocPwd.value) fd.append('password', reprocPwd.value)
    await api.upload(`/snapshots/${reproc.value.id}/reprocess`, fd)
    live.value = live.value.filter((l) => l.id !== reproc.value!.id)
    watchLive(reproc.value)
    reproc.value = null
    reprocPwd.value = ''
    await store.refreshSnapshots()
  } catch (e) {
    ui.error(e)
  }
}
async function remove(s: Snapshot) {
  if (!confirm(`Delete snapshot v${s.version_no} (${s.filename})? KPIs and history will be recomputed.`)) return
  try {
    await api.del(`/snapshots/${s.id}`)
    await store.refreshSnapshots()
    await store.loadDashboard(true)
  } catch (e) {
    ui.error(e)
  }
}
async function openDetail(s: Snapshot) {
  detail.value = await api.get<Snapshot>(`/snapshots/${s.id}`)
}
onMounted(() => {
  trackActive()
  timer = window.setInterval(() => busy.value && poll(), 2000)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <div>
    <div class="page-head"><div><h1>Snapshots</h1><p>Each upload is an immutable, versioned snapshot with an as-of date. Identical files are rejected by hash.</p></div></div>

    <div v-if="awaiting" class="alert warn mb row">
      <span>A snapshot is waiting for the mapping to be approved before the dashboard can be built.</span>
      <span class="spacer" />
      <button v-if="auth.isAdmin" class="btn btn-sm btn-primary" @click="router.push(`/p/${store.program?.id}/mapping`)">Open mapping wizard</button>
      <span v-else class="small">Ask an administrator to approve it.</span>
    </div>

    <section v-if="auth.isEditor" class="card mb">
      <h2 class="mb">Upload plan files</h2>
      <label class="drop" :class="{ dragging }" @dragover.prevent="dragging = true" @dragleave="dragging = false" @drop.prevent="onDrop">
        <input type="file" multiple accept=".mpp,.mpt,.mpx,.xml" class="sr-only" @change="(e) => addFiles((e.target as HTMLInputElement).files)" />
        <strong>Drop .mpp files here or click to browse</strong>
        <span class="muted small">MS Project .mpp (98–2021+), .mpt, .mpx or MSPDI .xml · several files at once for bulk/back-fill uploads · max 100 MB each</span>
      </label>
      <div v-if="pending.length" class="mt">
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>File</th><th>Size</th><th>As-of date</th><th></th></tr></thead>
            <tbody>
              <tr v-for="(p, i) in pending" :key="i">
                <td>{{ p.file.name }}</td><td class="tnum">{{ bytes(p.file.size) }}</td>
                <td><input v-model="p.asOf" type="date" class="input" style="max-width: 180px" :aria-label="`As-of date for ${p.file.name}`" />
                  <span v-if="!p.asOf" class="muted small"> blank = project status date</span></td>
                <td><button class="btn btn-sm btn-ghost" @click="pending.splice(i, 1)">Remove</button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="row mt">
          <label class="field" style="max-width: 280px">File password (optional)<input v-model="password" type="password" class="input" autocomplete="off" /></label>
          <span class="spacer" />
          <button class="btn" @click="pending = []">Clear</button>
          <button class="btn btn-primary" :disabled="uploading" @click="upload"><span v-if="uploading" class="spinner" /> Upload {{ pending.length }} file(s)</button>
        </div>
      </div>
      <div v-if="results.length" class="mt stack" style="gap: 6px">
        <div v-for="r in results" :key="r.filename" class="alert" :class="r.ok ? 'ok' : 'bad'">
          <strong>{{ r.filename }}</strong>: {{ r.ok ? `accepted as v${r.snapshot?.version_no}` : errText(r.error) }}
        </div>
      </div>
    </section>

    <section v-if="live.length" class="mb stack" style="gap: 10px" aria-label="Live processing">
      <ProcessingLog v-for="l in live" :key="l.id" :snapshot-id="l.id" :title="l.title"
                     @finished="onLiveFinished" @dismiss="live = live.filter((x) => x.id !== l.id)" />
    </section>

    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>Version</th><th>As of</th><th>File</th><th>Status</th><th>Tasks</th><th>Format</th><th>Baseline</th><th>Uploaded</th><th></th></tr></thead>
        <tbody>
          <tr v-for="s in store.snapshots" :key="s.id">
            <td class="tnum"><strong>v{{ s.version_no }}</strong></td>
            <td class="tnum">{{ date(s.as_of) }}<div class="muted small">{{ s.as_of_source === 'status_date' ? 'from status date' : s.as_of_source === 'upload' ? 'upload date' : s.as_of_source === 'user' ? 'set at upload' : '' }}</div></td>
            <td>{{ s.filename }}<div class="muted small">{{ bytes(s.file_size) }} · <span class="mono" :title="s.file_hash">{{ s.file_hash.slice(0, 10) }}</span></div></td>
            <td>
              <span class="pill" :class="STATUS[s.status]?.cls">{{ STATUS[s.status]?.label || s.status }}</span>
              <span v-if="['queued', 'parsing', 'processing'].includes(s.status)" class="spinner" style="width: 14px; height: 14px; margin-inline-start: 6px" />
              <div v-if="s.status_message" class="muted small">{{ s.status_message }}</div>
              <div v-if="s.error_report" class="alert bad small" style="margin-top: 6px">
                <strong>{{ s.error_report.message }}</strong><div v-if="s.error_report.hint">{{ s.error_report.hint }}</div>
              </div>
              <div v-if="s.warnings?.length" class="muted small">⚠ {{ s.warnings.length }} warning(s)</div>
            </td>
            <td class="tnum">{{ s.task_count || '—' }}</td>
            <td class="small">{{ s.file_format || '—' }}</td>
            <td>{{ s.status === 'ready' || s.status === 'awaiting_mapping' ? (s.has_baseline ? 'Yes' : 'No') : '—' }}<span v-if="s.rebaselined" class="pill warn plain" style="margin-inline-start: 4px">re-baselined</span></td>
            <td class="small">{{ datetime(s.uploaded_at) }}</td>
            <td>
              <div class="row" style="flex-wrap: nowrap; gap: 4px">
                <button class="btn btn-sm btn-ghost" @click="openDetail(s)">Details</button>
                <button v-if="ACTIVE.includes(s.status) && !live.some((l) => l.id === s.id)" class="btn btn-sm btn-ghost" @click="watchLive(s)">Live log</button>
                <button v-if="s.status === 'ready'" class="btn btn-sm btn-ghost" @click="store.selectSnapshot(s.id).then(() => router.push(`/p/${store.program?.id}/overview`))">View</button>
                <button v-if="auth.isEditor && ['failed', 'ready', 'awaiting_mapping'].includes(s.status)" class="btn btn-sm btn-ghost" @click="reproc = s">Reprocess</button>
                <button v-if="auth.isEditor" class="btn btn-sm btn-ghost" @click="api.download(`/snapshots/${s.id}/file`, s.filename)">File</button>
                <button v-if="auth.isAdmin" class="btn btn-sm btn-ghost btn-danger" @click="remove(s)">Delete</button>
              </div>
            </td>
          </tr>
          <tr v-if="!store.snapshots.length"><td colspan="9" class="empty">No snapshots yet — upload the first .mpp file above.</td></tr>
        </tbody>
      </table>
    </div>

    <Modal v-if="reproc" :title="`Reprocess v${reproc.version_no}`" @close="reproc = null">
      <p class="mb">Re-parse <strong>{{ reproc.filename }}</strong> and recompute its KPIs. Provide the password if the file is protected.</p>
      <label class="field">File password (optional)<input v-model="reprocPwd" type="password" class="input" autocomplete="off" /></label>
      <template #footer><button class="btn" @click="reproc = null">Cancel</button><button class="btn btn-primary" @click="doReprocess">Reprocess</button></template>
    </Modal>

    <Modal v-if="detail" :title="`Snapshot v${detail.version_no} · ${detail.filename}`" wide @close="detail = null">
      <div class="grid grid-2">
        <div>
          <h3 class="mb">Project properties</h3>
          <dl class="dl"><template v-for="(v, k) in detail.project" :key="k"><dt>{{ k }}</dt><dd>{{ v ?? '—' }}</dd></template></dl>
        </div>
        <div>
          <h3 class="mb">Structure</h3>
          <dl class="dl" v-if="detail.profile">
            <dt>Tasks / leaf / summary</dt><dd>{{ detail.profile.task_count }} / {{ detail.profile.leaf_task_count }} / {{ detail.profile.summary_task_count }}</dd>
            <dt>Milestone flags</dt><dd>{{ detail.profile.milestone_flag_count }}</dd>
            <dt>Resources</dt><dd>{{ detail.profile.resource_count }}</dd>
            <dt>Outline levels</dt><dd>{{ JSON.stringify(detail.profile.tasks_per_level) }}</dd>
            <dt>Planned method</dt><dd>{{ detail.planned_method || '—' }}</dd>
            <dt>KPI engine</dt><dd>{{ detail.kpi_engine_version || '—' }}</dd>
          </dl>
          <h3 class="mb mt" v-if="detail.warnings.length">Warnings</h3>
          <ul v-if="detail.warnings.length"><li v-for="w in detail.warnings" :key="w" class="small">{{ w }}</li></ul>
          <template v-if="detail.error_report">
            <h3 class="mb mt">Parse-error report</h3>
            <div class="alert bad small"><strong>{{ detail.error_report.code }}</strong>: {{ detail.error_report.message }}<br />{{ detail.error_report.hint }}<pre class="mono" style="white-space: pre-wrap">{{ detail.error_report.detail }}</pre></div>
          </template>
        </div>
      </div>
      <h3 class="mb mt">Processing log</h3>
      <ProcessingLog :snapshot-id="detail.id" :title="`v${detail.version_no} · ${detail.filename}`" compact />
    </Modal>
  </div>
</template>

<style scoped>
.drop { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 28px; border: 2px dashed var(--border-strong); border-radius: var(--radius); cursor: pointer; text-align: center; background: var(--surface-2); }
.drop.dragging, .drop:hover { border-color: var(--brand-2); }
.drop:focus-within { outline: 3px solid var(--focus); }
.dl { display: grid; grid-template-columns: 160px 1fr; gap: 4px 12px; margin: 0; font-size: 13px; }
.dl dt { color: var(--muted); }
.dl dd { margin: 0; word-break: break-word; }
</style>
