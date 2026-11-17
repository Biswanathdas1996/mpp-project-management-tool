<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { TrackRow } from '@/api/types'
import { pct, pts, STATUS_COLOR_VAR, varianceClass } from '@/format'
import ProgressBar from './ProgressBar.vue'
import StatusPill from './StatusPill.vue'

defineProps<{ tracks: TrackRow[]; detailed?: boolean }>()
const emit = defineEmits<{ (e: 'open', t: TrackRow): void }>()
const { locale } = useI18n()
</script>

<template>
  <div class="tracks">
    <button v-for="tr in tracks" :key="tr.id" type="button" class="track card linklike"
            :aria-label="`${tr.label} ${tr.name}: ${pct(tr.actual)} — view tasks`" @click="emit('open', tr)">
      <div class="row track-top">
        <span class="section-title">{{ tr.label }}</span>
        <span class="spacer" />
        <StatusPill :status="tr.status" />
      </div>
      <h3 class="track-name">{{ (locale === 'ar' && tr.name_ar) || tr.name }}</h3>
      <div class="row track-num">
        <span class="big tnum">{{ pct(tr.actual) }}</span>
        <span v-if="detailed || tr.started" class="pill plain small" :class="varianceClass(tr.variance)">{{ pts(tr.variance) }}</span>
      </div>
      <ProgressBar :value="tr.actual" :marker="tr.planned" :color="STATUS_COLOR_VAR[tr.status]" :label="`${tr.name} progress`" />
      <p v-if="detailed" class="muted small">Planned {{ pct(tr.planned) }} · {{ tr.leaf_count }} tasks · {{ tr.start }} → {{ tr.finish }}</p>
    </button>
  </div>
</template>

<style scoped>
.tracks { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(220px, 100%), 1fr)); gap: 12px; }
.track { text-align: start; display: flex; flex-direction: column; gap: 8px; cursor: pointer; padding: 14px 16px; background: var(--surface-2); box-shadow: none; }
.track:hover { background: var(--surface); }
.track-name { font-size: 14px; min-height: 2.5em; color: var(--text); }
.track-num { gap: 8px; }
.big { font-size: 24px; font-weight: 700; letter-spacing: -0.025em; }
</style>
