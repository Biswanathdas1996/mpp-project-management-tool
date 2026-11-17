<script setup lang="ts">
// AI insights: executive summary, change narrative, slippage root-cause, forecast, governance drafts,
// Q&A over plan data and the discovery profile. AI only narrates; numbers come from the KPI engine.
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import type { Insight, Profile } from '@/api/types'
import { useDash } from '@/composables/useDash'
import { datetime } from '@/format'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'

const ui = useUi()
const auth = useAuth()
const { sid, store, drillUids } = useDash()
const status = ref<{ enabled: boolean; mode: string; model: string; redaction: boolean } | null>(null)
const latest = ref<Record<string, Insight>>({})
const qa = ref<Insight[]>([])
const busy = ref<string | null>(null)
const question = ref('')
const discovery = ref<{ profile: Profile; discovery: NonNullable<Profile['discovery']>; insight: Insight | null } | null>(null)
const tab = ref<'insights' | 'qa' | 'discovery'>('insights')

const KINDS = [
  { kind: 'executive_summary', title: 'Executive summary' },
  { kind: 'change_narrative', title: 'Change narrative' },
  { kind: 'root_cause', title: 'Slippage root-cause' },
  { kind: 'forecast', title: 'Forecast' },
  { kind: 'draft_governance', title: 'Draft risks, decisions & attention items' },
] as const

async function load() {
  if (!sid.value) return
  try {
    const r = await api.get<{ latest: Record<string, Insight>; qa: Insight[] }>(`/snapshots/${sid.value}/insights`)
    latest.value = r.latest
    qa.value = r.qa
    discovery.value = await api.get(`/snapshots/${sid.value}/discovery`)
  } catch (e) {
    ui.error(e)
  }
}
onMounted(async () => {
  status.value = await api.get('/ai/status')
})
watch(sid, load, { immediate: true })

async function generate(kind: string, force = false) {
  busy.value = kind
  try {
    const ins = await api.post<Insight>(`/snapshots/${sid.value}/insights/${kind}?force=${force}`)
    latest.value = { ...latest.value, [kind]: ins }
    if (kind === 'draft_governance' && ins.drafts_created) {
      const c = ins.drafts_created
      ui.toast(`Created ${c.risks} risk, ${c.decisions} decision and ${c.attention} attention drafts for review${ins.duplicates_skipped ? ` (${ins.duplicates_skipped} duplicates of existing items skipped)` : ""}`)
    }
    if (kind === 'executive_summary') await store.loadDashboard(true)
  } catch (e) {
    ui.error(e)
  } finally {
    busy.value = null
  }
}
async function ask() {
  if (question.value.trim().length < 3) return
  busy.value = 'qa'
  try {
    const ins = await api.post<Insight>(`/snapshots/${sid.value}/ask`, { question: question.value })
    qa.value = [ins, ...qa.value]
    question.value = ''
  } catch (e) {
    ui.error(e)
  } finally {
    busy.value = null
  }
}
const disabledReason = computed(() => (status.value && !status.value.enabled
  ? 'AI is turned off for this organisation. The dashboard, KPIs and exports work fully without it; an admin can enable self-hosted or cloud Ollama under Administration → Organisation.' : ''))
</script>

