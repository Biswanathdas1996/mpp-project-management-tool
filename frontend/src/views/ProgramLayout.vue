<script setup lang="ts">
// Reference header (client logo + name EN/AR, title, subtitle, vendor logo, KPI strip, chips),
// grouped navigation (EXECUTIVE | PROGRAM | GOVERNANCE | ANALYSIS | MANAGE) and footer.
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'
import { useProgram } from '@/stores/program'
import { date, int, pct } from '@/format'
import Icon from '@/components/Icon.vue'

const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()
const auth = useAuth()
const store = useProgram()

const pid = computed(() => Number(route.params.pid))
watch(pid, async (id) => {
  if (!id) return
  try {
    await store.open(id)
    await store.loadDashboard()
  } catch {
    router.replace('/programs')
  }
}, { immediate: true })

const d = computed(() => store.dashboard)
const h = computed(() => d.value?.header)
const isAr = computed(() => locale.value === 'ar')
const clientName = computed(() => (isAr.value && h.value?.client_name_ar) || h.value?.client_name || store.program?.client_name || '')
const clientNameAlt = computed(() => (isAr.value ? h.value?.client_name : h.value?.client_name_ar) || '')
const programTitle = computed(() => {
  const name = (isAr.value && store.program?.name_ar) || store.program?.name || ''
  return `${name} – ${isAr.value ? 'لوحة المعلومات التنفيذية' : 'Executive Dashboard'}`
})
const avgProgress = computed(() => Math.min(100, Math.max(0, d.value?.kpi_strip.avg_progress || 0)))

const groups = computed(() => [
  { label: t('nav.executive'), items: [{ to: 'overview', label: t('nav.overview'), icon: 'grid' }] },
  { label: t('nav.program'), items: [
    { to: 'tracks', label: t('nav.tracks'), icon: 'layers' },
    { to: 'milestones', label: t('nav.milestones'), icon: 'flag' },
    { to: 'timeline', label: t('nav.timeline'), icon: 'calendar' },
  ] },
  { label: t('nav.governance'), items: [
    { to: 'decisions', label: t('nav.decisions'), icon: 'scale' },
    { to: 'risks', label: t('nav.risks'), icon: 'shield' },
    { to: 'attention', label: t('nav.attention'), icon: 'bell' },
  ] },
  { label: t('nav.analysis'), items: [
    { to: 'changes', label: t('nav.changes'), icon: 'activity' },
    { to: 'kpis', label: t('nav.kpis'), icon: 'chart' },
    { to: 'insights', label: t('nav.insights'), icon: 'sparkles' },
  ] },
  { label: t('nav.manage'), items: [
    { to: 'snapshots', label: t('nav.snapshots'), icon: 'file' },
    ...(auth.isAdmin ? [
      { to: 'mapping', label: t('nav.mapping'), icon: 'sliders' },
      { to: 'settings', label: t('nav.settings'), icon: 'settings' },
    ] : []),
  ] },
])

async function onSnapshot(e: Event) {
  const v = (e.target as HTMLSelectElement).value
  await store.selectSnapshot(v ? Number(v) : null)
}
</script>

