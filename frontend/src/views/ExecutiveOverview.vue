<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import AttentionList from '@/components/AttentionList.vue'
import DecisionCards from '@/components/DecisionCards.vue'
import DonutChart from '@/components/DonutChart.vue'
import KpiCard from '@/components/KpiCard.vue'
import RiskList from '@/components/RiskList.vue'
import TrackCards from '@/components/TrackCards.vue'
import TrendChart from '@/components/TrendChart.vue'
import Icon from '@/components/Icon.vue'
import { useDash } from '@/composables/useDash'
import { int, monthYear, pct, pts } from '@/format'
import { useUi } from '@/stores/ui'

const { t } = useI18n()
const router = useRouter()
const ui = useUi()
const { d, store, drillKpi, drillTrack, drillUids } = useDash()
const exporting = ref<string | null>(null)

const c = computed(() => d.value?.cards)
const tagClass = (tag: string | null | undefined) =>
  ({ 'On Track': 'ok', Completed: 'info', Delay: 'warn', 'Critical Delay': 'bad' })[tag || ''] || 'neutral'
const statusTag = (tag: string | null | undefined) =>
  ({ 'On Track': t('status.on_track'), Completed: t('status.completed'), Delay: t('status.delay'), 'Critical Delay': t('status.critical_delay') })[tag || ''] || tag

const trendSummary = computed(() => {
  const s = d.value?.trend.summary
  if (!s || !d.value) return ''
  return t('trend.summary', {
    p: (s.planned ?? 0).toFixed(1), a: (s.actual ?? 0).toFixed(1), b: Math.abs(s.behind_pts).toFixed(1),
    dir: s.behind_pts >= 0 ? t('trend.behind') : t('trend.ahead'), cycle: d.value.trend.cycle_label,
    n: d.value.trend.cycles_reported, c: s.tracks_covered, t: s.tracks_total,
  })
})
const attention = computed(() => (d.value ? [...d.value.attention.derived, ...d.value.attention.items].slice(0, 6) : []))

async function exportAs(fmt: 'pdf' | 'xlsx' | 'pptx') {
  if (!d.value) return
  exporting.value = fmt
  try {
    await api.download(`/snapshots/${d.value.snapshot.id}/export/${fmt}`, `dashboard.${fmt}`)
  } catch (e) {
    ui.error(e)
  } finally {
    exporting.value = null
  }
}
</script>

