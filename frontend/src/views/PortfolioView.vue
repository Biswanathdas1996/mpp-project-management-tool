<script setup lang="ts">
// Portfolio roll-up (v2): every programme's latest snapshot side by side.
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { PortfolioRow } from '@/api/types'
import EChart from '@/components/EChart.vue'
import ProgressBar from '@/components/ProgressBar.vue'
import { cssVar, date, int, num, pct, pts, varianceClass } from '@/format'
import { useUi } from '@/stores/ui'

interface Summary { programs: number; reporting: number; avg_completion: number; avg_planned: number; critical_delays: number; high_risks: number; pending_decisions: number; behind_plan: number }
const { t, locale } = useI18n()
const ui = useUi()
const router = useRouter()
const rows = ref<PortfolioRow[]>([])
const summary = ref<Summary | null>(null)

onMounted(async () => {
  try {
    const r = await api.get<{ summary: Summary | null; programs: PortfolioRow[] }>('/portfolio')
    rows.value = r.programs
    summary.value = r.summary
  } catch (e) {
    ui.error(e)
  }
})
const option = computed(() => {
  void ui.theme
  const data = rows.value.filter((r) => r.completion !== null)
  const muted = cssVar('--muted')
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } }, legend: { textStyle: { color: muted } },
    grid: { left: 180, right: 20, top: 30, bottom: 20 },
    xAxis: { type: 'value', max: 100, axisLabel: { color: muted, formatter: '{value}%' } },
    yAxis: { type: 'category', inverse: true, data: data.map((r) => r.name.slice(0, 26)), axisLabel: { color: cssVar('--text-2') } },
    series: [{ name: t('trend.planned'), type: 'bar', data: data.map((r) => r.planned), itemStyle: { color: cssVar('--neutral-bg') }, barGap: '-100%', barWidth: 18 },
      { name: t('trend.actual'), type: 'bar', data: data.map((r) => r.completion), itemStyle: { color: cssVar('--brand-2') }, barWidth: 10 }],
  }
})
const TAG: Record<string, string> = { 'On Track': 'ok', Completed: 'info', Delay: 'warn', 'Critical Delay': 'bad' }
</script>

<template>
  <main id="main" class="page" tabindex="-1">
    <div class="page-head"><div><h1>{{ t('nav.portfolio') }}</h1><p>Roll-up of the latest processed snapshot of every active programme.</p></div></div>
    <section v-if="summary" class="grid grid-kpi mb">
      <div class="card"><span class="section-title">Programmes reporting</span><div class="big">{{ summary.reporting }}/{{ summary.programs }}</div></div>
      <div class="card"><span class="section-title">Average completion</span><div class="big">{{ pct(summary.avg_completion) }}</div><p class="muted small">planned {{ pct(summary.avg_planned) }}</p></div>
      <div class="card"><span class="section-title">Behind plan (&gt; 5 pts)</span><div class="big">{{ summary.behind_plan }}</div></div>
      <div class="card"><span class="section-title">Critical-delay milestones</span><div class="big">{{ summary.critical_delays }}</div></div>
      <div class="card"><span class="section-title">High risks</span><div class="big">{{ summary.high_risks }}</div></div>
      <div class="card"><span class="section-title">Pending decisions</span><div class="big">{{ summary.pending_decisions }}</div></div>
    </section>
    <section v-if="rows.some((r) => r.completion !== null)" class="card mb">
      <h2 class="mb">Planned vs actual by programme</h2>
      <EChart :option="option" :height="`${Math.max(200, rows.length * 44 + 60)}px`" label="Planned versus actual completion by programme" />
    </section>
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>Programme</th><th>As of</th><th>Status</th><th style="min-width: 150px">Completion</th><th>Variance</th><th>SPI</th><th>Tracks</th><th>Milestones (crit./delay)</th><th>Overdue tasks</th><th>High risks</th><th>Decisions (overdue)</th></tr></thead>
        <tbody>
          <tr v-for="r in rows" :key="r.program_id" class="clickable" tabindex="0" @click="router.push(`/p/${r.program_id}/overview`)" @keydown.enter="router.push(`/p/${r.program_id}/overview`)">
            <td><strong>{{ (locale === 'ar' && r.name_ar) || r.name }}</strong><div class="muted small">{{ r.client_name }}</div></td>
            <td class="tnum">{{ date(r.as_of) }}</td>
            <td><span v-if="r.tag" class="pill" :class="TAG[r.tag]">{{ r.tag }}</span><span v-else class="muted">no data</span></td>
            <td><div class="row" style="flex-wrap: nowrap"><ProgressBar :value="r.completion" :marker="r.planned" style="flex: 1" /><span class="tnum small">{{ pct(r.completion) }}</span></div></td>
            <td><span class="pill plain" :class="varianceClass(r.variance_pts)">{{ pts(r.variance_pts) }}</span></td>
            <td class="tnum">{{ num(r.spi, 2) }}</td>
            <td class="tnum">{{ int(r.active_tracks) }}/{{ int(r.tracks) }}</td>
            <td class="tnum">{{ int(r.milestones) }} ({{ int(r.critical_delays) }}/{{ int(r.delays) }})</td>
            <td class="tnum">{{ int(r.overdue_tasks) }}</td>
            <td class="tnum">{{ r.high_risks }}</td>
            <td class="tnum">{{ r.pending_decisions }} ({{ r.overdue_decisions }})</td>
          </tr>
          <tr v-if="!rows.length"><td colspan="11" class="empty">No programmes.</td></tr>
        </tbody>
      </table>
    </div>
  </main>
</template>

<style scoped>.big { font-size: 26px; font-weight: 700; margin-top: 4px; }</style>
