<script setup lang="ts">
// Multi-tenant administration (v2): platform admins create tenants with their first admin.
import { onMounted, reactive, ref } from 'vue'
import { api } from '@/api/client'
import type { Tenant } from '@/api/types'
import Modal from '@/components/Modal.vue'
import { useUi } from '@/stores/ui'

const ui = useUi()
const tenants = ref<Tenant[]>([])
const creating = ref(false)
const form = reactive({ name: '', name_ar: '', slug: '', admin_email: '', admin_name: '', admin_password: '' })
async function load() {
  tenants.value = await api.get<Tenant[]>('/platform/tenants')
}
async function create() {
  try {
    await api.post('/platform/tenants', { ...form })
    creating.value = false
    ui.toast('Tenant created')
    await load()
  } catch (e) {
    ui.error(e)
  }
}
async function toggle(t: Tenant) {
  try {
    await api.patch(`/platform/tenants/${t.id}`, { is_active: !t.is_active })
    await load()
  } catch (e) {
    ui.error(e)
  }
}
onMounted(load)
</script>

<template>
  <main id="main" class="page" tabindex="-1">
    <div class="page-head"><div><h1>Tenants</h1><p>Each tenant is fully isolated: users, programs, branding and AI settings.</p></div>
      <button class="btn btn-primary" @click="creating = true">+ New tenant</button></div>
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>Name</th><th>Slug</th><th>AI</th><th>Status</th><th></th></tr></thead>
        <tbody>
          <tr v-for="t in tenants" :key="t.id">
            <td><strong>{{ t.name }}</strong> <span v-if="t.name_ar" class="muted" dir="rtl">{{ t.name_ar }}</span></td><td><code>{{ t.slug }}</code></td><td>{{ t.ai_mode }}</td>
            <td><span class="pill" :class="t.is_active ? 'ok' : 'neutral'">{{ t.is_active ? 'Active' : 'Disabled' }}</span></td>
            <td><button class="btn btn-sm" @click="toggle(t)">{{ t.is_active ? 'Disable' : 'Enable' }}</button></td>
          </tr>
        </tbody>
      </table>
    </div>
    <Modal v-if="creating" title="New tenant" @close="creating = false">
      <form id="tf" class="form-grid" @submit.prevent="create">
        <label class="field">Name<input v-model="form.name" class="input" required /></label>
        <label class="field">Name (Arabic)<input v-model="form.name_ar" class="input" dir="rtl" /></label>
        <label class="field">Slug<input v-model="form.slug" class="input" pattern="[a-z0-9-]+" required /><span class="hint">lowercase letters, digits, dashes</span></label>
        <label class="field">First admin email<input v-model="form.admin_email" class="input" type="email" required /></label>
        <label class="field">First admin name<input v-model="form.admin_name" class="input" /></label>
        <label class="field">First admin password<input v-model="form.admin_password" class="input" type="password" minlength="10" required /></label>
      </form>
      <template #footer><button class="btn" @click="creating = false">Cancel</button><button class="btn btn-primary" form="tf">Create</button></template>
    </Modal>
  </main>
</template>
