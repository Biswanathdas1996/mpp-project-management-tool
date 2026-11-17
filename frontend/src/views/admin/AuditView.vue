<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, qs } from '@/api/client'
import type { AuditItem } from '@/api/types'
import { datetime } from '@/format'

const items = ref<AuditItem[]>([])
const total = ref(0)
const action = ref('')
const email = ref('')
const offset = ref(0)
const LIMIT = 100
async function load() {
  const r = await api.get<{ total: number; items: AuditItem[] }>(`/audit${qs({ action: action.value, user_email: email.value, limit: LIMIT, offset: offset.value })}`)
  items.value = r.items
  total.value = r.total
}
function search() {
  offset.value = 0
  load()
}
onMounted(load)
</script>

<template>
  <main id="main" class="page" tabindex="-1">
    <div class="page-head"><div><h1>Audit log</h1><p>{{ total }} events · every login, upload, mapping approval, governance change, export and AI call is recorded.</p></div></div>
    <form class="row mb" @submit.prevent="search">
      <input v-model="action" class="input" style="max-width: 220px" placeholder="Action prefix (e.g. snapshot.)" aria-label="Action" />
      <input v-model="email" class="input" style="max-width: 220px" placeholder="User email" aria-label="User email" />
      <button class="btn">Filter</button>
    </form>
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>When</th><th>User</th><th>Action</th><th>Entity</th><th>Program</th><th>Details</th><th>IP</th></tr></thead>
        <tbody>
          <tr v-for="a in items" :key="a.id">
            <td class="small" style="white-space: nowrap">{{ datetime(a.created_at) }}</td><td class="small">{{ a.user_email || 'system' }}</td>
            <td><code>{{ a.action }}</code></td><td class="small">{{ a.entity_type }} {{ a.entity_id }}</td><td class="small">{{ a.program_id ?? '' }}</td>
            <td class="small mono" style="max-width: 420px; word-break: break-word">{{ Object.keys(a.details || {}).length ? JSON.stringify(a.details) : '' }}</td>
            <td class="small">{{ a.ip }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="row mt"><button class="btn btn-sm" :disabled="offset === 0" @click="offset -= LIMIT; load()">Previous</button>
      <span class="small muted">{{ offset + 1 }}–{{ Math.min(offset + LIMIT, total) }} of {{ total }}</span>
      <button class="btn btn-sm" :disabled="offset + LIMIT >= total" @click="offset += LIMIT; load()">Next</button></div>
  </main>
</template>
