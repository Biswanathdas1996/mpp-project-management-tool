<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { AriaComponent, DatasetComponent, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import type { EChartsCoreOption } from 'echarts/core'
import { useUi } from '@/stores/ui'

echarts.use([BarChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, MarkLineComponent,
  DatasetComponent, AriaComponent, SVGRenderer])

const props = withDefaults(defineProps<{ option: EChartsCoreOption; height?: string; label: string }>(), { height: '280px' })
const emit = defineEmits<{ (e: 'click', p: unknown): void }>()
const el = ref<HTMLDivElement>()
const ui = useUi()
let chart: echarts.ECharts | null = null
let ro: ResizeObserver | null = null

const base = () => ({ backgroundColor: 'transparent', textStyle: { fontFamily: 'Inter, IBM Plex Sans Arabic, sans-serif' },
  aria: { enabled: true } })

function render() {
  if (!el.value) return
  chart?.dispose()
  chart = echarts.init(el.value, ui.theme === 'dark' ? 'dark' : undefined, { renderer: 'svg' })
  chart.setOption({ ...base(), ...props.option }, true)
  chart.on('click', (p) => emit('click', p))
}
onMounted(() => {
  render()
  ro = new ResizeObserver(() => chart?.resize())
  if (el.value) ro.observe(el.value)
})
watch(() => props.option, () => chart?.setOption({ ...base(), ...props.option }, true), { deep: true })
watch(() => ui.theme, render)
onBeforeUnmount(() => {
  ro?.disconnect()
  chart?.dispose()
})
</script>

<template>
  <div ref="el" role="img" :aria-label="label" :style="{ height, width: '100%' }" />
</template>