<template>
  <div>
    <div class="page-head">
      <div><h1>AI insights</h1>
        <p v-if="status">Provider: <strong>{{ status.mode }}</strong> · model {{ status.model }}<span v-if="status.redaction"> · sensitive data redacted before cloud calls</span> · results cached per snapshot</p></div>
    </div>
    <div v-if="disabledReason" class="alert info mb">{{ disabledReason }}</div>
    <div class="tabs" role="tablist">
      <button role="tab" :aria-selected="tab === 'insights'" @click="tab = 'insights'">Insights</button>
      <button role="tab" :aria-selected="tab === 'qa'" @click="tab = 'qa'">Ask the plan</button>
      <button role="tab" :aria-selected="tab === 'discovery'" @click="tab = 'discovery'">Data discovery</button>
    </div>

    <div v-if="tab === 'insights'" class="stack">
      <section v-for="k in KINDS" :key="k.kind" class="card">
        <div class="card-head">
          <h2>{{ k.title }}</h2>
          <div class="row">
            <span v-if="latest[k.kind]" class="muted small">{{ latest[k.kind].model }} · {{ datetime(latest[k.kind].created_at) }} · {{ latest[k.kind].latency_ms }} ms</span>
            <button v-if="auth.isEditor" class="btn btn-sm" :disabled="!status?.enabled || !!busy" @click="generate(k.kind, !!latest[k.kind])">
              <span v-if="busy === k.kind" class="spinner" /> {{ latest[k.kind] ? 'Regenerate' : 'Generate' }}
            </button>
          </div>
        </div>
        <template v-if="latest[k.kind]">
          <div v-if="latest[k.kind].guardrail_flags.length" class="alert warn small mb">Guardrail flags (verify these statements): {{ latest[k.kind].guardrail_flags.join(', ') }}</div>
          <template v-if="k.kind === 'executive_summary'">
            <p><strong>{{ latest[k.kind].content.headline }}</strong></p>
            <p class="mt-s">{{ latest[k.kind].content.summary }}</p>
            <div class="grid grid-3 mt">
              <div><h3>Highlights</h3><ul><li v-for="x in latest[k.kind].content.highlights" :key="x">{{ x }}</li></ul></div>
              <div><h3>Concerns</h3><ul><li v-for="x in latest[k.kind].content.concerns" :key="x">{{ x }}</li></ul></div>
              <div><h3>Recommendations</h3><ul><li v-for="x in latest[k.kind].content.recommendations" :key="x">{{ x }}</li></ul></div>
            </div>
          </template>
          <template v-else-if="k.kind === 'change_narrative'">
            <p>{{ latest[k.kind].content.narrative }}</p>
            <ul class="mt-s"><li v-for="c in latest[k.kind].content.key_changes" :key="c.title"><span class="pill plain" :class="{ high: 'bad', medium: 'warn', low: 'neutral' }[c.impact as string]">{{ c.impact }}</span> <strong>{{ c.title }}</strong> — {{ c.detail }}</li></ul>
          </template>
          <template v-else-if="k.kind === 'root_cause'">
            <p>{{ latest[k.kind].content.summary }}</p>
            <div class="table-wrap mt"><table class="table"><thead><tr><th>Milestone</th><th>Likely cause</th><th>Confidence</th><th>Evidence</th></tr></thead>
              <tbody><tr v-for="c in latest[k.kind].content.causes" :key="c.milestone"><td><strong>{{ c.milestone }}</strong></td><td>{{ c.cause }}</td><td>{{ c.confidence }}</td>
                <td><button v-if="c.evidence_task_uids.length" class="btn btn-sm" @click="drillUids(c.evidence_task_uids, `Evidence · ${c.milestone}`)">{{ c.evidence_task_uids.length }} tasks</button></td></tr></tbody></table></div>
          </template>
          <template v-else-if="k.kind === 'forecast'">
            <p><strong>{{ latest[k.kind].content.likely_finish_window }}</strong> · confidence {{ latest[k.kind].content.confidence }}</p>
            <p class="mt-s">{{ latest[k.kind].content.forecast_narrative }}</p>
            <div class="grid grid-2 mt"><div><h3>Assumptions</h3><ul><li v-for="x in latest[k.kind].content.assumptions" :key="x">{{ x }}</li></ul></div>
              <div><h3>Risks to forecast</h3><ul><li v-for="x in latest[k.kind].content.risks_to_forecast" :key="x">{{ x }}</li></ul></div></div>
          </template>
          <template v-else>
            <p class="muted mb">Drafts are saved with status “AI draft — needs review”. Approve or reject them on the governance pages.</p>
            <div class="grid grid-3">
              <div><h3>Risks ({{ latest[k.kind].content.risks.length }})</h3><ul><li v-for="r in latest[k.kind].content.risks" :key="r.title"><strong>{{ r.severity }}</strong> {{ r.title }}</li></ul></div>
              <div><h3>Decisions ({{ latest[k.kind].content.decisions.length }})</h3><ul><li v-for="r in latest[k.kind].content.decisions" :key="r.title"><strong>{{ r.priority }}</strong> {{ r.title }}</li></ul></div>
              <div><h3>Attention ({{ latest[k.kind].content.attention.length }})</h3><ul><li v-for="r in latest[k.kind].content.attention" :key="r.title"><strong>{{ r.severity }}</strong> {{ r.title }}</li></ul></div>
            </div>
            <div class="row mt">
              <RouterLink class="btn btn-sm" :to="`/p/${store.program?.id}/risks`">Review risks</RouterLink>
              <RouterLink class="btn btn-sm" :to="`/p/${store.program?.id}/decisions`">Review decisions</RouterLink>
              <RouterLink class="btn btn-sm" :to="`/p/${store.program?.id}/attention`">Review attention</RouterLink>
            </div>
          </template>
        </template>
        <p v-else class="muted">Not generated yet for this snapshot.</p>
      </section>
    </div>

    <div v-else-if="tab === 'qa'" class="stack">
      <form class="card row" @submit.prevent="ask">
        <label class="sr-only" for="q">Question</label>
        <input id="q" v-model="question" class="input" style="flex: 1" maxlength="1000" placeholder="e.g. Which tasks are driving the delay on the Citizen Services Portal?" :disabled="!status?.enabled" />
        <button class="btn btn-primary" :disabled="!status?.enabled || busy === 'qa'"><span v-if="busy === 'qa'" class="spinner" /> Ask</button>
      </form>
      <article v-for="a in qa" :key="a.id" class="card">
        <p class="muted small">{{ datetime(a.created_at) }} · {{ a.model }}</p>
        <h3 class="mb-s">{{ a.question }}</h3>
        <p v-if="a.content.cannot_answer" class="alert warn small">The plan data cannot fully answer this.</p>
        <p style="white-space: pre-wrap">{{ a.content.answer }}</p>
        <div class="row mt-s">
          <span class="muted small">confidence {{ a.content.confidence }}</span>
          <button v-if="a.content.cited_task_uids?.length" class="btn btn-sm" @click="drillUids(a.content.cited_task_uids, 'Cited tasks')">{{ a.content.cited_task_uids.length }} cited tasks</button>
          <span v-if="a.guardrail_flags.length" class="pill warn plain" :title="a.guardrail_flags.join(', ')">guardrail flags</span>
        </div>
      </article>
      <p v-if="!qa.length" class="muted">No questions asked yet.</p>
    </div>

    <div v-else-if="discovery" class="stack">
      <section class="card">
        <div class="card-head"><h2>Discovery for this upload</h2><span class="src">proposal by {{ discovery.discovery.proposal_source }}</span></div>
        <p v-if="discovery.discovery.summary">{{ discovery.discovery.summary }}</p>
        <p v-if="discovery.discovery.structure_notes" class="mt-s muted">{{ discovery.discovery.structure_notes }}</p>
        <p class="mt-s"><strong>Proposed mapping:</strong> tracks = {{ JSON.stringify(discovery.discovery.proposal?.track_rule) }}, milestones = {{ JSON.stringify(discovery.discovery.proposal?.milestone_rule) }} — {{ discovery.discovery.proposal?.rationale }}</p>
        <p class="mt-s"><strong>{{ discovery.discovery.proposed_kpis?.length }}</strong> KPIs proposed as supportable by this data.</p>
        <div v-if="discovery.discovery.ideas?.length" class="mt"><h3>Further KPI ideas (not in catalogue)</h3><ul><li v-for="i in discovery.discovery.ideas" :key="i.name"><strong>{{ i.name }}</strong> — {{ i.rationale }}</li></ul></div>
      </section>
      <section class="card">
        <h2 class="mb">Field coverage (% of leaf tasks)</h2>
        <div class="cov">
          <div v-for="(v, k) in discovery.profile.group_coverage_pct" :key="k" class="cov-row">
            <span>{{ k }}</span><div class="bar" style="flex: 1"><span :style="{ width: `${v}%`, background: v > 60 ? 'var(--c-on-track)' : v > 0 ? 'var(--c-delay)' : 'var(--c-not-started)' }" /></div><span class="tnum">{{ v }}%</span>
          </div>
        </div>
      </section>
      <section class="card">
        <h2 class="mb">Data-quality gaps</h2>
        <ul><li v-for="g in discovery.profile.quality_gaps" :key="g.code"><span class="pill plain" :class="{ high: 'bad', medium: 'warn', low: 'neutral', info: 'info' }[g.severity]">{{ g.severity }}</span> {{ g.message }}</li></ul>
        <p v-if="!discovery.profile.quality_gaps?.length" class="muted">No gaps detected.</p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.mt-s { margin-top: 8px; }
.mb-s { margin-bottom: 6px; }
ul { margin: 6px 0 0; padding-inline-start: 18px; }
li { margin: 3px 0; }
.cov { display: grid; gap: 8px; }
.cov-row { display: grid; grid-template-columns: 120px 1fr 54px; gap: 10px; align-items: center; font-size: 13px; }
</style>
