<script setup lang="ts">
// Tenant branding (v2) and per-tenant AI provider switch: off | self-hosted Ollama | Ollama Cloud.
import { onMounted, reactive, ref } from 'vue'
import { api } from '@/api/client'
import type { Tenant } from '@/api/types'
import { useUi } from '@/stores/ui'

const ui = useUi()
const tenant = ref<Tenant | null>(null)
const form = reactive({ name: '', name_ar: '', primary_color: '', support_email: '', contact_url: '', location: '', ai_mode: 'off', ai_model: '', ai_redact: true })
const health = ref<{ ok: boolean; provider: string; models?: string[]; error?: string } | null>(null)
const stamp = ref(Date.now())

async function load() {
  const tn = await api.get<Tenant>('/tenant')
  tenant.value = tn
  Object.assign(form, { name: tn.name, name_ar: tn.name_ar || '', primary_color: tn.branding.primary_color || '', support_email: tn.branding.support_email || '',
    contact_url: tn.branding.contact_url || '', location: tn.branding.location || '', ai_mode: tn.ai_mode, ai_model: tn.ai_model, ai_redact: tn.ai_redact })
}
async function save() {
  try {
    tenant.value = await api.patch<Tenant>('/tenant', { name: form.name, name_ar: form.name_ar || null,
      branding: { primary_color: form.primary_color, support_email: form.support_email, contact_url: form.contact_url, location: form.location },
      ai_mode: form.ai_mode, ai_model: form.ai_model, ai_redact: form.ai_redact })
    ui.toast('Organisation settings saved')
  } catch (e) {
    ui.error(e)
  }
}
async function testAi() {
  health.value = null
  try {
    health.value = await api.get('/tenant/ai-health')
  } catch (e) {
    ui.error(e)
  }
}
async function logo(which: string, e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (!f) return
  const fd = new FormData()
  fd.append('file', f)
  try {
    tenant.value = await api.upload<Tenant>(`/tenant/logo/${which}`, fd)
    stamp.value = Date.now()
  } catch (err) {
    ui.error(err)
  }
}
onMounted(load)
</script>

<template>
  <main id="main" class="page" tabindex="-1">
    <div class="page-head"><div><h1>Organisation</h1><p>Branding shown in every program header, footer and export; AI provider for this tenant.</p></div></div>
    <form v-if="tenant" class="stack" @submit.prevent="save">
      <section class="card">
        <h2 class="mb">Branding</h2>
        <div class="form-grid">
          <label class="field">Organisation name<input v-model="form.name" class="input" required /></label>
          <label class="field">Organisation name (Arabic)<input v-model="form.name_ar" class="input" dir="rtl" lang="ar" /></label>
          <label class="field">Primary colour<input v-model="form.primary_color" class="input" placeholder="#1E3A8A" pattern="#[0-9a-fA-F]{6}" /></label>
          <label class="field">Support email (footer)<input v-model="form.support_email" class="input" type="email" /></label>
          <label class="field">Contact URL (footer)<input v-model="form.contact_url" class="input" type="url" /></label>
          <label class="field">Default location<input v-model="form.location" class="input" /></label>
        </div>
        <div class="grid grid-2 mt">
          <div v-for="w in ['client_logo', 'vendor_logo']" :key="w" class="stack">
            <strong>{{ w === 'client_logo' ? 'Client logo' : 'Vendor logo' }}</strong>
            <img v-if="w === 'client_logo' ? tenant.has_client_logo : tenant.has_vendor_logo" :src="`/api/branding/tenants/${tenant.id}/${w}?t=${stamp}`" alt="" style="max-height: 60px; max-width: 220px; object-fit: contain" />
            <label class="btn btn-sm" style="width: fit-content">Upload<input type="file" class="sr-only" accept="image/png,image/jpeg,image/svg+xml,image/webp" @change="logo(w, $event)" /></label>
          </div>
        </div>
      </section>
      <section class="card">
        <h2 class="mb">AI provider</h2>
        <p class="muted small mb">One provider interface, switchable per tenant. Self-hosted Ollama keeps data inside your network (default for government/restricted data). Cloud calls are redacted (names, emails, phone/ID numbers) and every call is logged. With AI off the application remains fully functional.</p>
        <div class="form-grid">
          <label class="field">Mode<select v-model="form.ai_mode" class="input">
            <option value="off">Off</option><option value="self_hosted">Self-hosted Ollama</option>
            <option value="cloud" :disabled="!tenant.cloud_available">Ollama Cloud{{ tenant.cloud_available ? '' : ' (API key not configured)' }}</option></select></label>
          <label class="field">Model<input v-model="form.ai_model" class="input" placeholder="deepseek-v4.1-flash:cloud" /></label>
          <label class="check"><input v-model="form.ai_redact" type="checkbox" /> Redact sensitive data before cloud calls</label>
        </div>
        <div class="row mt"><button type="button" class="btn btn-sm" @click="testAi">Test connection</button>
          <span v-if="health" class="pill" :class="health.ok ? 'ok' : 'bad'">{{ health.ok ? `Connected (${health.models?.length || 0} models)` : (health.error || 'Not reachable') }}</span></div>
        <p v-if="health?.models?.length" class="muted small mt">Available: {{ health.models.join(', ') }}</p>
      </section>
      <div class="row"><span class="spacer" /><button class="btn btn-primary">Save</button></div>
    </form>
  </main>
</template>
