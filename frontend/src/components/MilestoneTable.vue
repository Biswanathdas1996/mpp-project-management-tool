<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { MilestoneRow } from '@/api/types'
import { date, healthClass, pct, pts, STATUS_COLOR_VAR, two, varianceClass } from '@/format'
import ProgressBar from './ProgressBar.vue'
import StatusPill from './StatusPill.vue'

defineProps<{ milestones: MilestoneRow[]; compact?: boolean }>()
const emit = defineEmits<{ (e: 'open', m: MilestoneRow): void; (e: 'history', m: MilestoneRow): void }>()
const { t } = useI18n()
</script>

<template>
  <div class="table-wrap">
    <table class="table">
      <caption class="sr-only">Milestones</caption>
      <thead>
        <tr>
          <th scope="col">{{ t('ms.num') }}</th><th scope="col">{{ t('ms.milestone') }}</th><th scope="col">{{ t('ms.track') }}</th>
          <th scope="col">{{ t('ms.timeline') }}</th><th scope="col">{{ t('ms.status') }}</th><th scope="col">{{ t('ms.health') }}</th>
          <th scope="col" style="min-width: 150px">{{ t('ms.progress') }}</th><th scope="col">{{ t('ms.variance') }}</th>
          <th v-if="!compact" scope="col">Slippage</th><th v-if="!compact" scope="col"><span class="sr-only">History</span></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="m in milestones" :key="m.id" class="clickable" tabindex="0" @click="emit('open', m)" @keydown.enter="emit('open', m)">
          <td class="tnum muted">{{ two(m.number) }}</td>
          <td><strong>{{ m.name }}</strong><span v-if="m.is_critical" class="muted small"> · critical path</span></td>
          <td><span class="tnum">{{ two(m.track_number) }}</span><span v-if="!compact" class="muted small"> · {{ m.track_name }}</span></td>
          <td class="tnum" style="white-space: nowrap">{{ date(m.start) }} – {{ date(m.finish) }}</td>
          <td><StatusPill :status="m.status" /></td>
          <td><span class="pill plain" :class="healthClass(m.health)">{{ m.health?.label }}</span></td>
          <td>
            <div class="row" style="flex-wrap: nowrap; gap: 8px">
              <ProgressBar :value="m.percent_complete" :marker="m.planned_percent" :color="STATUS_COLOR_VAR[m.status]" style="flex: 1" :label="`${m.name} progress`" />
              <span class="tnum small" style="min-width: 44px">{{ pct(m.percent_complete, 0) }}</span>
            </div>
          </td>
          <td><span class="pill plain" :class="varianceClass(m.variance_pts)">{{ pts(m.variance_pts) }}</span></td>
          <td v-if="!compact" class="tnum">{{ m.slippage_days === null ? '—' : `${m.slippage_days > 0 ? '+' : ''}${m.slippage_days} d` }}</td>
          <td v-if="!compact"><button class="btn btn-sm btn-ghost" @click.stop="emit('history', m)">History</button></td>
        </tr>
        <tr v-if="!milestones.length"><td colspan="10" class="empty">No milestones mapped.</td></tr>
      </tbody>
    </table>
  </div>
</template>
