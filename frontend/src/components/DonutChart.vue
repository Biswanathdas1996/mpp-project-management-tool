<script setup lang="ts">
import { computed } from 'vue'
import { cssVar } from '@/format'
import { useUi } from '@/stores/ui'
import EChart from './EChart.vue'

const props = defineProps<{ percent: number; label: string; sub?: string }>()
const ui = useUi()
const option = computed(() => {
  void ui.theme
  const p = Math.max(0, Math.min(100, props.percent || 0))
  return {
    tooltip: { show: false },
    series: [{
      type: 'pie', radius: ['68%', '86%'], silent: true, label: { show: false }, startAngle: 90,
      data: [
        { value: p, itemStyle: { color: cssVar('--brand-2') || '#2563eb', borderRadius: 8 } },
        { value: 100 - p, itemStyle: { color: cssVar('--neutral-bg') || '#e2e8f0' } },
      ],
    }],
  }
})
</script>

<template>
  <div class="donut">
    <EChart :option="option" height="220px" :label="`${label}: ${percent.toFixed(1)}% complete`" />
    <div class="center" aria-hidden="true">
      <strong class="tnum">{{ percent.toFixed(1) }}%</strong>
      <span class="muted small">{{ sub }}</span>
    </div>
  </div>
</template>

<style scoped>
.donut { position: relative; }
.center { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; pointer-events: none; }
.center strong { font-size: 30px; }
</style>
