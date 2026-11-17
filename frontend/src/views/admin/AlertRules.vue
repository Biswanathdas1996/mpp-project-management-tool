<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api } from '@/api/client'
import type { AlertRule, CatalogueEntry, Program } from '@/api/types'
import Modal from '@/components/Modal.vue'
import { useUi } from '@/stores/ui'

const ui = useUi()
const rules = ref<AlertRule[]>([])
const catalogue = ref<CatalogueEntry[]>([])
const programs = ref<Program[]>([])
const editing = ref<Partial<AlertRule> | null>(null)
const form = reactive({ name: '', program_id: '' as string | number, kpi_code: 'schedule_variance_pts', operator: '<', threshold: -10, channel: 'in_app', target: '', enabled: true })

async function load() {
  ;[rules.value, catalogue.value, programs.value] = await Promise.all([
    api.get<AlertRule[]>('/alert-rules'), api.get<CatalogueEntry[]>('/kpi-catalogue'), api.get<Program[]>('/programs')])
}
function open(r: Partial<AlertRule>) {
  editing.value = r
  Object.assign(form, { name: r.name || '', program_id: r.program_id ?? '', kpi_code: r.kpi_code || 'schedule_variance_pts', operator: r.operator || '<',
    threshold: r.threshold ?? -10, channel: r.channel || 'in_app', target: r.target || '', enabled: r.enabled ?? true })
}
async function save() {
  const body = { ...form, program_id: form.program_id === '' ? null : Number(form.program_id), target: form.target || null }
  try {
    if (editing.value?.id) await api.put(`/alert-rules/${editing.value.id}`, body)
    else await api.post('/alert-rules', body)
    editing.value = null
    await load()
  } catch (e) {
    ui.error(e)
  }
}
async function remove(r: AlertRule) {
  if (!confirm(`Delete rule “${r.name}”?`)) return
  await api.del(`/alert-rules/${r.id}`)
  await load()
}
onMounted(load)
</script>

<template>
  <main id="main" class="page" tabindex="-1">
    <div class="page-head"><div><h1>Alert rules</h1><p>Evaluated after every processed snapshot. Deliver in-app, by email (SMTP) or to an HTTPS webhook (e.g. Teams/Slack).</p></div>
      <button class="btn btn-primary" @click="open({})">+ Add rule</button></div>
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>Name</th><th>Program</th><th>Condition</th><th>Channel</th><th>Enabled</th><th></th></tr></thead>
        <tbody>
          <tr v-for="r in rules" :key="r.id">
            <td><strong>{{ r.name }}</strong></td><td>{{ programs.find((p) => p.id === r.program_id)?.name || 'All programs' }}</td>
            <td>{{ r.kpi_name }} {{ r.operator }} {{ r.threshold }}</td><td>{{ r.channel }}<span v-if="r.target" class="muted small"> → {{ r.target }}</span></td>
            <td>{{ r.enabled ? 'Yes' : 'No' }}</td>
            <td><button class="btn btn-sm btn-ghost" @click="open(r)">Edit</button><button class="btn btn-sm btn-ghost btn-danger" @click="remove(r)">Delete</button></td>
          </tr>
          <tr v-if="!rules.length"><td colspan="6" class="empty">No rules.</td></tr>
        </tbody>
      </table>
    </div>
    <Modal v-if="editing" :title="editing.id ? 'Edit rule' : 'Add rule'" @close="editing = null">
      <form id="ar" class="form-grid" @submit.prevent="save">
        <label class="field" style="grid-column: 1 / -1">Name<input v-model="form.name" class="input" required /></label>
        <label class="field">Program<select v-model="form.program_id" class="input"><option value="">All programs</option><option v-for="p in programs" :key="p.id" :value="p.id">{{ p.name }}</option></select></label>
        <label class="field">KPI<select v-model="form.kpi_code" class="input"><option v-for="k in catalogue" :key="k.code" :value="k.code">{{ k.name }}</option></select></label>
        <label class="field">Operator<select v-model="form.operator" class="input"><option v-for="o in ['<', '<=', '>', '>=', '==', '!=']" :key="o">{{ o }}</option></select></label>
        <label class="field">Threshold<input v-model.number="form.threshold" type="number" step="any" class="input" required /></label>
        <label class="field">Channel<select v-model="form.channel" class="input"><option value="in_app">In-app</option><option value="email">Email</option><option value="webhook">Webhook</option></select></label>
        <label v-if="form.channel !== 'in_app'" class="field">{{ form.channel === 'email' ? 'Email address(es)' : 'Webhook URL (https)' }}<input v-model="form.target" class="input" required /></label>
        <label class="check"><input v-model="form.enabled" type="checkbox" /> Enabled</label>
      </form>
      <template #footer><button class="btn" @click="editing = null">Cancel</button><button class="btn btn-primary" form="ar">Save</button></template>
    </Modal>
  </main>
</template>