<template>
  <div class="program-shell">
    <div class="workspace">
      <nav class="pnav no-print" aria-label="Program">
        <div class="pnav-inner">
          <div v-for="g in groups" :key="g.label" class="pnav-group">
            <span class="pnav-label">{{ g.label }}</span>
            <RouterLink v-for="i in g.items" :key="i.to" :to="`/p/${pid}/${i.to}`">
              <Icon :name="i.icon" :size="16" />
              <span>{{ i.label }}</span>
            </RouterLink>
          </div>
        </div>
      </nav>
      <div class="workspace-main">
    <header class="phead" :style="h?.primary_color ? { '--brand': h.primary_color } as any : undefined">
      <div class="phead-inner hero">
        <div v-if="h?.client_logo_url || clientName" class="brand-block">
          <img v-if="h?.client_logo_url" :src="h.client_logo_url" :alt="clientName" class="logo" />
          <div v-else class="logo-fallback" aria-hidden="true">{{ clientName.slice(0, 2).toUpperCase() }}</div>
        </div>
        <div class="title-block">
          <div v-if="clientName" class="names">
            <span class="client">{{ clientName }}</span>
            <span v-if="clientNameAlt" class="client-alt" :lang="isAr ? 'en' : 'ar'" :dir="isAr ? 'ltr' : 'rtl'">{{ clientNameAlt }}</span>
          </div>
          <h1>{{ programTitle }}</h1>
          <p v-if="h?.subtitle || store.program?.subtitle" class="subtitle">{{ h?.subtitle || store.program?.subtitle }}</p>
        </div>
        <div class="hero-side">
          <div class="row chips">
            <span v-if="h?.location || store.program?.location" class="chip"><Icon name="pin" :size="14" />{{ h?.location || store.program?.location }}</span>
            <label v-if="store.readySnapshots.length" class="chip snap">
              <Icon name="calendar" :size="14" />
              <span>{{ d ? t('header.asOf', { date: date(d.snapshot.as_of) }) : t('header.snapshot') }}</span>
              <Icon name="chevron-down" :size="13" />
              <select class="snap-select" :value="store.selectedSnapshotId ?? ''" aria-label="Select snapshot" @change="onSnapshot">
                <option value="">Latest</option>
                <option v-for="s in store.readySnapshots" :key="s.id" :value="s.id">v{{ s.version_no }} · {{ s.as_of }}</option>
              </select>
            </label>
          </div>
          <img v-if="h?.vendor_logo_url" :src="h.vendor_logo_url" alt="Vendor" class="logo vendor" />
        </div>
      </div>
      <div v-if="d" class="phead-inner strip-row">
        <dl class="kpi-strip" aria-label="Key figures">
          <div><dt>{{ t('header.tracks') }}</dt><dd class="tnum">{{ d.kpi_strip.tracks }}</dd></div>
          <div><dt>{{ t('header.active') }}</dt><dd class="tnum">{{ int(d.kpi_strip.active) }}</dd></div>
          <div>
            <dt>{{ t('header.avgProgress') }}</dt>
            <dd class="tnum">{{ pct(d.kpi_strip.avg_progress) }}</dd>
            <span class="mini-bar" aria-hidden="true"><span :style="{ width: `${avgProgress}%` }" /></span>
          </div>
          <div><dt>{{ t('header.milestones') }}</dt><dd class="tnum">{{ int(d.kpi_strip.milestones) }}</dd></div>
        </dl>
      </div>
    </header>
        <main id="main" class="page" tabindex="-1">
          <div v-if="d?.snapshot.warnings?.length && route.name === 'overview'" class="alert warn mb notes">
            <Icon name="alert" :size="16" />
            <span><strong>Data notes:</strong> {{ d.snapshot.warnings.join(' · ') }}</span>
          </div>
          <RouterView />
        </main>
        <footer class="pfoot">
          <div class="pfoot-inner">
            <span class="muted">{{ t('footer.contact') }}</span>
            <a v-if="h?.support_email" :href="`mailto:${h.support_email}`">{{ h.support_email }}</a>
            <a v-if="h?.contact_url" :href="h.contact_url" target="_blank" rel="noopener">{{ h.contact_url }}</a>
            <span v-if="!h?.support_email && !h?.contact_url" class="muted">—</span>
            <span class="spacer" />
            <span v-if="d" class="muted small">Snapshot v{{ d.snapshot.version_no }} · KPI engine {{ d.snapshot.kpi_engine_version }} · {{ d.snapshot.filename }}</span>
          </div>
        </footer>
      </div>
    </div>
  </div>
</template>

