<script setup lang="ts">
// Extended KPI catalogue: every KPI the data supports (admin-approved set), grouped by category,
// with formula, version and drill-down. Unavailable KPIs show why.
import { computed, ref, watch } from 'vue'
import { api, qs } from '@/api/client'
import type { KPIItem } from '@/api/types'
import EChart from '@/components/EChart.vue'
import Icon from '@/components/Icon.vue'
import { useDash } from '@/composables/useDash'
import { cssVar, num } from '@/format'
import { useUi } from '@/stores/ui'

const ui = useUi()
const { sid, drillKpi } = useDash()
const kpis = ref<KPIItem[]>([])
const engine = ref('')
const showAll = ref(false)
const showUnavailable = ref(false)
const loading = ref(false)
const open = ref<KPIItem | null>(null)

async function load() {
  if (!sid.value) return
  loading.value = true
  try {
    const r = await api.get<{ kpis: KPIItem[]; engine_version: string }>(`/snapshots/${sid.value}/kpis${qs({ all: showAll.value })}`)
    kpis.value = r.kpis
    engine.value = r.engine_version
  } catch (e) {
    ui.error(e)
  } finally {
    loading.value = false
  }
}
watch([sid, showAll], load, { immediate: true })

const CATS: Record<string, string> = { reference: 'Reference dashboard', schedule: 'Schedule', progress: 'Progress', cost: 'Cost & effort (earned value)',
  resources: 'Resources', quality: 'Plan quality', change: 'Change', governance: 'Governance' }
const grouped = computed(() => {
  const out: Record<string, KPIItem[]> = {}
  for (const k of kpis.value) {
    if (!showUnavailable.value && !k.available) continue
    ;(out[k.category] ||= []).push(k)
  }
  return Object.keys(CATS).filter((c) => out[c]?.length).map((c) => ({ cat: c, label: CATS[c], items: out[c] }))
})
const stats = computed(() => ({ total: kpis.value.length, available: kpis.value.filter((k) => k.available).length }))

function seriesOption(k: KPIItem) {
  const det = k.details || {}
  const muted = cssVar('--muted')
  const axis = { axisLabel: { color: muted }, splitLine: { lineStyle: { color: cssVar('--border') } } }
  if (k.code === 's_curve') {
    return { tooltip: { trigger: 'axis' }, legend: { textStyle: { color: muted } }, grid: { left: 40, right: 16, top: 30, bottom: 26 },
      xAxis: { type: 'time', ...axis }, yAxis: { type: 'value', max: 100, ...axis },
      series: [{ name: 'Planned (baseline)', type: 'line', showSymbol: false, data: det.planned.map((p: any) => [p.date, p.planned]), itemStyle: { color: cssVar('--c-planned') } },
        { name: 'Actual', type: 'line', data: det.actual.map((p: any) => [p.date, p.actual]), itemStyle: { color: cssVar('--brand-2') } }] }
  }
  if (k.code === 'burn_up') {
    return { tooltip: { trigger: 'axis' }, legend: { textStyle: { color: muted } }, grid: { left: 40, right: 16, top: 30, bottom: 26 },
      xAxis: { type: 'category', data: det.series.map((p: any) => p.date), ...axis }, yAxis: { type: 'value', ...axis },
      series: [{ name: 'Scope', type: 'line', data: det.series.map((p: any) => p.scope), itemStyle: { color: cssVar('--c-planned') } },
        { name: 'Completed', type: 'line', areaStyle: { opacity: 0.1 }, data: det.series.map((p: any) => p.completed), itemStyle: { color: cssVar('--c-on-track') } }] }
  }
  if (k.code === 'weekly_velocity') {
    return { tooltip: { trigger: 'axis' }, grid: { left: 40, right: 16, top: 20, bottom: 26 },
      xAxis: { type: 'category', data: det.series.map((p: any) => p.as_of), ...axis }, yAxis: { type: 'value', ...axis },
      series: [{ type: 'bar', data: det.series.map((p: any) => p.velocity), itemStyle: { color: cssVar('--brand-2') } }] }
  }
  if (k.code === 'slippage_trend' && det.series?.length) {
    return { tooltip: { trigger: 'axis' }, grid: { left: 40, right: 16, top: 20, bottom: 26 },
      xAxis: { type: 'category', data: det.series.map((p: any) => p.date), ...axis }, yAxis: { type: 'value', name: 'days', ...axis },
      series: [{ type: 'line', data: det.series.map((p: any) => p.slippage_days), itemStyle: { color: cssVar('--c-critical') } }] }
  }
  return null
}
function rowsOf(k: KPIItem): Record<string, unknown>[] | null {
  const r = k.details?.rows || k.details?.checks
  return Array.isArray(r) && r.length ? r : null
}
function scalarDetails(k: KPIItem) {
  return Object.entries(k.details || {}).filter(([, v]) => v !== null && typeof v !== 'object')
}
function fmt(v: unknown) {
  if (typeof v === 'number') return num(v, Number.isInteger(v) ? 0 : 2)
  if (typeof v === 'boolean') return v ? '✓' : '✗'
  return String(v ?? '—')
}
</script>

