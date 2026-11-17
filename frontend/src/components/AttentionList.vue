<script setup lang="ts">
import type { AttentionRow } from '@/api/types'
import { date, severityClass } from '@/format'
import Icon from './Icon.vue'

defineProps<{ items: AttentionRow[]; editable?: boolean }>()
const emit = defineEmits<{
  (e: 'drill', a: AttentionRow): void
  (e: 'edit', a: AttentionRow): void
  (e: 'review', a: AttentionRow, action: 'approve' | 'reject'): void
  (e: 'resolve', a: AttentionRow): void
  (e: 'delete', a: AttentionRow): void
}>()
const ICON: Record<string, string> = { overdue_milestone: 'clock', critical_delay: 'octagon', at_risk: 'alert', overdue_tasks: 'clock',
  missed_deadline: 'calendar-x', overdue_decision: 'scale', overdue_mitigation: 'shield' }
</script>

<template>
  <ul class="att">
    <li v-for="(a, i) in items" :key="a.id ?? `d-${i}`" class="card att-item">
      <span class="ico" :class="severityClass(a.severity)" aria-hidden="true"><Icon :name="ICON[a.category || ''] || 'info'" :size="18" /></span>
      <div class="body">
        <div class="row">
          <span class="pill plain" :class="severityClass(a.severity)">{{ a.severity }}</span>
          <strong>{{ a.title }}</strong>
          <span class="muted small">{{ a.source === 'engine' ? 'Computed from plan' : a.source === 'ai' ? 'AI' : 'Manual' }}</span>
          <span v-if="a.review_status === 'draft'" class="pill info plain">AI draft — needs review</span>
        </div>
        <p v-if="a.description" class="muted small">{{ a.description }}</p>
      </div>
      <span class="tnum small due">{{ a.due_date ? date(a.due_date) : '' }}</span>
      <div class="row acts">
        <button v-if="a.related_task_uids?.length" class="btn btn-sm" @click="emit('drill', a)">Tasks ({{ a.related_task_uids.length }})</button>
        <template v-if="editable && a.id">
          <template v-if="a.review_status === 'draft'">
            <button class="btn btn-sm btn-primary" @click="emit('review', a, 'approve')">Approve</button>
            <button class="btn btn-sm" @click="emit('review', a, 'reject')">Reject</button>
          </template>
          <button v-else-if="a.status !== 'Resolved'" class="btn btn-sm" @click="emit('resolve', a)">Resolve</button>
          <button class="btn btn-sm btn-ghost" @click="emit('edit', a)">Edit</button>
          <button class="btn btn-sm btn-ghost btn-danger" @click="emit('delete', a)">Delete</button>
        </template>
      </div>
    </li>
    <li v-if="!items.length" class="muted all-clear"><Icon name="check" :size="18" />No overdue or at-risk items.</li>
  </ul>
</template>

<style scoped>
.att { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.att-item { display: grid; grid-template-columns: 36px 1fr auto auto; gap: 14px; align-items: center; padding: 12px 16px; box-shadow: none; }
.att-item:hover { border-color: var(--border-strong); }
.ico { width: 36px; height: 36px; border-radius: 10px; display: grid; place-items: center; background: var(--neutral-bg); color: var(--neutral); }
.ico.bad { background: var(--bad-bg); color: var(--bad); }
.ico.warn { background: var(--warn-bg); color: var(--warn); }
.ico.info { background: var(--info-bg); color: var(--info); }
.ico.ok { background: var(--ok-bg); color: var(--ok); }
.body { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.due { color: var(--muted); }
.all-clear { display: flex; align-items: center; gap: 8px; padding: 14px 4px; }
.all-clear .icon { color: var(--ok); }
@media (max-width: 760px) { .att-item { grid-template-columns: 36px 1fr; } .acts, .due { grid-column: 2; } }
</style>
