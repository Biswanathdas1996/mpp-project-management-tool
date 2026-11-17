<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { datetime } from '@/format'

interface Log { id: number; kind: string; provider: string; model: string; status: string; redacted: boolean; redaction_count: number; prompt_chars: number; response_chars: number; prompt_tokens: number | null; completion_tokens: number | null; latency_ms: number; error: string | null; program_id: number | null; created_at: string }
const logs = ref<Log[]>([])
onMounted(async () => (logs.value = await api.get<Log[]>('/ai/logs?limit=500')))
const stats = computed(() => {
  const ok = logs.value.filter((l) => l.status === 'ok')
  return { calls: logs.value.length, ok: ok.length, cached: logs.value.filter((l) => l.status === 'cached').length,
    avgMs: ok.length ? Math.round(ok.reduce((a, b) => a + b.latency_ms, 0) / ok.length) : 0,
    tokens: ok.reduce((a, b) => a + (b.prompt_tokens || 0) + (b.completion_tokens || 0), 0), redacted: logs.value.filter((l) => l.redacted).length }
})
const CLS: Record<string, string> = { ok: 'ok', cached: 'info', invalid: 'warn', error: 'bad', blocked: 'bad' }
</script>

<template>
  <main id="main" class="page" tabindex="-1">
    <div class="page-head"><div><h1>AI call log</h1><p>Cost and latency controls: cache hits, token usage, latency, redaction and validation failures per call.</p></div></div>
    <section class="grid grid-kpi mb">
      <div class="card"><span class="section-title">Calls</span><div class="big">{{ stats.calls }}</div></div>
      <div class="card"><span class="section-title">Successful</span><div class="big">{{ stats.ok }}</div></div>
      <div class="card"><span class="section-title">Cache hits</span><div class="big">{{ stats.cached }}</div></div>
      <div class="card"><span class="section-title">Avg latency</span><div class="big">{{ stats.avgMs }} ms</div></div>
      <div class="card"><span class="section-title">Tokens</span><div class="big">{{ stats.tokens.toLocaleString() }}</div></div>
      <div class="card"><span class="section-title">Redacted calls</span><div class="big">{{ stats.redacted }}</div></div>
    </section>
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>When</th><th>Kind</th><th>Provider / model</th><th>Status</th><th>Redaction</th><th>Prompt / response chars</th><th>Tokens</th><th>Latency</th><th>Error</th></tr></thead>
        <tbody>
          <tr v-for="l in logs" :key="l.id">
            <td class="small">{{ datetime(l.created_at) }}</td><td><code>{{ l.kind }}</code></td><td class="small">{{ l.provider }} · {{ l.model }}</td>
            <td><span class="pill plain" :class="CLS[l.status]">{{ l.status }}</span></td><td class="small">{{ l.redacted ? `${l.redaction_count} items` : '—' }}</td>
            <td class="tnum small">{{ l.prompt_chars }} / {{ l.response_chars }}</td><td class="tnum small">{{ (l.prompt_tokens || 0) + (l.completion_tokens || 0) || '—' }}</td>
            <td class="tnum small">{{ l.latency_ms }} ms</td><td class="small" style="max-width: 300px">{{ l.error }}</td>
          </tr>
          <tr v-if="!logs.length"><td colspan="9" class="empty">No AI calls yet.</td></tr>
        </tbody>
      </table>
    </div>
  </main>
</template>

<style scoped>.big { font-size: 24px; font-weight: 700; }</style>