<template>
  <div>
    <div class="page-head">
      <div><h1>KPI catalogue</h1>
        <p>{{ stats.available }} of {{ stats.total }} KPIs computable from this snapshot · deterministic engine v{{ engine }} · {{ showAll ? 'showing all KPIs' : 'showing the admin-approved set' }}</p></div>
      <div class="row">
        <label class="check"><input v-model="showUnavailable" type="checkbox" /> Show unavailable</label>
        <label class="check"><input v-model="showAll" type="checkbox" /> Include non-approved</label>
      </div>
    </div>
    <div v-if="loading" class="empty"><span class="spinner" /></div>
    <section v-for="g in grouped" :key="g.cat" class="mb">
      <h2 class="mb">{{ g.label }}</h2>
      <div class="grid grid-kpi">
        <article v-for="k in g.items" :key="k.code" class="card kc" :class="{ off: !k.available }">
          <div class="row"><span class="section-title">{{ k.name }}</span><span class="spacer" /><span class="muted small" :title="`Formula version ${k.version}`">{{ k.phase }} · v{{ k.version }}</span></div>
          <div class="val tnum">{{ k.available ? (k.display ?? '—') : 'n/a' }}</div>
          <p v-if="!k.available" class="muted small">{{ k.reason }}</p>
          <p class="muted small formula" :title="k.formula">{{ k.formula }}</p>
          <div class="row">
            <button v-if="k.available && (k.drill_count || 0) > 0" class="btn btn-sm" @click="drillKpi(k.code, k.name)">{{ k.drill_count }} tasks</button>
            <button v-if="k.available && (rowsOf(k) || seriesOption(k) || scalarDetails(k).length)" class="btn btn-sm btn-ghost" @click="open = k">Details</button>
          </div>
        </article>
      </div>
    </section>
    <div v-if="!loading && !grouped.length" class="empty">No KPIs to show.</div>

    <div v-if="open" class="backdrop" @mousedown.self="open = null">
      <section class="card panel" role="dialog" aria-modal="true" :aria-label="open.name">
        <div class="card-head"><h2>{{ open.name }} <span class="muted">· {{ open.display }}</span></h2><button class="btn btn-ghost btn-sm btn-icon" aria-label="Close" @click="open = null"><Icon name="x" /></button></div>
        <p class="muted small mb">{{ open.formula }} · source fields: {{ open.source_fields?.join(', ') }}</p>
        <EChart v-if="seriesOption(open)" :option="seriesOption(open)!" height="260px" :label="open.name" />
        <dl v-if="scalarDetails(open).length" class="dl">
          <template v-for="[k, v] in scalarDetails(open)" :key="k"><dt>{{ String(k).replace(/_/g, ' ') }}</dt><dd class="tnum">{{ fmt(v) }}</dd></template>
        </dl>
        <div v-if="rowsOf(open)" class="table-wrap mt">
          <table class="table">
            <thead><tr><th v-for="c in Object.keys(rowsOf(open)![0])" :key="c">{{ c.replace(/_/g, ' ') }}</th></tr></thead>
            <tbody><tr v-for="(r, i) in rowsOf(open)" :key="i"><td v-for="c in Object.keys(rowsOf(open)![0])" :key="c" class="tnum">{{ fmt(r[c]) }}</td></tr></tbody>
          </table>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.kc { display: flex; flex-direction: column; gap: 6px; }
.kc.off { opacity: 0.7; border-style: dashed; }
.val { font-size: 24px; font-weight: 700; }
.formula { display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.backdrop { position: fixed; inset: 0; background: rgb(2 6 23 / 0.5); display: grid; place-items: center; z-index: 60; padding: 16px; }
.panel { width: min(980px, 100%); max-height: calc(100vh - 32px); overflow: auto; }
.dl { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr) minmax(120px, 1fr)); gap: 6px 12px; margin: 12px 0 0; font-size: 13px; }
.dl dt { color: var(--muted); text-transform: capitalize; }
.dl dd { margin: 0; font-weight: 600; }
</style>
