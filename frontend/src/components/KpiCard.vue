<script setup lang="ts">
import Icon from './Icon.vue'
import ProgressBar from './ProgressBar.vue'

defineProps<{
  label: string
  value: string
  caption?: string
  tag?: string | null
  tagClass?: string
  bar?: number | null
  barColor?: string
  marker?: number | null
  clickable?: boolean
  small?: boolean
  edge?: string
}>()
const emit = defineEmits<{ (e: 'open'): void }>()
</script>

<template>
  <article class="card kpi" :class="{ clickable }" :style="edge ? { borderInlineStart: `4px solid ${edge}` } : undefined">
    <header class="kpi-head">
      <span class="section-title">{{ label }}</span>
      <span v-if="tag" class="tag pill plain" :class="tagClass || 'neutral'">{{ tag }}</span>
    </header>
    <button v-if="clickable" type="button" class="kpi-value linklike" :class="{ small }"
            :aria-label="`${label}: ${value}. View underlying tasks`" @click="emit('open')">
      <span class="num tnum">{{ value }}</span><Icon name="arrow" :size="16" class="go" />
    </button>
    <div v-else class="kpi-value" :class="{ small }"><span class="num tnum">{{ value }}</span></div>
    <p v-if="caption" class="kpi-caption">{{ caption }}</p>
    <ProgressBar v-if="bar !== undefined && bar !== null" class="kpi-bar" :value="bar" :color="barColor" :marker="marker" :label="label" />
    <slot />
  </article>
</template>

<style scoped>
.kpi { display: flex; flex-direction: column; gap: 8px; min-height: 152px; position: relative; overflow: hidden; }
.kpi.clickable:hover { border-color: var(--border-strong); box-shadow: var(--shadow-md); transform: translateY(-1px); }
.kpi-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; min-height: 24px; }
.kpi-value { font-size: 32px; font-weight: 700; letter-spacing: -0.03em; line-height: 1.1; color: var(--text); display: flex; align-items: center; gap: 8px; text-align: start; }
.kpi-value.small { font-size: 18px; line-height: 1.3; font-weight: 650; letter-spacing: -0.015em; }
.kpi.clickable .kpi-value { cursor: pointer; }
.kpi-value .go { color: var(--muted); opacity: 0; transition: opacity 0.18s var(--ease); }
:root[dir='rtl'] .kpi-value .go { transform: scaleX(-1); }
.kpi.clickable:hover .go, .kpi-value:focus-visible .go { opacity: 1; }
.kpi-caption { color: var(--muted); font-size: 12.5px; line-height: 1.45; }
.kpi-bar { margin-top: auto; }
</style>
