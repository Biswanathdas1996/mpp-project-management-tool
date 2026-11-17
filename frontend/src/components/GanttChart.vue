<script setup lang="ts">
// Monthly-column Gantt: bar per milestone with filled progress + % label, plan-to-date marker,
// red Today line and the full legend from the reference spec.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Dashboard } from '@/api/types'
import { date, STATUS_COLOR_VAR, two } from '@/format'

const props = defineProps<{ gantt: Dashboard['gantt'] }>()
const emit = defineEmits<{ (e: 'open', milestoneId: number): void }>()
const { t } = useI18n()

const DAY = 86400000
const range = computed(() => {
  const r = props.gantt.range
  if (!r) return null
  const s = new Date(`${r.start}T00:00:00`).getTime()
  const e = new Date(`${r.end}T00:00:00`).getTime() + DAY
  return { s, e, span: e - s }
})
const pos = (d: string) => (range.value ? ((new Date(`${d}T00:00:00`).getTime() - range.value.s) / range.value.span) * 100 : 0)
const todayPos = computed(() => pos(props.gantt.today))
const months = computed(() => props.gantt.months.map((m) => ({ ...m, left: pos(m.start), width: pos(m.end) - pos(m.start) + (DAY / (range.value?.span || 1)) * 100 })))
const bars = computed(() => props.gantt.items.map((it) => {
  const left = pos(it.start)
  const right = pos(it.finish) + (DAY / (range.value?.span || 1)) * 100
  const plannedAt = left + ((right - left) * Math.min(100, Math.max(0, it.planned_percent))) / 100
  return { ...it, left, width: Math.max(right - left, 0.6), plannedAt }
}))
const legend = computed(() => [
  { key: 'on_track', color: STATUS_COLOR_VAR.on_track }, { key: 'completed', color: STATUS_COLOR_VAR.completed },
  { key: 'delay', color: STATUS_COLOR_VAR.delay }, { key: 'critical_delay', color: STATUS_COLOR_VAR.critical_delay },
  { key: 'not_started', color: STATUS_COLOR_VAR.not_started },
])
</script>

<template>
  <div v-if="!range" class="empty">No dated milestones.</div>
  <div v-else class="gantt-wrap">
    <div class="legend" :aria-label="t('gantt.legend')">
      <span v-for="l in legend" :key="l.key" class="lg"><i :style="{ background: l.color }" />{{ t(`status.${l.key}`) }}</span>
      <span class="lg"><i class="today-swatch" />{{ t('gantt.today') }}</span>
      <span class="lg"><i class="plan-swatch" />{{ t('gantt.planToDate') }}</span>
    </div>
    <div class="gantt" role="table" aria-label="Milestone timeline">
      <div class="g-row g-head" role="row">
        <div class="g-label" role="columnheader">{{ t('ms.milestone') }}</div>
        <div class="g-track" role="columnheader">
          <span v-for="m in months" :key="m.key" class="g-month" :style="{ insetInlineStart: `${m.left}%`, width: `${m.width}%` }">{{ m.label }}</span>
        </div>
      </div>
      <div v-for="b in bars" :key="b.milestone_id" class="g-row" role="row">
        <div class="g-label" role="cell">
          <button class="linklike" @click="emit('open', b.milestone_id)">
            <span class="muted tnum">{{ two(b.number) }}</span> {{ b.name }}
          </button>
        </div>
        <div class="g-track" role="cell">
          <span v-for="m in months" :key="m.key" class="g-grid" :style="{ insetInlineStart: `${m.left}%` }" />
          <button class="g-bar" :class="{ point: b.is_point }"
                  :style="{ insetInlineStart: `${b.left}%`, width: `${b.width}%`, '--c': STATUS_COLOR_VAR[b.status] } as any"
                  :title="`${b.name}: ${date(b.start)} – ${date(b.finish)} · ${b.percent_complete.toFixed(0)}% (plan ${b.planned_percent.toFixed(0)}%)`"
                  :aria-label="`${b.name}, ${t('status.' + b.status)}, ${b.percent_complete.toFixed(0)}% complete`"
                  @click="emit('open', b.milestone_id)">
            <span class="g-fill" :style="{ width: `${b.percent_complete}%` }" />
          </button>
          <span class="g-plan" :style="{ insetInlineStart: `${b.plannedAt}%` }" aria-hidden="true" />
          <span class="g-pct tnum" :style="{ insetInlineStart: `calc(${b.left + b.width}% + 6px)` }">{{ b.percent_complete.toFixed(0) }}%</span>
        </div>
      </div>
      <div class="g-today" :style="{ insetInlineStart: `calc(var(--label-w) + (100% - var(--label-w)) * ${todayPos / 100})` }"
           :title="`${t('gantt.today')} ${gantt.today}`"><span>{{ t('gantt.today') }}</span></div>
    </div>
  </div>
</template>

<style scoped>
.gantt-wrap { overflow-x: auto; }
.legend { display: flex; flex-wrap: wrap; gap: 14px; margin-bottom: 10px; font-size: 12px; color: var(--text-2); }
.lg { display: inline-flex; align-items: center; gap: 6px; }
.lg i { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
.today-swatch { background: var(--c-today); width: 3px !important; }
.plan-swatch { background: transparent; border: 2px solid var(--text); width: 4px !important; height: 14px !important; border-radius: 1px !important; }
.gantt { --label-w: 280px; position: relative; min-width: 900px; }
.g-row { display: flex; align-items: center; min-height: 36px; border-bottom: 1px solid var(--border); }
.g-head { min-height: 30px; position: sticky; top: 0; background: var(--surface); z-index: 2; }
.g-label { width: var(--label-w); flex: none; padding-inline-end: 10px; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.g-track { position: relative; flex: 1; height: 36px; }
.g-head .g-track { height: 30px; }
.g-month { position: absolute; top: 0; height: 100%; display: flex; align-items: center; justify-content: center; font-size: 11px; color: var(--muted); border-inline-start: 1px solid var(--border); }
.g-grid { position: absolute; top: 0; bottom: 0; border-inline-start: 1px dashed var(--border); }
.g-bar { position: absolute; top: 9px; height: 18px; border-radius: 5px; border: 1px solid var(--c); background: color-mix(in srgb, var(--c) 22%, transparent); padding: 0; overflow: hidden; cursor: pointer; }
.g-bar.point { width: 14px !important; height: 14px; top: 11px; transform: rotate(45deg); border-radius: 2px; }
.g-fill { display: block; height: 100%; background: var(--c); }
.g-plan { position: absolute; top: 5px; height: 26px; width: 2px; background: var(--text); opacity: 0.7; }
.g-pct { position: absolute; top: 9px; font-size: 11.5px; color: var(--text-2); white-space: nowrap; }
.g-today { position: absolute; top: 0; bottom: 0; width: 2px; background: var(--c-today); z-index: 3; pointer-events: none; }
.g-today span { position: absolute; top: -2px; inset-inline-start: 4px; font-size: 10px; font-weight: 700; color: var(--c-today); background: var(--surface); padding: 0 3px; }
</style>
