<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { Program } from '@/api/types'
import Icon from '@/components/Icon.vue'
import Modal from '@/components/Modal.vue'
import { date } from '@/format'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'

const { t, locale } = useI18n()
const auth = useAuth()
const ui = useUi()
const router = useRouter()
const programs = ref<Program[]>([])
const loading = ref(true)
const creating = ref(false)
const showArchived = ref(false)
const form = reactive({ name: '', name_ar: '', client_name: '', client_name_ar: '', subtitle: '', location: '', reporting_cycle_days: 7 })

async function load() {
  loading.value = true
  try {
    programs.value = await api.get<Program[]>(`/programs?include_archived=${showArchived.value}`)
  } catch (e) {
    ui.error(e)
  } finally {
    loading.value = false
  }
}
async function create() {
  try {
    const p = await api.post<Program>('/programs', { ...form })
    creating.value = false
    router.push(`/p/${p.id}/snapshots`)
  } catch (e) {
    ui.error(e)
  }
}
function go(p: Program) {
  router.push(p.latest_snapshot ? `/p/${p.id}/overview` : `/p/${p.id}/snapshots`)
}
onMounted(load)
</script>

<template>
  <main id="main" class="page" tabindex="-1">
    <div class="page-head">
      <div><h1>{{ t('nav.programs') }}</h1><p>{{ auth.user?.tenant_name }}</p></div>
      <div class="row">
        <label class="check small"><input v-model="showArchived" type="checkbox" @change="load" /> Show archived</label>
        <button v-if="auth.isAdmin" class="btn btn-primary" @click="creating = true"><Icon name="plus" />New program</button>
      </div>
    </div>
    <div v-if="loading" class="empty"><span class="spinner" /></div>
    <div v-else-if="!programs.length" class="card empty">
      <h3>No programs yet</h3>
      <p v-if="auth.isAdmin">Create a program, then upload its first MS Project file.</p>
      <p v-else>Ask an administrator to create a program.</p>
    </div>
    <div v-else class="grid grid-3">
      <button v-for="p in programs" :key="p.id" class="card prog linklike" @click="go(p)">
        <div class="row"><span class="section-title">{{ (locale === 'ar' && p.client_name_ar) || p.client_name || '—' }}</span><span class="spacer" />
          <span v-if="p.is_archived" class="pill neutral plain">Archived</span>
          <span v-else-if="p.mapping_status === 'proposed'" class="pill warn plain">Mapping pending</span>
          <span v-else-if="p.latest_snapshot" class="pill ok plain">Live</span>
          <span v-else class="pill neutral plain">No data</span></div>
        <h2>{{ (locale === 'ar' && p.name_ar) || p.name }}</h2>
        <p class="muted small">{{ p.subtitle }}</p>
        <div class="row small muted prog-foot">
          <span><Icon name="layers" :size="14" />{{ p.track_count }} tracks</span>
          <span><Icon name="file" :size="14" />{{ Object.values(p.snapshot_counts).reduce((a, b) => a + b, 0) }} snapshots</span>
          <span><Icon name="calendar" :size="14" />{{ p.latest_snapshot ? `as of ${date(p.latest_snapshot.as_of)}` : 'awaiting first upload' }}</span>
          <span class="spacer" />
          <Icon name="arrow" :size="16" class="arrow" />
        </div>
      </button>
    </div>
    <Modal v-if="creating" title="New program" @close="creating = false">
      <form id="np" class="form-grid" @submit.prevent="create">
        <label class="field">Program name *<input v-model="form.name" class="input" required /></label>
        <label class="field">Program name (Arabic)<input v-model="form.name_ar" class="input" dir="rtl" lang="ar" /></label>
        <label class="field">Client name<input v-model="form.client_name" class="input" /></label>
        <label class="field">Client name (Arabic)<input v-model="form.client_name_ar" class="input" dir="rtl" lang="ar" /></label>
        <label class="field">Subtitle<input v-model="form.subtitle" class="input" /></label>
        <label class="field">Location<input v-model="form.location" class="input" /></label>
        <label class="field">Reporting cycle (days)<input v-model.number="form.reporting_cycle_days" type="number" min="1" max="92" class="input" /></label>
      </form>
      <template #footer><button class="btn" @click="creating = false">Cancel</button><button class="btn btn-primary" form="np">Create</button></template>
    </Modal>
  </main>
</template>

<style scoped>
.prog { text-align: start; display: flex; flex-direction: column; gap: 10px; cursor: pointer; min-height: 168px; position: relative; overflow: hidden; }
.prog::before { content: ''; position: absolute; inset-inline: 0; top: 0; height: 3px; background: linear-gradient(90deg, var(--brand-2), color-mix(in srgb, var(--brand-2) 40%, #06b6d4)); opacity: 0; transition: opacity 0.2s var(--ease); }
.prog:hover::before { opacity: 1; }
.prog h2 { font-size: 17px; }
.prog-foot { margin-top: auto; padding-top: 12px; border-top: 1px solid var(--border); gap: 14px; }
.prog-foot span { display: inline-flex; align-items: center; gap: 5px; }
.prog-foot .icon { color: var(--muted); }
.prog .arrow { color: var(--muted); transition: transform 0.2s var(--ease), color 0.2s; }
.prog:hover .arrow { color: var(--brand-2); transform: translateX(3px); }
:root[dir='rtl'] .prog .arrow { transform: scaleX(-1); }
:root[dir='rtl'] .prog:hover .arrow { transform: scaleX(-1) translateX(3px); }
</style>
