<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, qs } from '@/api/client'
import type { DiffResult, DiffRow } from '@/api/types'
import StatusPill from '@/components/StatusPill.vue'
import { useDash } from '@/composables/useDash'
import { date } from '@/format'
import { useUi } from '@/stores/ui'

const ui = useUi()
const { d, store, sid, drillUids } = useDash()
const compareTo = ref<string>('previous')
const result = ref<DiffResult | null>(null)
const loading = ref(false)
const type = ref('')
const onlyMilestones = ref(false)
const q = ref('')

async function load() {
  if (!sid.value) return
  loading.value = true
  try {
    result.value = await api.get<DiffResult>(`/snapshots/${sid.value}/diff${qs({ compare_to: compareTo.value })}`)
  } catch (e) {
    ui.error(e)
    result.value = null
  } finally {
    loading.value = false
  }
}
watch([sid, compareTo], load, { immediate: true })

const others = computed(() => store.readySnapshots.filter((s) => s.id !== sid.value))
const rows = computed(() => (result.value?.changes || []).filter((r) =>
  (!type.value || r.change_type === type.value) && (!onlyMilestones.value || r.is_milestone) &&
  (!q.value || r.task_name.toLowerCase().includes(q.value.toLowerCase()))))
const TYPE_LABEL: Record<string, string> = { added: 'Added', removed: 'Removed', renamed: 'Renamed', date_moved: 'Date moved',
  progress: 'Progress', status: 'Status change', moved: 'Moved (parent)', modified: 'Modified' }
const TYPE_CLASS: Record<string, string> = { added: 'ok', removed: 'bad', renamed: 'info', date_moved: 'warn', progress: 'neutral', status: 'warn', moved: 'info', modified: 'neutral' }
const FIELD_LABEL: Record<string, string> = { name: 'Name', start: 'Start', finish: 'Finish', baseline_start: 'Baseline start',
  baseline_finish: 'Baseline finish', duration_days: 'Duration', percent_complete: '% complete', actual_start: 'Actual start',
  actual_finish: 'Actual finish', is_critical: 'Critical', is_milestone: 'Milestone flag', is_active: 'Active', constraint_type: 'Constraint',
  deadline: 'Deadline', parent: 'Parent', predecessors: 'Predecessors', resources: 'Resources' }
function fmtVal(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (Array.isArray(v)) return v.join(', ') || '—'
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(1)
  if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)) return date(v)
  return String(v)
}
function delta(v: number | null, unit: string) {
  if (v === null || v === undefined) return ''
  return `${v > 0 ? '+' : ''}${Number.isInteger(v) ? v : v.toFixed(1)}${unit}`
}
function uids(r: DiffRow) {
  return [r.task_unique_id ?? r.base_unique_id].filter((x): x is number => x !== null)
}
</script>

