<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { TrendPoint } from '@/api/types'
import { cssVar } from '@/format'
import { useUi } from '@/stores/ui'
import EChart from './EChart.vue'

const props = defineProps<{ points: TrendPoint[] }>()
const emit = defineEmits<{ (e: 'select', snapshotId: number): void }>()
const { t } = useI18n()
const ui = useUi()

const option = computed(() => {
  void ui.theme
  const muted = cssVar('--muted')
  const grid = cssVar('--border')
  return {
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => (v == null ? '—' : `${v.toFixed(1)}%`) },
    legend: { data: [t('trend.planned'), t('trend.actual')], textStyle: { color: muted }, top: 0 },
    grid: { left: 44, right: 16, top: 36, bottom: 30 },
    xAxis: { type: 'category', data: props.points.map((p) => `C${p.cycle} · ${p.as_of}`), axisLabel: { color: muted },
      axisLine: { lineStyle: { color: grid } } },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { color: muted, formatter: '{value}%' }, splitLine: { lineStyle: { color: grid } } },
    series: [
      { name: t('trend.planned'), type: 'line', data: props.points.map((p) => p.planned), symbol: 'circle', symbolSize: 7,
        lineStyle: { type: 'dashed', width: 2, color: cssVar('--c-planned') }, itemStyle: { color: cssVar('--c-planned') } },
      { name: t('trend.actual'), type: 'line', data: props.points.map((p) => p.actual), symbol: 'circle', symbolSize: 8,
        lineStyle: { width: 3, color: cssVar('--brand-2') }, itemStyle: { color: cssVar('--brand-2') },
        areaStyle: { color: cssVar('--brand-2'), opacity: 0.08 } },
    ],
  }
})
function onClick(p: unknown) {
  const idx = (p as { dataIndex?: number }).dataIndex
  if (idx !== undefined && props.points[idx]) emit('select', props.points[idx].snapshot_id)
}
</script>

<template>
  <EChart :option="option" height="280px" label="Planned versus actual progress per reporting cycle" @click="onClick" />
</template>
