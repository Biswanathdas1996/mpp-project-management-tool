<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { DecisionItem } from '@/api/types'
import { date, decisionStatusClass, priorityClass } from '@/format'

defineProps<{ items: DecisionItem[]; editable?: boolean }>()
const emit = defineEmits<{ (e: 'edit', d: DecisionItem): void; (e: 'review', d: DecisionItem, action: 'approve' | 'reject'): void; (e: 'delete', d: DecisionItem): void }>()
const { t, locale } = useI18n()
const EDGE: Record<string, string> = { High: 'var(--c-critical)', Medium: 'var(--c-delay)', Low: 'var(--c-not-started)' }
</script>

<template>
  <div class="grid grid-3">
    <article v-for="d in items" :key="d.id" class="card dec">
      <span class="edge" :style="{ background: EDGE[d.priority] }" aria-hidden="true" />
      <div class="row">
        <span class="pill plain" :class="priorityClass(d.priority)">{{ d.priority }}</span>
        <span class="pill" :class="decisionStatusClass(d.status)">{{ d.status }}</span>
        <span class="muted small">{{ d.kind === 'support' ? 'Support request' : 'Decision' }}</span>
        <span class="spacer" />
        <span v-if="d.source === 'ai'" class="pill info plain" title="AI-drafted">AI</span>
      </div>
      <h3>{{ (locale === 'ar' && d.title_ar) || d.title }}</h3>
      <p v-if="d.description" class="desc">{{ d.description }}</p>
      <dl class="meta">
        <div><dt>{{ t('gov.owner') }}</dt><dd>{{ d.owner || '—' }}</dd></div>
        <div><dt>{{ t('gov.neededBy') }}</dt><dd class="tnum">{{ date(d.needed_by) }}</dd></div>
      </dl>
      <div v-if="d.review_status === 'draft'" class="alert info small">{{ t('gov.draft') }}</div>
      <div v-if="editable" class="row actions">
        <template v-if="d.review_status === 'draft'">
          <button class="btn btn-sm btn-primary" @click="emit('review', d, 'approve')">{{ t('gov.approve') }}</button>
          <button class="btn btn-sm" @click="emit('review', d, 'reject')">{{ t('gov.reject') }}</button>
        </template>
        <button class="btn btn-sm btn-ghost" @click="emit('edit', d)">{{ t('gov.edit') }}</button>
        <button class="btn btn-sm btn-ghost btn-danger" @click="emit('delete', d)">{{ t('gov.delete') }}</button>
      </div>
    </article>
    <p v-if="!items.length" class="muted">{{ t('gov.none') }}</p>
  </div>
</template>

<style scoped>
.dec { display: flex; flex-direction: column; gap: 10px; position: relative; overflow: hidden; }
.edge { position: absolute; inset-block: 0; inset-inline-start: 0; width: 4px; }
.desc { color: var(--text-2); font-size: 13px; line-height: 1.55; }
.meta { display: flex; gap: 22px; margin: 0; font-size: 12.5px; padding-top: 10px; border-top: 1px solid var(--border); }
.meta dt { color: var(--muted); font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }
.meta dd { margin: 0; font-weight: 550; }
.actions { margin-top: auto; padding-top: 4px; }
</style>