<template>
  <div v-if="d">
    <div class="page-head">
      <div><h1>What changed</h1>
        <p>Snapshot v{{ d.snapshot.version_no }} ({{ date(d.snapshot.as_of) }}) compared with
          <strong>{{ compareTo === 'previous' ? 'the previous snapshot' : compareTo === 'baseline' ? 'the baseline' : `snapshot v${result?.base?.version_no}` }}</strong>
          <span v-if="result?.base"> ({{ date(result.base.as_of) }})</span>. Tasks matched by Unique ID, then WBS, then fuzzy name.</p>
      </div>
      <label class="field" style="min-width: 240px">Compare against
        <select v-model="compareTo" class="input">
          <option value="previous">Previous snapshot</option>
          <option value="baseline">Baseline</option>
          <option v-for="s in others" :key="s.id" :value="String(s.id)">Snapshot v{{ s.version_no }} · {{ s.as_of }}</option>
        </select>
      </label>
    </div>
    <div v-if="loading" class="empty"><span class="spinner" /></div>
    <template v-else-if="result">
      <div v-if="result.rebaselined" class="alert warn mb">Re-baseline detected in this snapshot: baseline dates changed for ≥10% of matched tasks. Variance is measured against the new baseline.</div>
      <section class="grid grid-kpi mb">
        <div class="card"><span class="section-title">Total changes</span><div class="big tnum">{{ result.summary.total }}</div></div>
        <div class="card"><span class="section-title">Added / removed</span><div class="big tnum">{{ result.summary.by_type.added || 0 }} / {{ result.summary.by_type.removed || 0 }}</div></div>
        <div class="card"><span class="section-title">Renamed</span><div class="big tnum">{{ result.summary.renamed }}</div></div>
        <div class="card"><span class="section-title">Slipped / pulled in</span><div class="big tnum">{{ result.summary.slipped }} / {{ result.summary.pulled_in }}</div><p class="muted small">net {{ delta(result.summary.net_finish_days, ' d') || '0 d' }} finish movement</p></div>
        <div class="card"><span class="section-title">Milestones changed</span><div class="big tnum">{{ result.summary.milestones_changed }}</div></div>
        <div class="card"><span class="section-title">Status transitions</span>
          <div v-if="Object.keys(result.summary.status_transitions).length" class="small stack" style="gap: 2px; margin-top: 6px">
            <span v-for="(n, k) in result.summary.status_transitions" :key="k">{{ String(k).replace(/_/g, ' ') }}: <strong>{{ n }}</strong></span>
          </div>
          <div v-else class="big">0</div>
        </div>
      </section>
      <div class="row mb">
        <input v-model="q" class="input" style="max-width: 240px" placeholder="Search task" aria-label="Search changes" />
        <select v-model="type" class="input" style="max-width: 180px" aria-label="Change type">
          <option value="">All change types</option>
          <option v-for="(l, k) in TYPE_LABEL" :key="k" :value="k">{{ l }} ({{ result.summary.by_type[k] || 0 }})</option>
        </select>
        <label class="check"><input v-model="onlyMilestones" type="checkbox" /> Milestones only</label>
        <span class="spacer" />
        <button class="btn btn-sm" :disabled="!rows.length" @click="drillUids(rows.flatMap(uids), 'Changed tasks')">Open {{ rows.length }} tasks</button>
      </div>
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>Change</th><th>Task</th><th>Details</th><th>Start Δ</th><th>Finish Δ</th><th>Progress Δ</th><th>Status</th><th>Match</th></tr></thead>
          <tbody>
            <tr v-for="(r, i) in rows" :key="i">
              <td><span class="pill plain" :class="TYPE_CLASS[r.change_type]">{{ TYPE_LABEL[r.change_type] || r.change_type }}</span></td>
              <td><strong>{{ r.task_name }}</strong><span v-if="r.is_milestone" class="pill info plain" style="margin-inline-start: 6px">milestone</span></td>
              <td class="small">
                <div v-for="(c, f) in r.changes" :key="f"><span class="muted">{{ FIELD_LABEL[f] || f }}:</span> {{ fmtVal(c.old) }} → <strong>{{ fmtVal(c.new) }}</strong></div>
              </td>
              <td class="tnum" :class="{ bad: (r.start_delta_days || 0) > 0 }">{{ delta(r.start_delta_days, ' d') }}</td>
              <td class="tnum" :style="{ color: (r.finish_delta_days || 0) > 0 ? 'var(--bad)' : (r.finish_delta_days || 0) < 0 ? 'var(--ok)' : undefined }">{{ delta(r.finish_delta_days, ' d') }}</td>
              <td class="tnum">{{ delta(r.progress_delta, ' pts') }}</td>
              <td><span v-if="r.old_status" class="row" style="gap: 4px; flex-wrap: nowrap"><StatusPill :status="r.old_status" />→<StatusPill :status="r.new_status" /></span></td>
              <td class="muted small">{{ r.match_method }}<span v-if="r.match_method === 'fuzzy' || r.match_method === 'wbs'"> ({{ r.match_score }})</span></td>
            </tr>
            <tr v-if="!rows.length"><td colspan="8" class="empty">No changes.</td></tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<style scoped>
.big { font-size: 26px; font-weight: 700; margin-top: 4px; }
</style>
