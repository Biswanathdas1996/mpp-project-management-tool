<script setup lang="ts">
// Per-program mapping wizard: shown on first upload, reused afterwards (re-open to change).
// 1 profile → 2 tracks → 3 milestones → 4 planned-to-date → 5 approve KPI set → recompute.
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api } from '@/api/client'
import type { MappingState, PreviewResult, Rule } from '@/api/types'
import { useProgram } from '@/stores/program'
import { useUi } from '@/stores/ui'

const store = useProgram()
const ui = useUi()
const state = ref<MappingState | null>(null)
const step = ref(1)
const preview = ref<PreviewResult | null>(null)
const previewing = ref(false)
const saving = ref(false)
const trackRule = reactive<Rule>({ type: 'outline_level', level: 1 })
const msRule = reactive<Rule>({ type: 'flag' })
const plannedMethod = ref('auto')
const trackNames = reactive<Record<string, string>>({})
const excluded = ref<string[]>([])
const kpis = ref<string[]>([])

const profile = computed(() => state.value?.profile)
const levels = computed(() => Object.keys(profile.value?.tasks_per_level || {}).map(Number).sort((a, b) => a - b))
const customFields = computed(() => profile.value?.custom_fields || [])
const proposedCodes = computed(() => new Set((state.value?.proposed?.proposed_kpis || profile.value?.discovery?.proposed_kpis || []).map((k) => k.code)))
const rationale = computed(() => Object.fromEntries((state.value?.proposed?.proposed_kpis || profile.value?.discovery?.proposed_kpis || []).map((k) => [k.code, k.rationale])))
const catalogue = computed(() => (state.value?.kpi_catalogue || []).filter((k) => !k.reference))
const byCat = computed(() => {
  const out: Record<string, typeof catalogue.value> = {}
  for (const k of catalogue.value) (out[k.category] ||= []).push(k)
  return out
})

async function load() {
  if (!store.program) return
  state.value = await api.get<MappingState>(`/programs/${store.program.id}/mapping`)
  const src = state.value.proposed || state.value.approved
  const disc = state.value.profile?.discovery?.proposal
  const tr = src?.track_rule || disc?.track_rule
  const mr = src?.milestone_rule || disc?.milestone_rule
  if (tr) Object.assign(trackRule, { type: tr.type, level: tr.level, field: tr.field, value: tr.value })
  if (mr) Object.assign(msRule, { type: mr.type, level: mr.level, field: mr.field, value: mr.value })
  plannedMethod.value = src?.planned_method || disc?.planned_method || 'auto'
  Object.assign(trackNames, state.value.approved?.track_names || {})
  excluded.value = [...(state.value.approved?.excluded_track_keys || [])]
  kpis.value = state.value.approved?.approved_kpis?.length ? [...state.value.approved.approved_kpis] : [...proposedCodes.value]
  await runPreview()
}
function clean(r: Rule): Rule {
  if (r.type === 'outline_level') return { type: r.type, level: Number(r.level) || 1 }
  if (r.type === 'custom_field') return { type: r.type, field: r.field, ...(r.value ? { value: r.value } : {}) }
  return { type: 'flag' }
}
async function runPreview() {
  if (!store.program || !state.value?.snapshot_id) return
  previewing.value = true
  try {
    preview.value = await api.post<PreviewResult>(`/programs/${store.program.id}/mapping/preview`, {
      snapshot_id: state.value.snapshot_id, track_rule: clean(trackRule), milestone_rule: clean(msRule) })
  } catch (e) {
    ui.error(e)
  } finally {
    previewing.value = false
  }
}
watch([() => ({ ...trackRule }), () => ({ ...msRule })], runPreview, { deep: true })

