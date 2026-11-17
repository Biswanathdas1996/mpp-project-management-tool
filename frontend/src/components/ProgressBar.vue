<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{ value: number | null | undefined; color?: string; marker?: number | null; label?: string; height?: number }>(),
  { color: 'var(--brand-2)', marker: null, label: '', height: 6 },
)
const w = computed(() => Math.max(0, Math.min(100, props.value ?? 0)))
</script>

<template>
  <div class="bar" role="progressbar" :aria-valuenow="Math.round(w)" aria-valuemin="0" aria-valuemax="100"
       :aria-label="label || `${Math.round(w)}%`" :style="{ height: `${height}px` }">
    <span :style="{ width: `${w}%`, background: color }" />
    <i v-if="marker !== null && marker !== undefined" class="marker"
       :style="{ insetInlineStart: `calc(${Math.min(100, Math.max(0, marker))}% - 1px)` }"
       :title="`Planned ${marker.toFixed(1)}%`" />
  </div>
</template>
