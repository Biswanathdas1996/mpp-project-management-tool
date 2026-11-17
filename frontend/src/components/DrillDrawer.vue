<script setup lang="ts">
// "Every number drills down to its underlying tasks."
import { computed, ref, watch } from 'vue'
import { api, qs } from '@/api/client'
import type { TaskRow } from '@/api/types'
import { useUi } from '@/stores/ui'
import { date, num, pct } from '@/format'
import Icon from './Icon.vue'
import ProgressBar from './ProgressBar.vue'

const ui = useUi()
const tasks = ref<TaskRow[]>([])
const title = ref('')
const loading = ref(false)
const error = ref<string | null>(null)
const filter = ref('')
const leafOnly = ref(false)
const selected = ref<TaskRow | null>(null)

watch(() => ui.drill, async (req) => {
  tasks.value = []
  selected.value = null
  filter.value = ''
  if (!req) return
  loading.value = true
  error.value = null
  try {
    const res = await api.get<{ title: string; count: number; tasks: TaskRow[] }>(
      `/snapshots/${req.snapshotId}/drill${qs({ kpi: req.kpi, track_id: req.trackId, milestone_id: req.milestoneId, uids: req.uids?.join(',') })}`,
    )
    tasks.value = res.tasks
    title.value = req.title || res.title
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
})

const shown = computed(() => {
  const f = filter.value.trim().toLowerCase()
  return tasks.value.filter((t) => (!leafOnly.value || !t.is_summary) &&
    (!f || t.name.toLowerCase().includes(f) || (t.wbs || '').toLowerCase().includes(f) ||
     t.resource_names.join(' ').toLowerCase().includes(f)))
})

function csv() {
  const cols: (keyof TaskRow)[] = ['unique_id', 'task_id', 'wbs', 'name', 'start', 'finish', 'baseline_finish', 'percent_complete',
    'planned_percent', 'duration_days', 'total_slack_days', 'is_critical']
  const esc = (v: unknown) => `"${String(v ?? '').replace(/"/g, '""')}"`
  const body = [cols.join(','), ...shown.value.map((t) => cols.map((c) => esc(t[c])).join(','))].join('\n')
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([body], { type: 'text/csv' }))
  a.download = `${title.value.replace(/[^\w-]+/g, '_')}.csv`
  a.click()
}
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') ui.closeDrill()
}
</script>

