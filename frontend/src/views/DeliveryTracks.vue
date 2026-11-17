<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import EChart from '@/components/EChart.vue'
import TrackCards from '@/components/TrackCards.vue'
import { useDash } from '@/composables/useDash'
import { cssVar, date, pct, pts, varianceClass } from '@/format'
import StatusPill from '@/components/StatusPill.vue'
import { useUi } from '@/stores/ui'

const { t } = useI18n()
const ui = useUi()
const { d, drillTrack } = useDash()

const option = computed(() => {
  void ui.theme
  const tracks = d.value?.tracks || []
  const muted = cssVar('--muted')
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v: number) => `${v.toFixed(1)}%` },
    legend: { data: [t('trend.planned'), t('trend.actual')], textStyle: { color: muted } },
    grid: { left: 200, right: 24, top: 30, bottom: 20 },
    xAxis: { type: 'value', max: 100, axisLabel: { color: muted, formatter: '{value}%' }, splitLine: { lineStyle: { color: cssVar('--border') } } },
    yAxis: { type: 'category', inverse: true, data: tracks.map((x) => `${x.label}  ${x.name.slice(0, 26)}`), axisLabel: { color: cssVar('--text-2') } },
    series: [
      { name: t('trend.planned'), type: 'bar', data: tracks.map((x) => x.planned), itemStyle: { color: cssVar('--neutral-bg') }, barGap: '-100%', barWidth: 18 },
      { name: t('trend.actual'), type: 'bar', data: tracks.map((x) => ({ value: x.actual, itemStyle: { color: cssVar({ completed: '--c-completed', on_track: '--c-on-track', delay: '--c-delay', critical_delay: '--c-critical', not_started: '--c-not-started' }[x.status]) } })), barWidth: 10 },
    ],
  }
})
function onBar(p: unknown) {
  const i = (p as { dataIndex: number }).dataIndex
  const tr = d.value?.tracks[i]
  if (tr) drillTrack(tr.id, `${tr.label} · ${tr.name}`)
}
</script>

<template>
  <div v-if="d">
    <div class="page-head"><div><h1>{{ t('nav.tracks') }}</h1><p>{{ t('sections.source', { s: d.tracks[0]?.source_label || '—' }) }} · click any track to see its tasks</p></div></div>
    <TrackCards :tracks="d.tracks" detailed @open="(tr) => drillTrack(tr.id, `${tr.label} · ${tr.name}`)" />
    <section class="card mt">
      <div class="card-head"><h2>Planned vs actual by track</h2><span class="src">duration-weighted roll-up of leaf tasks</span></div>
      <EChart :option="option" :height="`${Math.max(220, d.tracks.length * 42 + 60)}px`" label="Planned versus actual percent complete by track" @click="onBar" />
    </section>
    <section class="mt">
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>Track</th><th>Name</th><th>Status</th><th>Actual</th><th>Planned</th><th>Variance</th><th>Start</th><th>Finish</th><th>Tasks</th></tr></thead>
          <tbody>
            <tr v-for="tr in d.tracks" :key="tr.id" class="clickable" tabindex="0" @click="drillTrack(tr.id, `${tr.label} · ${tr.name}`)" @keydown.enter="drillTrack(tr.id)">
              <td class="tnum">{{ tr.label }}</td><td><strong>{{ tr.name }}</strong></td><td><StatusPill :status="tr.status" /></td>
              <td class="tnum">{{ pct(tr.actual) }}</td><td class="tnum">{{ pct(tr.planned) }}</td>
              <td><span class="pill plain" :class="varianceClass(tr.variance)">{{ pts(tr.variance) }}</span></td>
              <td class="tnum">{{ date(tr.start) }}</td><td class="tnum">{{ date(tr.finish) }}</td><td class="tnum">{{ tr.leaf_count }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
