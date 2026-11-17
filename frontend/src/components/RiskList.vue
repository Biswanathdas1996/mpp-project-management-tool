<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { RiskItem } from '@/api/types'
import { date, severityClass } from '@/format'

defineProps<{ items: RiskItem[]; editable?: boolean }>()
const emit = defineEmits<{ (e: 'edit', r: RiskItem): void; (e: 'review', r: RiskItem, action: 'approve' | 'reject'): void; (e: 'delete', r: RiskItem): void }>()
const { t, locale } = useI18n()
const today = new Date().toISOString().slice(0, 10)
</script>

<template>
  <div class="stack">
    <article v-for="r in items" :key="r.id" class="card risk">
      <div class="sev"><span class="pill" :class="severityClass(r.severity)">{{ r.severity }}</span></div>
      <div class="body">
        <div class="row">
          <h3>{{ (locale === 'ar' && r.title_ar) || r.title }}</h3>
          <span class="muted small">{{ r.status }}</span>
          <span v-if="r.source === 'ai'" class="pill info plain">AI</span>
          <span v-if="r.review_status === 'draft'" class="pill info plain">{{ t('gov.draft') }}</span>
        </div>
        <p v-if="r.description" class="desc">{{ r.description }}</p>
        <p v-if="r.mitigation" class="mit"><strong>{{ t('gov.mitigation') }}:</strong> {{ r.mitigation }}</p>
      </div>
      <dl class="meta">
        <div><dt>{{ t('gov.actionOwner') }}</dt><dd>{{ r.owner || '—' }}</dd></div>
        <div><dt>{{ t('gov.dueDate') }}</dt><dd class="tnum" :class="{ overdue: r.due_date && r.due_date < today && r.status !== 'Closed' }">{{ date(r.due_date) }}</dd></div>
      </dl>
      <div v-if="editable" class="row actions">
        <template v-if="r.review_status === 'draft'">
          <button class="btn btn-sm btn-primary" @click="emit('review', r, 'approve')">{{ t('gov.approve') }}</button>
          <button class="btn btn-sm" @click="emit('review', r, 'reject')">{{ t('gov.reject') }}</button>
        </template>
        <button class="btn btn-sm btn-ghost" @click="emit('edit', r)">{{ t('gov.edit') }}</button>
        <button class="btn btn-sm btn-ghost btn-danger" @click="emit('delete', r)">{{ t('gov.delete') }}</button>
      </div>
    </article>
    <p v-if="!items.length" class="muted">{{ t('gov.none') }}</p>
  </div>
</template>

<style scoped>
.risk { display: grid; grid-template-columns: 90px 1fr 220px; gap: 14px; align-items: start; }
.body { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.desc { color: var(--text-2); font-size: 13px; }
.mit { font-size: 13px; }
.meta { margin: 0; display: grid; gap: 6px; font-size: 12.5px; }
.meta dt { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
.meta dd { margin: 0; font-weight: 550; }
.overdue { color: var(--bad); }
.actions { grid-column: 1 / -1; justify-content: flex-end; }
@media (max-width: 760px) { .risk { grid-template-columns: 1fr; } }
</style>
