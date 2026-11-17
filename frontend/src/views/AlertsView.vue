<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '@/api/client'
import type { AlertItem } from '@/api/types'
import { datetime } from '@/format'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'

const ui = useUi()
const auth = useAuth()
const alerts = ref<AlertItem[]>([])
const onlyOpen = ref(true)
async function load() {
  try {
    alerts.value = await api.get<AlertItem[]>(`/alerts?unacknowledged=${onlyOpen.value}`)
  } catch (e) {
    ui.error(e)
  }
}
async function ack(a: AlertItem) {
  await api.post(`/alerts/${a.id}/ack`)
  await load()
}
onMounted(load)
</script>

<template>
  <main id="main" class="page" tabindex="-1">
    <div class="page-head">
      <div><h1>Alerts</h1><p>Raised automatically when a new snapshot breaches a KPI threshold rule.</p></div>
      <div class="row"><label class="check"><input v-model="onlyOpen" type="checkbox" @change="load" /> Unacknowledged only</label>
        <RouterLink v-if="auth.isAdmin" class="btn" to="/admin/alert-rules">Manage rules</RouterLink></div>
    </div>
    <div class="stack">
      <article v-for="a in alerts" :key="a.id" class="card row">
        <span class="pill" :class="a.acknowledged ? 'neutral' : 'warn'">{{ a.acknowledged ? 'Acknowledged' : 'New' }}</span>
        <div style="flex: 1; min-width: 200px"><strong>{{ a.title }}</strong><p class="muted small">{{ a.message }}</p></div>
        <span class="muted small">{{ datetime(a.created_at) }} · {{ a.delivery_status }}</span>
        <RouterLink v-if="a.program_id" class="btn btn-sm" :to="`/p/${a.program_id}/overview`">Open</RouterLink>
        <button v-if="!a.acknowledged" class="btn btn-sm" @click="ack(a)">Acknowledge</button>
      </article>
      <p v-if="!alerts.length" class="empty">No alerts.</p>
    </div>
  </main>
</template>