async function approve() {
  if (!store.program) return
  saving.value = true
  try {
    const names = Object.fromEntries(Object.entries(trackNames).filter(([, v]) => v && v.trim()))
    await api.post(`/programs/${store.program.id}/mapping/approve`, { track_rule: clean(trackRule), milestone_rule: clean(msRule),
      planned_method: plannedMethod.value, track_names: names, excluded_track_keys: excluded.value, approved_kpis: kpis.value })
    ui.toast('Mapping approved — all snapshots are being recomputed')
    await load()
    setTimeout(async () => {
      await store.refreshSnapshots()
      await store.loadDashboard(true)
    }, 2500)
  } catch (e) {
    ui.error(e)
  } finally {
    saving.value = false
  }
}
function toggleAll(codes: string[], on: boolean) {
  const s = new Set(kpis.value)
  for (const c of codes) on ? s.add(c) : s.delete(c)
  kpis.value = [...s]
}
onMounted(load)
const STEPS = ['Data profile', 'Delivery tracks', 'Milestones', 'Planned to date', 'KPIs & approve']
</script>

<template>
  <div v-if="state">
    <div class="page-head">
      <div><h1>Mapping wizard</h1>
        <p>
          <template v-if="state.approved">{{ state.approved.auto_approved ? 'Automatically approved' : 'Approved' }} mapping v{{ state.approved.version }} ({{ state.approved.proposed_by }}{{ state.approved.auto_approved ? ' — logic and AI agreed, structural checks passed' : '' }}) in use · review it below; changing it recomputes every snapshot.</template>
          <template v-else>First upload: confirm how this plan maps to tracks and milestones. The mapping is saved and reused for every future upload.</template>
        </p>
      </div>
    </div>
    <div v-if="!state.snapshot_id" class="card empty">Upload a snapshot first.</div>
    <template v-else>
      <ol class="steps" aria-label="Wizard steps">
        <li v-for="(s, i) in STEPS" :key="s"><button class="linklike" :aria-current="step === i + 1 ? 'step' : undefined" :class="{ on: step === i + 1, done: step > i + 1 }" @click="step = i + 1"><span>{{ i + 1 }}</span>{{ s }}</button></li>
      </ol>

      <section v-if="step === 1 && profile" class="card">
        <div class="card-head"><h2>What's in the file</h2><span class="src">{{ profile.discovery?.proposal_source === 'ai' ? 'AI discovery' : 'deterministic profiling' }}</span></div>
        <div class="grid grid-kpi">
          <div><span class="section-title">Tasks</span><div class="big">{{ profile.task_count }}</div><span class="muted small">{{ profile.leaf_task_count }} leaf · {{ profile.summary_task_count }} summary</span></div>
          <div><span class="section-title">Outline depth</span><div class="big">{{ profile.max_outline_level }}</div><span class="muted small">{{ JSON.stringify(profile.summaries_per_level) }} summaries/level</span></div>
          <div><span class="section-title">Milestone flags</span><div class="big">{{ profile.milestone_flag_count }}</div></div>
          <div><span class="section-title">Resources</span><div class="big">{{ profile.resource_count }}</div></div>
        </div>
        <p v-if="profile.discovery?.summary" class="mt">{{ profile.discovery.summary }}</p>
        <h3 class="mt mb">Field coverage</h3>
        <div class="cov">
          <div v-for="(v, k) in profile.group_coverage_pct" :key="k" class="cov-row"><span>{{ k }}</span>
            <div class="bar" style="flex: 1"><span :style="{ width: `${v}%`, background: v > 60 ? 'var(--c-on-track)' : v > 0 ? 'var(--c-delay)' : 'var(--c-not-started)' }" /></div><span class="tnum">{{ v }}%</span></div>
        </div>
        <h3 class="mt mb">Data-quality gaps</h3>
        <ul class="small"><li v-for="g in profile.quality_gaps" :key="g.code">{{ g.message }}</li></ul>
        <div class="row mt"><span class="spacer" /><button class="btn btn-primary" @click="step = 2">Next: tracks</button></div>
      </section>

      <section v-if="step === 2" class="card">
        <h2 class="mb">How are delivery tracks defined?</h2>
        <div class="form-grid">
          <label class="field">Rule<select v-model="trackRule.type" class="input"><option value="outline_level">Outline level (summary tasks)</option><option value="custom_field" :disabled="!customFields.length">Custom field value</option></select></label>
          <label v-if="trackRule.type === 'outline_level'" class="field">Outline level<select v-model.number="trackRule.level" class="input"><option v-for="l in levels" :key="l" :value="l">Level {{ l }} ({{ profile?.summaries_per_level[String(l)] || 0 }} summaries)</option></select></label>
          <label v-else class="field">Custom field<select v-model="trackRule.field" class="input"><option v-for="cf in customFields" :key="cf.field" :value="cf.field">{{ cf.field }} ({{ cf.distinct_values }} values)</option></select></label>
        </div>
        <p v-if="profile?.discovery?.proposal?.rationale" class="muted small mt">Proposal rationale: {{ profile.discovery.proposal.rationale }}</p>
        <h3 class="mt mb">Preview <span v-if="previewing" class="spinner" /></h3>
        <div v-if="preview" class="table-wrap">
          <table class="table">
            <thead><tr><th>Include</th><th>Track</th><th>Name in file</th><th>Display name (optional)</th><th>Tasks</th></tr></thead>
            <tbody>
              <tr v-for="tr in preview.tracks" :key="tr.key">
                <td><input type="checkbox" :checked="!excluded.includes(tr.key)" :aria-label="`Include ${tr.name}`" @change="excluded = ($event.target as HTMLInputElement).checked ? excluded.filter((k) => k !== tr.key) : [...excluded, tr.key]" /></td>
                <td class="tnum">Track {{ String(tr.number).padStart(2, '0') }}</td><td>{{ tr.name }}</td>
                <td><input v-model="trackNames[tr.key]" class="input" :placeholder="tr.name" :aria-label="`Display name for ${tr.name}`" /></td>
                <td class="tnum">{{ tr.task_count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="preview?.unmapped_tasks" class="alert warn small mt">{{ preview.unmapped_tasks }} tasks fall outside any track (e.g. above the chosen level) and are excluded from roll-ups.</p>
        <div class="row mt"><button class="btn" @click="step = 1">Back</button><span class="spacer" /><button class="btn btn-primary" @click="step = 3">Next: milestones</button></div>
      </section>

      <section v-if="step === 3" class="card">
        <h2 class="mb">How are milestones identified?</h2>
        <div class="form-grid">
          <label class="field">Rule<select v-model="msRule.type" class="input"><option value="flag">MS Project milestone flag</option><option value="outline_level">Outline level</option><option value="custom_field" :disabled="!customFields.length">Custom field value</option></select></label>
          <label v-if="msRule.type === 'outline_level'" class="field">Outline level<select v-model.number="msRule.level" class="input"><option v-for="l in levels" :key="l" :value="l">Level {{ l }}</option></select></label>
          <template v-if="msRule.type === 'custom_field'">
            <label class="field">Custom field<select v-model="msRule.field" class="input"><option v-for="cf in customFields" :key="cf.field" :value="cf.field">{{ cf.field }}</option></select></label>
            <label class="field">Value<input v-model="msRule.value" class="input" placeholder="e.g. Yes (blank = any value)" /><span class="hint">{{ customFields.find((c) => c.field === msRule.field)?.top_values.slice(0, 6).join(', ') }}</span></label>
          </template>
        </div>
        <p class="mt"><strong>{{ preview?.milestone_count ?? '…' }}</strong> milestones will be numbered 01..n by track and start date.</p>
        <div v-if="preview" class="grid grid-3 mt">
          <div v-for="tr in preview.tracks.filter((x) => x.milestones.length)" :key="tr.key" class="card"><h3>Track {{ String(tr.number).padStart(2, '0') }} · {{ tr.name }}</h3><ul class="small"><li v-for="m in tr.milestones" :key="m">{{ m }}</li></ul></div>
        </div>
        <div class="row mt"><button class="btn" @click="step = 2">Back</button><span class="spacer" /><button class="btn btn-primary" @click="step = 4">Next</button></div>
      </section>

      <section v-if="step === 4" class="card">
        <h2 class="mb">Planned-to-date method</h2>
        <div class="stack">
          <label v-for="o in [
            { v: 'auto', t: 'Automatic (recommended)', d: 'Baseline when present on ≥50% of tasks; otherwise the first snapshot is frozen as the baseline; otherwise linear by duration.' },
            { v: 'baseline', t: 'Baseline dates', d: 'Use MS Project baseline start/finish (falls back per task when missing).' },
            { v: 'first_snapshot', t: 'First snapshot frozen as baseline', d: 'Treat the dates in the first uploaded snapshot as the plan.' },
            { v: 'linear', t: 'Linear by duration', d: 'Planned % = elapsed share of each task\'s current start→finish.' }]" :key="o.v" class="card check" style="align-items: flex-start">
            <input v-model="plannedMethod" type="radio" name="pm" :value="o.v" />
            <span><strong>{{ o.t }}</strong><br /><span class="muted small">{{ o.d }}</span></span>
          </label>
        </div>
        <p class="muted small mt">Variance (pts) = actual % − planned %. Status thresholds are set in Program Settings.</p>
        <div class="row mt"><button class="btn" @click="step = 3">Back</button><span class="spacer" /><button class="btn btn-primary" @click="step = 5">Next: KPIs</button></div>
      </section>

      <section v-if="step === 5" class="card">
        <div class="card-head"><h2>Approve the KPI set</h2><span class="muted small">{{ kpis.length }} selected · ★ = proposed as supported by this data</span></div>
        <p class="muted small mb">The reference dashboard KPIs are always on. Choose which extended KPIs this program shows. All values are computed by the deterministic engine.</p>
        <div v-for="(items, cat) in byCat" :key="cat" class="mb">
          <div class="row"><h3 style="text-transform: capitalize">{{ cat }}</h3>
            <button class="btn btn-sm btn-ghost" @click="toggleAll(items.map((k) => k.code), true)">All</button>
            <button class="btn btn-sm btn-ghost" @click="toggleAll(items.map((k) => k.code), false)">None</button></div>
          <div class="kpi-grid">
            <label v-for="k in items" :key="k.code" class="check kpi-opt" :title="k.formula">
              <input v-model="kpis" type="checkbox" :value="k.code" />
              <span>{{ proposedCodes.has(k.code) ? '★ ' : '' }}{{ k.name }}<br /><span class="muted small">{{ rationale[k.code] || k.formula }}</span></span>
            </label>
          </div>
        </div>
        <div class="row mt"><button class="btn" @click="step = 4">Back</button><span class="spacer" />
          <button class="btn btn-primary" :disabled="saving" @click="approve"><span v-if="saving" class="spinner" /> Approve mapping &amp; build dashboard</button></div>
      </section>

      <section v-if="state.history.length" class="card mt">
        <h3 class="mb">Mapping history</h3>
        <table class="table"><thead><tr><th>Version</th><th>Status</th><th>By</th><th>Tracks</th><th>Milestones</th><th>Approved</th></tr></thead>
          <tbody><tr v-for="m in state.history" :key="m.id"><td>v{{ m.version }}</td><td>{{ m.status }}</td><td>{{ m.proposed_by }}</td><td class="mono">{{ JSON.stringify(m.track_rule) }}</td><td class="mono">{{ JSON.stringify(m.milestone_rule) }}</td><td>{{ m.approved_at?.slice(0, 10) || '—' }}</td></tr></tbody></table>
      </section>
    </template>
  </div>
  <div v-else class="empty"><span class="spinner" /></div>
</template>

<style scoped>
.steps { display: flex; gap: 6px; list-style: none; padding: 0; margin: 0 0 16px; flex-wrap: wrap; }
.steps button { display: inline-flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: 999px; border: 1px solid var(--border); background: var(--surface); color: var(--muted); font-weight: 550; }
.steps button span { width: 22px; height: 22px; border-radius: 50%; display: grid; place-items: center; background: var(--surface-2); font-size: 12px; }
.steps button.on { color: var(--text); border-color: var(--brand-2); }
.steps button.on span { background: var(--brand-2); color: #fff; }
.steps button.done span { background: var(--ok-bg); color: var(--ok); }
.big { font-size: 26px; font-weight: 700; }
.cov { display: grid; gap: 8px; }
.cov-row { display: grid; grid-template-columns: 120px 1fr 54px; gap: 10px; align-items: center; font-size: 13px; }
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 8px; margin-top: 8px; }
.kpi-opt { align-items: flex-start; padding: 8px; border: 1px solid var(--border); border-radius: 8px; }
</style>
