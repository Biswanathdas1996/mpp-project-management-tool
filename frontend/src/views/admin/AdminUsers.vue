<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/client'
import type { Role, User } from '@/api/types'
import Modal from '@/components/Modal.vue'
import { datetime } from '@/format'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'

const { t } = useI18n()
const ui = useUi()
const auth = useAuth()
const users = ref<User[]>([])
const editing = ref<Partial<User> | null>(null)
const form = reactive({ email: '', full_name: '', role: 'super_viewer' as Role, password: '', is_active: true })

async function load() {
  users.value = await api.get<User[]>('/users')
}
function open(u: Partial<User>) {
  editing.value = u
  Object.assign(form, { email: u.email || '', full_name: u.full_name || '', role: u.role || 'super_viewer', password: '', is_active: u.is_active ?? true })
}
async function save() {
  try {
    if (editing.value?.id) {
      await api.patch(`/users/${editing.value.id}`, { full_name: form.full_name, role: form.role, is_active: form.is_active, ...(form.password ? { password: form.password } : {}) })
    } else {
      await api.post('/users', { email: form.email, full_name: form.full_name, role: form.role, ...(form.password ? { password: form.password } : {}) })
    }
    editing.value = null
    ui.toast('Saved')
    await load()
  } catch (e) {
    ui.error(e)
  }
}
async function remove(u: User) {
  if (!confirm(`Delete ${u.email}?`)) return
  try {
    await api.del(`/users/${u.id}`)
    await load()
  } catch (e) {
    ui.error(e)
  }
}
onMounted(load)
</script>

<template>
  <main id="main" class="page" tabindex="-1">
    <div class="page-head"><div><h1>{{ t('nav.users') }}</h1><p>Admin: full control incl. mapping approval · PMO Editor: uploads and governance · Super Viewer: read-only and exports.</p></div>
      <button class="btn btn-primary" @click="open({})">+ Add user</button></div>
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>Email</th><th>Name</th><th>Role</th><th>Sign-in</th><th>Status</th><th>Last login</th><th></th></tr></thead>
        <tbody>
          <tr v-for="u in users" :key="u.id">
            <td>{{ u.email }}</td><td>{{ u.full_name }}</td><td>{{ t(`roles.${u.role}`) }}<span v-if="u.is_platform_admin" class="pill info plain" style="margin-inline-start: 6px">platform</span></td>
            <td>{{ u.sso ? 'SSO' : 'Password' }}</td><td><span class="pill" :class="u.is_active ? 'ok' : 'neutral'">{{ u.is_active ? 'Active' : 'Disabled' }}</span></td>
            <td class="small">{{ datetime(u.last_login_at) }}</td>
            <td><div class="row" style="gap: 4px"><button class="btn btn-sm btn-ghost" @click="open(u)">Edit</button><button v-if="u.id !== auth.user?.id" class="btn btn-sm btn-ghost btn-danger" @click="remove(u)">Delete</button></div></td>
          </tr>
        </tbody>
      </table>
    </div>
    <Modal v-if="editing" :title="editing.id ? `Edit ${editing.email}` : 'Add user'" @close="editing = null">
      <form id="uf" class="form-grid" @submit.prevent="save">
        <label class="field">Email<input v-model="form.email" class="input" type="email" :disabled="!!editing.id" required /></label>
        <label class="field">Full name<input v-model="form.full_name" class="input" /></label>
        <label class="field">Role<select v-model="form.role" class="input"><option value="admin">{{ t('roles.admin') }}</option><option value="pmo_editor">{{ t('roles.pmo_editor') }}</option><option value="super_viewer">{{ t('roles.super_viewer') }}</option></select></label>
        <label class="field">{{ editing.id ? 'Reset password' : 'Password' }}<input v-model="form.password" class="input" type="password" autocomplete="new-password" /><span class="hint">Leave blank for SSO-only accounts{{ editing.id ? ' / to keep current' : '' }}</span></label>
        <label v-if="editing.id" class="check"><input v-model="form.is_active" type="checkbox" /> Active</label>
      </form>
      <template #footer><button class="btn" @click="editing = null">Cancel</button><button class="btn btn-primary" form="uf">Save</button></template>
    </Modal>
  </main>
</template>
