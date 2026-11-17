<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { DecisionItem } from '@/api/types'
import DecisionCards from '@/components/DecisionCards.vue'
import Modal from '@/components/Modal.vue'
import { useGovernance } from '@/composables/useGovernance'

const { t } = useI18n()
const g = useGovernance<DecisionItem>('decisions')
const form = reactive({ title: '', title_ar: '', description: '', kind: 'decision', priority: 'Medium', status: 'Pending', owner: '', needed_by: '' })
watch(g.editing, (e) => {
  if (!e) return
  Object.assign(form, { title: e.title || '', title_ar: e.title_ar || '', description: e.description || '', kind: e.kind || 'decision',
    priority: e.priority || 'Medium', status: e.status || 'Pending', owner: e.owner || '', needed_by: e.needed_by || '' })
})
const pending = computed(() => g.items.value.filter((d) => d.status === 'Pending'))
const closed = computed(() => g.items.value.filter((d) => d.status !== 'Pending'))
const drafts = computed(() => g.items.value.filter((d) => d.review_status === 'draft').length)
</script>

<template>
  <div>
    <div class="page-head">
      <div><h1>{{ t('nav.decisions') }}</h1><p>Steering-committee decisions and support requests. Persist across snapshots. <span v-if="drafts">{{ drafts }} AI drafts awaiting review.</span></p></div>
      <button v-if="g.canEdit.value" class="btn btn-primary" @click="g.editing.value = {}">+ {{ t('gov.add') }}</button>
    </div>
    <h2 class="mb">Pending ({{ pending.length }})</h2>
    <DecisionCards :items="pending" :editable="g.canEdit.value" @edit="(d) => (g.editing.value = d)" @review="g.review" @delete="g.remove" />
    <h2 class="mb mt">Decided ({{ closed.length }})</h2>
    <DecisionCards :items="closed" :editable="g.canEdit.value" @edit="(d) => (g.editing.value = d)" @review="g.review" @delete="g.remove" />

    <Modal v-if="g.editing.value" :title="g.editing.value.id ? t('gov.edit') : t('gov.add')" @close="g.editing.value = null">
      <form id="dec-form" class="form-grid" @submit.prevent="g.save({ ...form })">
        <label class="field" style="grid-column: 1 / -1">{{ t('gov.title') }} *<input v-model="form.title" class="input" required maxlength="300" /></label>
        <label class="field" style="grid-column: 1 / -1">Title (Arabic)<input v-model="form.title_ar" class="input" dir="rtl" lang="ar" /></label>
        <label class="field" style="grid-column: 1 / -1">{{ t('gov.description') }}<textarea v-model="form.description" class="input" /></label>
        <label class="field">Type<select v-model="form.kind" class="input"><option value="decision">Decision</option><option value="support">Support request</option></select></label>
        <label class="field">{{ t('gov.priority') }}<select v-model="form.priority" class="input"><option>High</option><option>Medium</option><option>Low</option></select></label>
        <label class="field">{{ t('gov.status') }}<select v-model="form.status" class="input"><option>Pending</option><option>Approved</option><option>Rejected</option></select></label>
        <label class="field">{{ t('gov.owner') }}<input v-model="form.owner" class="input" /></label>
        <label class="field">{{ t('gov.neededBy') }}<input v-model="form.needed_by" type="date" class="input" /></label>
      </form>
      <template #footer>
        <button class="btn" @click="g.editing.value = null">{{ t('gov.cancel') }}</button>
        <button class="btn btn-primary" type="submit" form="dec-form" :disabled="g.saving.value">{{ t('gov.save') }}</button>
      </template>
    </Modal>
  </div>
</template>