<template>
  <div v-if="store.loading && !d" class="empty"><span class="spinner" /> {{ t('common.loading') }}</div>
  <div v-else-if="!d" class="card empty">
    <h3>No dashboard yet</h3>
    <p>{{ store.error || 'Upload a plan snapshot and approve the mapping to build the dashboard.' }}</p>
    <RouterLink class="btn btn-primary mt" :to="`/p/${store.program?.id}/snapshots`">Go to snapshots</RouterLink>
  </div>
  <template v-else-if="c">
    <div class="page-head">
      <div>
        <h1>{{ t('nav.overview') }}</h1>
        <p>Snapshot v{{ d.snapshot.version_no }} · planned-to-date method: {{ d.snapshot.planned_method }}<span v-if="d.snapshot.rebaselined"> · <strong>re-baselined</strong></span></p>
      </div>
      <div class="row no-print">
        <button class="btn" :disabled="!!exporting" @click="exportAs('pdf')"><span v-if="exporting === 'pdf'" class="spinner" /><Icon v-else name="download" :size="15" />PDF</button>
        <button class="btn" :disabled="!!exporting" @click="exportAs('xlsx')"><span v-if="exporting === 'xlsx'" class="spinner" /><Icon v-else name="download" :size="15" />Excel</button>
        <button class="btn" :disabled="!!exporting" @click="exportAs('pptx')"><span v-if="exporting === 'pptx'" class="spinner" /><Icon v-else name="download" :size="15" />PowerPoint</button>
      </div>
    </div>

    <section aria-label="Key performance indicators" class="grid grid-kpi">
      <KpiCard :label="t('cards.completion')" :value="pct(c.program_completion.value)" :tag="statusTag(c.program_completion.tag)"
               :tag-class="tagClass(c.program_completion.tag)" :bar="c.program_completion.value" :marker="c.program_completion.planned"
               :caption="t('cards.plannedVs', { p: (c.program_completion.planned ?? 0).toFixed(1), v: pts(c.program_completion.variance_pts).replace(' pts', '') })"
               clickable @open="drillKpi('program_completion')" />
      <KpiCard :label="t('cards.activeTracks')" :value="`${int(c.active_tracks.value)}/${int(c.active_tracks.total)}`"
               :caption="t('cards.pendingActivation', { n: int(c.active_tracks.pending) }, c.active_tracks.pending ?? 0)"
               :bar="c.active_tracks.total ? (100 * (c.active_tracks.value || 0)) / c.active_tracks.total : 0" clickable
               @open="drillKpi('active_tracks')" />
      <KpiCard :label="t('cards.totalMilestones')" :value="int(c.total_milestones.value)"
               :caption="t('cards.scope', { n: int(c.total_milestones.tracks_covered) })"
               :bar="c.total_milestones.value ? (100 * (c.total_milestones.by_status.completed || 0)) / c.total_milestones.value : 0"
               clickable @open="drillKpi('total_milestones')" />
      <KpiCard :label="t('cards.onTrack')" :value="int(c.on_track.value)" :caption="t('cards.progressing')" tag-class="ok"
               :bar="c.on_track.of ? (100 * (c.on_track.value || 0)) / c.on_track.of : 0" bar-color="var(--c-on-track)" clickable
               @open="drillKpi('milestones_on_track')" />
      <KpiCard :label="t('cards.notStarted')" :value="int(c.not_started.value)" :caption="t('cards.pending')"
               :bar="c.not_started.of ? (100 * (c.not_started.value || 0)) / c.not_started.of : 0" bar-color="var(--c-not-started)"
               clickable @open="drillKpi('milestones_not_started')" />
      <KpiCard :label="t('cards.decisions')" :value="int(c.decisions_required.value)" :tag="t('cards.action')" tag-class="warn"
               :caption="t('cards.highPriority', { n: c.decisions_required.high_priority })"
               :bar="c.decisions_required.value ? (100 * c.decisions_required.high_priority) / c.decisions_required.value : 0"
               bar-color="var(--c-delay)" clickable @open="router.push(`/p/${d.program_id}/decisions`)" />
      <KpiCard :label="t('cards.highRisks')" :value="int(c.high_risks.value)" :tag="t('cards.monitor')" tag-class="bad"
               :caption="t('cards.ofTracked', { n: c.high_risks.tracked })"
               :bar="c.high_risks.tracked ? (100 * (c.high_risks.value || 0)) / c.high_risks.tracked : 0" bar-color="var(--c-critical)"
               clickable @open="router.push(`/p/${d.program_id}/risks`)" />
      <KpiCard :label="t('cards.timeline')" :value="c.active_track_timeline.available ? t('cards.months', { n: int(c.active_track_timeline.value) }) : '—'"
               :caption="c.active_track_timeline.available ? `${monthYear(c.active_track_timeline.start)} – ${monthYear(c.active_track_timeline.finish)} · ${t('cards.monthOf', { x: c.active_track_timeline.month, y: c.active_track_timeline.of_months, z: c.active_track_timeline.elapsed_pct })}` : ''"
               :bar="c.active_track_timeline.elapsed_pct" clickable @open="drillKpi('active_track_timeline')" />
      <KpiCard :label="t('cards.nextMilestone')" :value="c.next_milestone.name || '—'" small
               :caption="c.next_milestone.start ? t('cards.startsIn', { month: monthYear(c.next_milestone.start) }) : ''" clickable
               @open="router.push({ path: `/p/${d.program_id}/milestones`, query: { focus: c.next_milestone.milestone_id } })" />
    </section>

    <section v-if="d.ai_summary" class="card mt ai">
      <div class="card-head"><h2><Icon name="sparkles" :size="18" />{{ t('sections.aiSummary') }}</h2><span class="src">AI narrative · numbers from KPI engine · {{ d.ai_summary.model }}</span></div>
      <p><strong>{{ d.ai_summary.content.headline }}</strong></p>
      <p class="mt-s">{{ d.ai_summary.content.summary }}</p>
      <p v-if="d.ai_summary.flags?.length" class="muted small">Guardrail flags: {{ d.ai_summary.flags.join(', ') }}</p>
    </section>

    <div class="grid two-col mt">
      <section class="card">
        <div class="card-head"><h2>{{ t('sections.tracksOverview') }}</h2><span class="src">{{ t('sections.source', { s: d.tracks[0]?.source_label || '—' }) }}</span></div>
        <TrackCards :tracks="d.tracks" @open="(tr) => drillTrack(tr.id, `${tr.label} · ${tr.name}`)" />
      </section>
      <section class="card">
        <div class="card-head"><h2>{{ t('sections.activeProgress') }}</h2></div>
        <DonutChart :percent="d.active_track_progress.percent" :label="t('sections.activeProgress')"
                    :sub="`${d.active_track_progress.active_tracks}/${d.active_track_progress.total_tracks} tracks · plan ${d.active_track_progress.planned.toFixed(1)}%`" />
      </section>
    </div>

    <section class="card mt">
      <div class="card-head"><h2>{{ t('sections.trend') }}</h2></div>
      <TrendChart :points="d.trend.points" @select="(id) => store.selectSnapshot(id)" />
      <p class="strip small">{{ trendSummary }}</p>
    </section>

    <div class="grid grid-2 mt">
      <section class="card">
        <div class="card-head"><h2>{{ t('sections.keyDecisions') }}</h2><RouterLink :to="`/p/${d.program_id}/decisions`" class="small">View all</RouterLink></div>
        <DecisionCards :items="d.decisions.filter((x) => x.status === 'Pending').slice(0, 4)" />
      </section>
      <section class="card">
        <div class="card-head"><h2>{{ t('sections.risks') }}</h2><RouterLink :to="`/p/${d.program_id}/risks`" class="small">View all</RouterLink></div>
        <RiskList :items="d.risks.slice(0, 4)" />
      </section>
    </div>

    <section class="card mt">
      <div class="card-head"><h2>{{ t('sections.attention') }}</h2><RouterLink :to="`/p/${d.program_id}/attention`" class="small">View all</RouterLink></div>
      <AttentionList :items="attention" @drill="(a) => drillUids(a.related_task_uids, a.title)" />
    </section>
  </template>
</template>

<style scoped>
.two-col { grid-template-columns: 2fr 1fr; }
.strip { margin-top: 12px; padding: 10px 14px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 10px; color: var(--text-2); }
.ai {
  position: relative; overflow: hidden;
  background: linear-gradient(135deg, color-mix(in srgb, var(--brand-2) 7%, var(--surface)), var(--surface) 60%);
  border-color: color-mix(in srgb, var(--brand-2) 25%, var(--border));
}
.ai h2 { display: inline-flex; align-items: center; gap: 8px; }
.ai h2 .icon { color: var(--brand-2); }
.mt-s { margin-top: 6px; color: var(--text-2); line-height: 1.6; }
@media (max-width: 1000px) { .two-col { grid-template-columns: 1fr; } }
</style>