<template>
  <div v-if="ui.drill" class="drawer-backdrop" @mousedown.self="ui.closeDrill()" @keydown="onKey">
    <aside class="drawer" role="dialog" aria-modal="true" :aria-label="title || 'Underlying tasks'">
      <header class="drawer-head">
        <div>
          <span class="section-title">Underlying tasks</span>
          <h2>{{ title }}</h2>
          <p class="muted small">{{ shown.length }} of {{ tasks.length }} tasks</p>
        </div>
        <button class="btn btn-ghost btn-icon" aria-label="Close" autofocus @click="ui.closeDrill()"><Icon name="x" :size="18" /></button>
      </header>
      <div class="row mb">
        <input v-model="filter" class="input" style="max-width: 280px" placeholder="Filter by name, WBS or resource" aria-label="Filter tasks" />
        <label class="check small"><input v-model="leafOnly" type="checkbox" /> Leaf tasks only</label>
        <span class="spacer" />
        <button class="btn btn-sm" :disabled="!shown.length" @click="csv"><Icon name="download" :size="14" />Download CSV</button>
      </div>
      <div v-if="loading" class="empty"><span class="spinner" /></div>
      <div v-else-if="error" class="alert bad">{{ error }}</div>
      <div v-else-if="!tasks.length" class="empty">No tasks contribute to this number.</div>
      <div v-else class="table-wrap">
        <table class="table">
          <thead>
            <tr><th>UID</th><th>WBS</th><th>Task</th><th>Start</th><th>Finish</th><th>Baseline finish</th><th>Progress</th><th>Planned</th><th>Slack</th></tr>
          </thead>
          <tbody>
            <tr v-for="t in shown" :key="t.unique_id" class="clickable" tabindex="0"
                @click="selected = selected?.unique_id === t.unique_id ? null : t" @keydown.enter="selected = t">
              <td class="tnum muted">{{ t.unique_id }}</td>
              <td class="tnum muted">{{ t.wbs || t.outline_number }}</td>
              <td :style="{ paddingInlineStart: `${12 + Math.max(0, t.outline_level - 1) * 12}px` }">
                <strong v-if="t.is_summary">{{ t.name }}</strong><span v-else>{{ t.name }}</span>
                <span v-if="t.is_critical" class="pill bad plain small" style="margin-inline-start: 6px; height: 18px">critical</span>
                <span v-if="t.is_milestone" class="pill info plain" style="margin-inline-start: 6px; height: 18px">◆</span>
              </td>
              <td class="tnum">{{ date(t.start) }}</td>
              <td class="tnum">{{ date(t.finish) }}</td>
              <td class="tnum muted">{{ date(t.baseline_finish) }}</td>
              <td style="min-width: 110px"><div class="row" style="gap: 6px; flex-wrap: nowrap"><ProgressBar :value="t.percent_complete" style="flex: 1" /><span class="tnum small">{{ pct(t.percent_complete, 0) }}</span></div></td>
              <td class="tnum muted">{{ pct(t.planned_percent, 0) }}</td>
              <td class="tnum">{{ t.total_slack_days === null ? '—' : `${num(t.total_slack_days, 1)} d` }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <section v-if="selected" class="card mt detail">
        <h3>{{ selected.name }}</h3>
        <dl class="dl">
          <dt>Resources</dt><dd>{{ selected.resource_names.join(', ') || '—' }}</dd>
          <dt>Predecessors</dt><dd>{{ selected.predecessors.map((p) => `${p.uid} (${p.type}${p.lag_days ? ` ${p.lag_days}d` : ''})`).join(', ') || '—' }}</dd>
          <dt>Actual start / finish</dt><dd>{{ date(selected.actual_start) }} / {{ date(selected.actual_finish) }}</dd>
          <dt>Duration</dt><dd>{{ num(selected.duration_days, 1) }} d</dd>
          <dt>Constraint</dt><dd>{{ selected.constraint_type || '—' }}</dd>
          <dt>Deadline</dt><dd>{{ date(selected.deadline) }}</dd>
          <dt>Cost (baseline / actual)</dt><dd>{{ num(selected.baseline_cost) }} / {{ num(selected.actual_cost) }}</dd>
          <dt>Custom fields</dt><dd>{{ Object.entries(selected.custom_fields || {}).map(([k, v]) => `${k}: ${v}`).join(' · ') || '—' }}</dd>
          <dt>Notes</dt><dd style="white-space: pre-wrap">{{ selected.notes || '—' }}</dd>
        </dl>
      </section>
    </aside>
  </div>
</template>

<style scoped>
.drawer-backdrop { position: fixed; inset: 0; background: rgb(10 12 18 / 0.4); backdrop-filter: blur(3px); -webkit-backdrop-filter: blur(3px); z-index: 70; display: flex; justify-content: flex-end; animation: fade 0.18s var(--ease); }
.drawer { width: min(1060px, 100%); height: 100%; background: var(--bg); padding: 24px; overflow: auto; box-shadow: var(--shadow-lg); border-inline-start: 1px solid var(--border); animation: slide 0.26s var(--ease); }
:root[dir='rtl'] .drawer { animation-name: slide-rtl; }
.drawer-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 18px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
.drawer-head h2 { font-size: 19px; margin: 4px 0 2px; }
.dl { display: grid; grid-template-columns: 180px 1fr; gap: 8px 14px; margin: 12px 0 0; font-size: 13px; }
.dl dt { color: var(--muted); }
.dl dd { margin: 0; }
@keyframes fade { from { opacity: 0; } }
@keyframes slide { from { transform: translateX(32px); opacity: 0.4; } }
@keyframes slide-rtl { from { transform: translateX(-32px); opacity: 0.4; } }
@media (max-width: 600px) { .drawer { padding: 16px; } .dl { grid-template-columns: 1fr; } }
</style>
