<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { Program } from '@/api/types'
import { useProgram } from '@/stores/program'
import { useUi } from '@/stores/ui'

const store = useProgram()
const ui = useUi()
const router = useRouter()
const saving = ref(false)
const form = reactive({ name: '', name_ar: '', client_name: '', client_name_ar: '', subtitle: '', location: '', description: '', reporting_cycle_days: 7 })
const th = reactive({ delay_pts: -5, critical_pts: -15, stalled_snapshots: 3, near_critical_days: 10, long_duration_days: 44 })
const stamp = ref(Date.now())

onMounted(() => {
  const p = store.program
  if (!p) return
  Object.assign(form, { name: p.name, name_ar: p.name_ar || '', client_name: p.client_name || '', client_name_ar: p.client_name_ar || '',
    subtitle: p.subtitle || '', location: p.location || '', description: p.description || '', reporting_cycle_days: p.reporting_cycle_days })
  Object.assign(th, p.thresholds || {})
})
async function save() {
  if (!store.program) return
  saving.value = true
  try {
    store.program = await api.patch<Program>(`/programs/${store.program.id}`, { ...form, thresholds: { ...th } })
    ui.toast('Program settings saved. Threshold changes apply on the next recompute (Snapshots → Reprocess, or re-approve mapping).')
    await store.loadDashboard(true)
  } catch (e) {
    ui.error(e)
  } finally {
    saving.value = false
  }
}
async function uploadLogo(which: 'client_logo' | 'vendor_logo', e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (!f || !store.program) return
  const fd = new FormData()
  fd.append('file', f)
  try {
    await api.upload(`/programs/${store.program.id}/logo/${which}`, fd)
    stamp.value = Date.now()
    ui.toast('Logo uploaded')
    await store.open(store.program.id)
    await store.loadDashboard(true)
  } catch (err) {
    ui.error(err)
  }
}
async function removeLogo(which: string) {
  if (!store.program) return
  await api.del(`/programs/${store.program.id}/logo/${which}`)
  await store.open(store.program.id)
  await store.loadDashboard(true)
}
async function archive() {
  if (!store.program || !confirm('Archive this program? It will be hidden from lists and the portfolio.')) return
  await api.patch(`/programs/${store.program.id}`, { is_archived: true })
  router.push('/programs')
}
async function destroy() {
  if (!store.program || prompt(`Type the program name to permanently delete it and all snapshots:`) !== store.program.name) return
  await api.del(`/programs/${store.program.id}`)
  store.reset()
  router.push('/programs')
}
</script>

<template>
  <div>
    <div class="page-head"><div><h1>Program settings</h1><p>Header text (EN/AR), reporting cycle, status thresholds and program-specific branding.</p></div></div>
    <form class="stack" @submit.prevent="save">
      <section class="card">
        <h2 class="mb">Identity</h2>
        <div class="form-grid">
          <label class="field">Program name *<input v-model="form.name" class="input" required /></label>
          <label class="field">Program name (Arabic)<input v-model="form.name_ar" class="input" dir="rtl" lang="ar" /></label>
          <label class="field">Client name<input v-model="form.client_name" class="input" /></label>
          <label class="field">Client name (Arabic)<input v-model="form.client_name_ar" class="input" dir="rtl" lang="ar" /></label>
          <label class="field">Subtitle<input v-model="form.subtitle" class="input" placeholder="e.g. Steering Committee Report" /></label>
          <label class="field">Location<input v-model="form.location" class="input" /></label>
          <label class="field">Reporting cycle (days)<input v-model.number="form.reporting_cycle_days" type="number" min="1" max="92" class="input" /><span class="hint">7 = weekly</span></label>
          <label class="field" style="grid-column: 1 / -1">Description<textarea v-model="form.description" class="input" /></label>
        </div>
      </section>
      <section class="card">
        <h2 class="mb">Status thresholds</h2>
        <p class="muted small mb">Milestone/track status from variance (actual − planned, in points): ≥ delay → On Track; ≥ critical → Delay; below → Critical Delay.</p>
        <div class="form-grid">
          <label class="field">Delay threshold (pts)<input v-model.number="th.delay_pts" type="number" step="0.5" class="input" /></label>
          <label class="field">Critical-delay threshold (pts)<input v-model.number="th.critical_pts" type="number" step="0.5" class="input" /></label>
          <label class="field">Stalled after n snapshots<input v-model.number="th.stalled_snapshots" type="number" min="2" class="input" /></label>
          <label class="field">Near-critical slack (days)<input v-model.number="th.near_critical_days" type="number" min="1" class="input" /></label>
          <label class="field">Long-duration task (days)<input v-model.number="th.long_duration_days" type="number" min="1" class="input" /></label>
        </div>
      </section>
      <div class="row"><span class="spacer" /><button class="btn btn-primary" :disabled="saving">Save settings</button></div>
    </form>
    <section class="card mt">
      <h2 class="mb">Program logos</h2>
      <p class="muted small mb">Overrides the organisation logos for this program's header and exports. PNG, JPEG, SVG or WebP, ≤ 2 MB.</p>
      <div class="grid grid-2">
        <div v-for="w in (['client_logo', 'vendor_logo'] as const)" :key="w" class="stack">
          <strong>{{ w === 'client_logo' ? 'Client logo' : 'Vendor logo' }}</strong>
          <img v-if="w === 'client_logo' ? store.program?.has_client_logo : store.program?.has_vendor_logo"
               :src="`/api/branding/programs/${store.program?.id}/${w}?t=${stamp}`" alt="" style="max-height: 60px; max-width: 220px; object-fit: contain" />
          <div class="row">
            <label class="btn btn-sm">Upload<input type="file" accept="image/png,image/jpeg,image/svg+xml,image/webp" class="sr-only" @change="uploadLogo(w, $event)" /></label>
            <button class="btn btn-sm btn-ghost" @click="removeLogo(w)">Remove</button>
          </div>
        </div>
      </div>
    </section>
    <section class="card mt">
      <h2 class="mb">Danger zone</h2>
      <div class="row"><button class="btn" @click="archive">Archive program</button><button class="btn btn-danger" @click="destroy">Delete program permanently</button></div>
    </section>
  </div>
</template>
