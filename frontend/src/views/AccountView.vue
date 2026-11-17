<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, setToken } from '@/api/client'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'

const { t } = useI18n()
const auth = useAuth()
const ui = useUi()
const cur = ref('')
const next = ref('')
const confirm2 = ref('')
async function change() {
  if (next.value !== confirm2.value) return ui.toast('New passwords do not match', 'bad')
  try {
    const r = await api.post<{ access_token: string }>('/auth/change-password', { current_password: cur.value, new_password: next.value })
    setToken(r.access_token)
    cur.value = next.value = confirm2.value = ''
    ui.toast('Password changed. Other sessions were signed out.')
  } catch (e) {
    ui.error(e)
  }
}
</script>

<template>
  <main id="main" class="page" tabindex="-1">
    <div class="page-head"><div><h1>{{ t('nav.account') }}</h1><p>{{ auth.user?.email }} · {{ t(`roles.${auth.user?.role}`) }} · {{ auth.user?.tenant_name }}</p></div></div>
    <section class="card" style="max-width: 520px">
      <h2 class="mb">Change password</h2>
      <p v-if="auth.user?.sso" class="muted">Your account signs in through single sign-on; manage your password with your identity provider.</p>
      <form v-else class="stack" @submit.prevent="change">
        <label class="field">Current password<input v-model="cur" type="password" class="input" autocomplete="current-password" required /></label>
        <label class="field">New password<input v-model="next" type="password" class="input" autocomplete="new-password" minlength="10" required /><span class="hint">At least 10 characters with a letter and a digit.</span></label>
        <label class="field">Confirm new password<input v-model="confirm2" type="password" class="input" autocomplete="new-password" required /></label>
        <button class="btn btn-primary">Change password</button>
      </form>
    </section>
  </main>
</template>