<style scoped>
.program-shell { min-height: calc(100vh - 61px); display: flex; flex-direction: column; }
.phead {
  background:
    radial-gradient(720px 180px at 0% 0%, color-mix(in srgb, var(--brand-2) 9%, transparent), transparent 70%),
    var(--surface);
  border-bottom: 1px solid var(--border);
}
.phead-inner { margin: 0; padding: 18px 28px 0; display: flex; align-items: center; gap: 18px; flex-wrap: wrap; }
.hero { align-items: flex-start; }
.brand-block { display: flex; align-items: center; }
.logo { height: 52px; max-width: 150px; object-fit: contain; }
.logo.vendor { height: 34px; opacity: 0.9; }
.logo-fallback {
  width: 52px; height: 52px; border-radius: 14px; display: grid; place-items: center; font-weight: 750; font-size: 17px; letter-spacing: 0.02em;
  background: linear-gradient(140deg, var(--brand), color-mix(in srgb, var(--brand) 60%, #06b6d4));
  color: #fff; box-shadow: var(--shadow-md), inset 0 1px 0 rgb(255 255 255 / 0.2);
}
.title-block { flex: 1; min-width: min(280px, 100%); display: flex; flex-direction: column; gap: 4px; }
.names { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.client { font-weight: 650; color: var(--brand-2); text-transform: uppercase; letter-spacing: 0.07em; font-size: 11.5px; }
.client-alt { color: var(--muted); font-size: 12.5px; }
.subtitle { color: var(--muted); font-size: 13.5px; }
.hero-side { display: flex; flex-direction: column; align-items: flex-end; gap: 12px; }
.chips { gap: 8px; justify-content: flex-end; }
.snap { position: relative; cursor: pointer; transition: border-color 0.15s, box-shadow 0.15s; }
.snap:hover { border-color: var(--border-strong); }
.snap:focus-within { border-color: var(--brand-2); box-shadow: var(--ring); }
.snap-select { position: absolute; inset: 0; width: 100%; opacity: 0; cursor: pointer; font: inherit; }
.strip-row { padding-top: 16px; padding-bottom: 16px; }
.kpi-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 0; width: 100%; }
.kpi-strip > div {
  position: relative; overflow: hidden; display: flex; flex-direction: column; gap: 2px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 10px 14px 12px; box-shadow: var(--shadow-xs);
}
.kpi-strip dt { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.07em; font-weight: 600; }
.kpi-strip dd { margin: 0; font-size: 22px; font-weight: 700; letter-spacing: -0.02em; color: var(--text); }
.mini-bar { position: absolute; inset-inline: 0; bottom: 0; height: 3px; background: var(--surface-3); }
.mini-bar > span { display: block; height: 100%; background: var(--brand-2); }
.workspace {
  position: relative;
  flex: 1;
  display: grid;
  grid-template-columns: 252px minmax(0, 1fr);
  align-items: stretch;
  min-width: 0;
}
.workspace::before {
  content: '';
  position: absolute;
  inset-block: 0;
  inset-inline-start: 0;
  width: 252px;
  background: var(--surface);
  border-inline-end: 1px solid var(--border);
}
.workspace-main { grid-column: 2; min-width: 0; display: flex; flex-direction: column; background: var(--bg); }
.workspace-main > .page { max-width: none; margin: 0; padding: 22px 28px 36px; }
.pnav {
  position: sticky;
  top: 61px;
  z-index: 5;
  align-self: start;
  max-height: calc(100vh - 77px);
  overflow: auto;
  background: var(--surface);
  border-inline-end: 1px solid var(--border);
  padding: 14px 10px 20px;
}
.pnav-inner { display: flex; flex-direction: column; gap: 4px; }
.pnav-group { display: flex; flex-direction: column; gap: 2px; }
.pnav-group + .pnav-group { margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border); }
.pnav-label {
  display: block;
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.09em;
  color: var(--muted);
  text-transform: uppercase;
  padding: 6px 12px 4px;
}
.pnav a {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  margin-inline: 4px;
  padding: 8px 10px;
  border-radius: 9px;
  color: var(--text-2);
  font-weight: 550;
  font-size: 13.5px;
  line-height: 1.25;
  transition: background 0.15s var(--ease), color 0.15s var(--ease);
}
.pnav a .icon { color: var(--muted); }
.pnav a:hover { text-decoration: none; color: var(--text); background: var(--surface-3); }
.pnav a:hover .icon { color: var(--text-2); }
.pnav a.router-link-active {
  color: var(--brand-2);
  background: var(--brand-soft);
  font-weight: 650;
}
.pnav a.router-link-active .icon { color: var(--brand-2); }
.pnav a.router-link-active::before {
  content: '';
  position: absolute;
  inset-inline-start: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 999px;
  background: var(--brand-2);
}
.notes { display: flex; gap: 10px; align-items: flex-start; }
.notes .icon { color: var(--warn); margin-top: 2px; }
.pfoot { margin-top: auto; border-top: 1px solid var(--border); background: var(--surface); font-size: 13px; }
.pfoot-inner { margin: 0; padding: 14px 28px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
@media (max-width: 960px) {
  .workspace { grid-template-columns: 1fr; }
  .workspace-main { grid-column: auto; }
  .workspace::before { display: none; }
  .pnav {
    position: sticky;
    top: 60px;
    z-index: 25;
    max-height: none;
    width: auto;
    height: auto;
    border-inline-end: 0;
    border-bottom: 1px solid var(--border);
    padding: 8px 8px 10px;
    background: color-mix(in srgb, var(--surface) 88%, transparent);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
  }
  .pnav-inner { flex-direction: row; gap: 2px; overflow-x: auto; scrollbar-width: none; }
  .pnav-inner::-webkit-scrollbar { display: none; }
  .pnav-group { flex-direction: row; align-items: center; gap: 2px; flex-shrink: 0; }
  .pnav-group + .pnav-group { margin-top: 0; padding-top: 0; border-top: 0; padding-inline-start: 8px; margin-inline-start: 4px; border-inline-start: 1px solid var(--border); }
  .pnav-label { display: none; }
  .pnav a { white-space: nowrap; padding: 7px 10px; }
  .workspace-main > .page { padding: 18px 16px 32px; }
}
@media (max-width: 900px) {
  .hero-side { align-items: flex-start; width: 100%; }
  .chips { justify-content: flex-start; }
}
@media (max-width: 720px) {
  .phead-inner, .pfoot-inner { padding-inline: 16px; }
  .kpi-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .title-block h1 { font-size: 20px; }
}
@media print {
  .workspace { display: block; }
}
</style>
