<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { api, qs } from '@/api/client'
import type { MilestoneRow, Status } from '@/api/types'
import EChart from '@/components/EChart.vue'
import MilestoneTable from '@/components/MilestoneTable.vue'
import Modal from '@/components/Modal.vue'
import StatusPill from '@/components/StatusPill.vue'
import { useDash } from '@/composables/useDash'
import { cssVar, date, pct } from '@/format'
import { useUi } from '@/stores/ui'

interface HistoryPoint { snapshot_id: number; version_no: number; as_of: string; start: string | null; finish: string | null; baseline_finish: string | null; percent_complete: number; planned_percent: number; status: Status; slippage_days: number | null }

const { t } = useI18n()
const route = useRoute()
const ui = useUi()
const { d, store, drillMilestone } = useDash()
const status = ref<string>('')
const track = ref<string>('')
const q = ref('')
const history = ref<{ name: string; points: HistoryPoint[]; finish_moves: number } | null>(null)

const focus = computed(() => Number(route.query.focus) || null)
const rows = computed(() => (d.value?.milestones || []).filter((m) =>
  (!status.value || m.status === status.value) && (!track.value || String(m.track_number) === track.value) &&
  (!q.value || m.name.toLowerCase().includes(q.value.toLowerCase()))))
const tracks = computed(() => [...new Set((d.value?.milestones || []).map((m) => m.track_number))].filter((x) => x !== null))
const counts = computed(() => {
  const c: Record<string, number> = {}
  for (const m of d.value?.milestones || []) c[m.status] = (c[m.status] || 0) + 1
  return c
})

async function openHistory(m: MilestoneRow) {
  try {
    const res = await api.get<{ name: string; points: HistoryPoint[]; finish_moves: number }[]>(
      `/programs/${store.program!.id}/milestone-history${qs({ task_uid: m.task_unique_id })}`)
    history.value = res[0] || { name: m.name, points: [], finish_moves: 0 }
  } catch (e) {
    ui.error(e)
  }
}
const histOption = computed(() => {
  const pts = history.value?.points || []
  const muted = cssVar('--muted')
  return {
    tooltip: { trigger: 'axis' }, legend: { textStyle: { color: muted } },
    grid: { left: 44, right: 50, top: 34, bottom: 28 },
    xAxis: { type: 'category', data: pts.map((p) => p.as_of), axisLabel: { color: muted } },
    yAxis: [{ type: 'value', max: 100, axisLabel: { color: muted, formatter: '{value}%' } },
      { type: 'value', name: 'slip d', axisLabel: { color: muted }, splitLine: { show: false } }],
    series: [
      { name: 'Actual %', type: 'line', data: pts.map((p) => p.percent_complete), itemStyle: { color: cssVar('--brand-2') } },
      { name: 'Planned %', type: 'line', data: pts.map((p) => p.planned_percent), lineStyle: { type: 'dashed' }, itemStyle: { color: cssVar('--c-planned') } },
      { name: 'Slippage (days)', type: 'bar', yAxisIndex: 1, data: pts.map((p) => p.slippage_days ?? 0), itemStyle: { color: cssVar('--c-delay') }, barWidth: 14 },
    ],
  }
})
</script>

<template>
  <div v-if="d">
    <div class="page-head">
      <div><h1>{{ t('nav.milestones') }}</h1>
        <p class="row small">
          <span v-for="(n, s) in counts" :key="s" class="row" style="gap: 4px"><StatusPill :status="s" /> {{ n }}</span>
        </p>
      </div>
      <div class="row">
        <input v-model="q" class="input" style="width: 200px" :placeholder="t('common.search')" aria-label="Search milestones" />
        <select v-model="status" class="input" style="width: 160px" aria-label="Filter by status">
          <option value="">{{ t('common.all') }} statuses</option>
          <option v-for="s in ['completed', 'on_track', 'delay', 'critical_delay', 'not_started']" :key="s" :value="s">{{ t(`status.${s}`) }}</option>
        </select>
        <select v-model="track" class="input" style="width: 130px" aria-label="Filter by track">
          <option value="">{{ t('common.all') }} tracks</option>
          <option v-for="n in tracks" :key="String(n)" :value="String(n)">Track {{ String(n).padStart(2, '0') }}</option>
        </select>
      </div>
    </div>
    <div v-if="focus" class="alert info mb">Highlighted: next milestone — {{ d.milestones.find((m) => m.id === focus)?.name }}</div>
    <MilestoneTable :milestones="rows" @open="(m) => drillMilestone(m.id, `Milestone ${String(m.number).padStart(2, '0')} · ${m.name}`)" @history="openHistory" />

    <Modal v-if="history" :title="`Milestone history · ${history.name}`" wide @close="history = null">
      <p class="muted mb">Tracked across {{ history.points.length }} snapshots (matched by Unique ID) · finish date moved {{ history.finish_moves }} times.</p>
      <EChart v-if="history.points.length" :option="histOption" height="260px" label="Milestone progress and slippage over snapshots" />
      <div class="table-wrap mt">
        <table class="table">
          <thead><tr><th>Snapshot</th><th>As of</th><th>Start</th><th>Finish</th><th>Baseline finish</th><th>Actual</th><th>Planned</th><th>Status</th><th>Slip</th></tr></thead>
          <tbody>
            <tr v-for="p in history.points" :key="p.snapshot_id">
              <td>v{{ p.version_no }}</td><td class="tnum">{{ date(p.as_of) }}</td><td class="tnum">{{ date(p.start) }}</td><td class="tnum">{{ date(p.finish) }}</td>
              <td class="tnum muted">{{ date(p.baseline_finish) }}</td><td class="tnum">{{ pct(p.percent_complete) }}</td><td class="tnum">{{ pct(p.planned_percent) }}</td>
              <td><StatusPill :status="p.status" /></td><td class="tnum">{{ p.slippage_days ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </Modal>
  </div>
</template>
