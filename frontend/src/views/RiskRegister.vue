<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { RiskItem } from '@/api/types'
import Modal from '@/components/Modal.vue'
import RiskList from '@/components/RiskList.vue'
import { useGovernance } from '@/composables/useGovernance'

const { t } = useI18n()
const g = useGovernance<RiskItem>('risks')
const filter = ref<'open' | 'all'>('open')
const form = reactive({ title: '', title_ar: '', description: '', severity: 'Medium', likelihood: '', impact: '', mitigation: '', owner: '', due_date: '', status: 'Open' })
watch(g.editing, (e) => {
  if (!e) return
  Object.assign(form, { title: e.title || '', title_ar: e.title_ar || '', description: e.description || '', severity: e.severity || 'Medium',
    likelihood: e.likelihood || '', impact: e.impact || '', mitigation: e.mitigation || '', owner: e.owner || '', due_date: e.due_date || '', status: e.status || 'Open' })
})
const ORDER: Record<string, number> = { Critical: 0, High: 1, Medium: 2, Low: 3 }
const rows = computed(() => g.items.value.filter((r) => filter.value === 'all' || r.status !== 'Closed')
  .sort((a, b) => ORDER[a.severity] - ORDER[b.severity]))
const counts = computed(() => {
  const c: Record<string, number> = { Critical: 0, High: 0, Medium: 0, Low: 0 }
  for (const r of g.items.value) if (r.status !== 'Closed' && r.review_status === 'approved') c[r.severity]++
  return c
})
</script>

<template>
  <div>
    <div class="page-head">
      <div><h1>{{ t('nav.risks') }}</h1>
        <p class="row small"><span v-for="(n, s) in counts" :key="s">{{ s }}: <strong>{{ n }}</strong></span></p>
      </div>
      <div class="row">
        <select v-model="filter" class="input" style="width: 150px" aria-label="Filter risks"><option value="open">Open risks</option><option value="all">All risks</option></select>
        <button v-if="g.canEdit.value" class="btn btn-primary" @click="g.editing.value = {}">+ {{ t('gov.add') }}</button>
      </div>
    </div>
    <RiskList :items="rows" :editable="g.canEdit.value" @edit="(r) => (g.editing.value = r)" @review="g.review" @delete="g.remove" />

    <Modal v-if="g.editing.value" :title="g.editing.value.id ? t('gov.edit') : t('gov.add')" @close="g.editing.value = null">
      <form id="risk-form" class="form-grid" @submit.prevent="g.save({ ...form })">
        <label class="field" style="grid-column: 1 / -1">{{ t('gov.title') }} *<input v-model="form.title" class="input" required maxlength="300" /></label>
        <label class="field" style="grid-column: 1 / -1">Title (Arabic)<input v-model="form.title_ar" class="input" dir="rtl" lang="ar" /></label>
        <label class="field" style="grid-column: 1 / -1">{{ t('gov.description') }}<textarea v-model="form.description" class="input" /></label>
        <label class="field" style="grid-column: 1 / -1">{{ t('gov.mitigation') }}<textarea v-model="form.mitigation" class="input" /></label>
        <label class="field">{{ t('gov.severity') }}<select v-model="form.severity" class="input"><option>Critical</option><option>High</option><option>Medium</option><option>Low</option></select></label>
        <label class="field">Likelihood<select v-model="form.likelihood" class="input"><option value="">—</option><option>Almost certain</option><option>Likely</option><option>Possible</option><option>Unlikely</option><option>Rare</option></select></label>
        <label class="field">Impact<select v-model="form.impact" class="input"><option value="">—</option><option>Severe</option><option>Major</option><option>Moderate</option><option>Minor</option></select></label>
        <label class="field">{{ t('gov.status') }}<select v-model="form.status" class="input"><option>Open</option><option>Mitigating</option><option>Closed</option></select></label>
        <label class="field">{{ t('gov.actionOwner') }}<input v-model="form.owner" class="input" /></label>
        <label class="field">{{ t('gov.dueDate') }}<input v-model="form.due_date" type="date" class="input" /></label>
      </form>
      <template #footer>
        <button class="btn" @click="g.editing.value = null">{{ t('gov.cancel') }}</button>
        <button class="btn btn-primary" type="submit" form="risk-form" :disabled="g.saving.value">{{ t('gov.save') }}</button>
      </template>
    </Modal>
  </div>
</template>
