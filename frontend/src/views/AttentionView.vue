<script setup lang="ts">
import { reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/client'
import type { AttentionRow } from '@/api/types'
import AttentionList from '@/components/AttentionList.vue'
import Modal from '@/components/Modal.vue'
import { useDash } from '@/composables/useDash'
import { useGovernance } from '@/composables/useGovernance'
import { useUi } from '@/stores/ui'

const { t } = useI18n()
const ui = useUi()
const { d, store, drillUids } = useDash()
const g = useGovernance<AttentionRow>('attention')
const form = reactive({ title: '', description: '', severity: 'Medium', status: 'Open', owner: '', due_date: '', category: '' })
watch(g.editing, (e) => {
  if (!e) return
  Object.assign(form, { title: e.title || '', description: e.description || '', severity: e.severity || 'Medium', status: e.status || 'Open',
    owner: e.owner || '', due_date: e.due_date || '', category: e.category || '' })
})
async function resolve(a: AttentionRow) {
  try {
    await api.put(`/programs/${store.program!.id}/attention/${a.id}`, { ...a, status: 'Resolved' })
    await g.load()
    await store.loadDashboard(true)
  } catch (e) {
    ui.error(e)
  }
}
</script>

<template>
  <div>
    <div class="page-head">
      <div><h1>{{ t('nav.attention') }}</h1><p>Overdue or at-risk items needing action — computed from the plan and governance data, plus items raised by the PMO.</p></div>
      <button v-if="g.canEdit.value" class="btn btn-primary" @click="g.editing.value = {}">+ {{ t('gov.add') }}</button>
    </div>
    <section class="mb">
      <h2 class="mb">Computed from the plan ({{ d?.attention.derived.length || 0 }})</h2>
      <AttentionList :items="d?.attention.derived || []" @drill="(a) => drillUids(a.related_task_uids, a.title)" />
    </section>
    <section class="mt">
      <h2 class="mb">Raised by PMO / AI ({{ g.items.value.length }})</h2>
      <AttentionList :items="g.items.value" :editable="g.canEdit.value" @drill="(a) => drillUids(a.related_task_uids, a.title)"
                     @edit="(a) => (g.editing.value = a)" @review="g.review" @resolve="resolve" @delete="g.remove" />
    </section>

    <Modal v-if="g.editing.value" :title="g.editing.value.id ? t('gov.edit') : t('gov.add')" @close="g.editing.value = null">
      <form id="att-form" class="form-grid" @submit.prevent="g.save({ ...form })">
        <label class="field" style="grid-column: 1 / -1">{{ t('gov.title') }} *<input v-model="form.title" class="input" required /></label>
        <label class="field" style="grid-column: 1 / -1">{{ t('gov.description') }}<textarea v-model="form.description" class="input" /></label>
        <label class="field">{{ t('gov.severity') }}<select v-model="form.severity" class="input"><option>Critical</option><option>High</option><option>Medium</option><option>Low</option></select></label>
        <label class="field">{{ t('gov.status') }}<select v-model="form.status" class="input"><option>Open</option><option>Resolved</option></select></label>
        <label class="field">{{ t('gov.owner') }}<input v-model="form.owner" class="input" /></label>
        <label class="field">{{ t('gov.dueDate') }}<input v-model="form.due_date" type="date" class="input" /></label>
      </form>
      <template #footer>
        <button class="btn" @click="g.editing.value = null">{{ t('gov.cancel') }}</button>
        <button class="btn btn-primary" type="submit" form="att-form" :disabled="g.saving.value">{{ t('gov.save') }}</button>
      </template>
    </Modal>
  </div>
</template>
