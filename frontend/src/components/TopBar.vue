<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import { applyLocale } from '@/i18n'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'
import type { AlertItem } from '@/api/types'
import Icon from './Icon.vue'

const { t, locale } = useI18n()
const auth = useAuth()
const ui = useUi()
const router = useRouter()
const menuOpen = ref(false)
const menuWrap = ref<HTMLElement>()
const unread = ref(0)
let timer: number | undefined

const isAr = computed(() => locale.value === 'ar')
const displayName = computed(() => auth.user?.full_name || auth.user?.email || '')
const initials = computed(() => {
  const parts = displayName.value.split(/[\s@._-]+/).filter(Boolean)
  return ((parts[0]?.[0] || '') + (parts[1]?.[0] || '')).toUpperCase() || '?'
})

async function toggleLocale() {
  const next = isAr.value ? 'en' : 'ar'
  applyLocale(next)
  try {
    await api.patch('/auth/me', { locale: next })
  } catch {
    /* non-blocking */
  }
}
async function signOut() {
  await auth.logout()
  router.push('/login')
}
async function pollAlerts() {
  try {
    unread.value = (await api.get<AlertItem[]>('/alerts?unacknowledged=true')).length
  } catch {
    /* ignore */
  }
}
function onDocClick(e: MouseEvent) {
  if (menuOpen.value && menuWrap.value && !menuWrap.value.contains(e.target as Node)) menuOpen.value = false
}
function onDocKey(e: KeyboardEvent) {
  if (e.key === 'Escape') menuOpen.value = false
}
onMounted(() => {
  pollAlerts()
  timer = window.setInterval(pollAlerts, 60000)
  document.addEventListener('mousedown', onDocClick)
  document.addEventListener('keydown', onDocKey)
})
onBeforeUnmount(() => {
  window.clearInterval(timer)
  document.removeEventListener('mousedown', onDocClick)
  document.removeEventListener('keydown', onDocKey)
})
</script>

<template>
  <div class="topbar no-print">
    <div class="topbar-inner">
      <RouterLink to="/programs" class="brand" :aria-label="t('app.name')">
        <img src="/favicon.svg" alt="" width="30" height="30" />
        <span class="brand-text">
          <span class="brand-name">{{ t('app.short') }}</span>
          <span class="brand-sub">{{ t('app.name') }}</span>
        </span>
      </RouterLink>
      <nav class="topnav" aria-label="Main">
        <RouterLink to="/programs"><Icon name="grid" />{{ t('nav.programs') }}</RouterLink>
        <RouterLink to="/portfolio"><Icon name="layers" />{{ t('nav.portfolio') }}</RouterLink>
        <RouterLink to="/alerts"><Icon name="bell" />{{ t('nav.alerts') }}<span v-if="unread" class="badge" :aria-label="`${unread} unread`">{{ unread > 99 ? '99+' : unread }}</span></RouterLink>
      </nav>
      <span class="spacer" />
      <div class="actions">
        <button class="btn btn-ghost btn-icon btn-sm" :aria-label="t('header.theme')" :title="t('header.theme')" @click="ui.toggleTheme()">
          <Icon :name="ui.theme === 'dark' ? 'sun' : 'moon'" />
        </button>
        <button class="btn btn-ghost btn-sm lang" :lang="isAr ? 'en' : 'ar'" @click="toggleLocale"><Icon name="globe" /><span>{{ t('header.language') }}</span></button>
        <span class="divider" aria-hidden="true" />
        <div ref="menuWrap" class="menu-wrap">
          <button class="user-btn" aria-haspopup="menu" :aria-expanded="menuOpen" @click="menuOpen = !menuOpen">
            <span class="avatar" aria-hidden="true">{{ initials }}</span>
            <span class="user-meta">
              <span class="user-name">{{ displayName }}</span>
              <span class="user-role">{{ t(`roles.${auth.user?.role}`) }}</span>
            </span>
            <Icon name="chevron-down" :size="14" class="chev" :class="{ open: menuOpen }" />
          </button>
          <Transition name="pop">
            <div v-if="menuOpen" class="menu" role="menu" @click="menuOpen = false">
              <div class="menu-user">
                <span class="avatar lg" aria-hidden="true">{{ initials }}</span>
                <div class="menu-user-text">
                  <strong>{{ displayName }}</strong>
                  <span class="muted small">{{ auth.user?.email }}</span>
                </div>
              </div>
              <RouterLink role="menuitem" to="/account"><Icon name="user" />{{ t('nav.account') }}</RouterLink>
              <template v-if="auth.isAdmin">
                <div class="menu-label">{{ t('nav.admin') }}</div>
                <RouterLink role="menuitem" to="/admin/users"><Icon name="users" />{{ t('nav.users') }}</RouterLink>
                <RouterLink role="menuitem" to="/admin/organisation"><Icon name="building" />{{ t('nav.organisation') }}</RouterLink>
                <RouterLink role="menuitem" to="/admin/alert-rules"><Icon name="sliders" />{{ t('nav.alertRules') }}</RouterLink>
                <RouterLink role="menuitem" to="/admin/audit"><Icon name="file" />{{ t('nav.audit') }}</RouterLink>
                <RouterLink role="menuitem" to="/admin/ai-logs"><Icon name="cpu" />{{ t('nav.aiLogs') }}</RouterLink>
                <RouterLink v-if="auth.user?.is_platform_admin" role="menuitem" to="/platform/tenants"><Icon name="server" />{{ t('nav.tenants') }}</RouterLink>
              </template>
              <div class="menu-sep" />
              <button role="menuitem" class="linklike danger" @click="signOut"><Icon name="logout" />{{ t('header.signOut') }}</button>
            </div>
          </Transition>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.topbar {
  position: sticky; top: 0; z-index: 40;
  background: var(--header-bg); backdrop-filter: saturate(180%) blur(14px); -webkit-backdrop-filter: saturate(180%) blur(14px);
  border-bottom: 1px solid var(--border);
}
.topbar-inner { display: flex; align-items: center; gap: 8px 16px; flex-wrap: wrap; padding: 10px 20px; min-height: 60px; }
.brand { display: inline-flex; align-items: center; gap: 10px; color: var(--text); white-space: nowrap; }
.brand:hover { text-decoration: none; }
.brand img { border-radius: 8px; box-shadow: var(--shadow); }
.brand-text { display: flex; flex-direction: column; line-height: 1.15; }
.brand-name { font-weight: 750; font-size: 15px; letter-spacing: -0.01em; }
.brand-sub { font-size: 11px; color: var(--muted); font-weight: 500; }
.topnav { display: flex; gap: 2px; margin-inline-start: 12px; padding-inline-start: 16px; border-inline-start: 1px solid var(--border); }
.topnav a {
  padding: 7px 12px; border-radius: 9px; color: var(--muted); font-weight: 600; font-size: 13.5px;
  display: inline-flex; gap: 7px; align-items: center; transition: background 0.15s, color 0.15s;
}
.topnav a:hover { text-decoration: none; color: var(--text); background: var(--surface-3); }
.topnav a.router-link-active { background: var(--brand-soft); color: var(--brand-2); }
.badge {
  background: var(--c-critical); color: #fff; border-radius: 999px; font-size: 10.5px; font-weight: 700;
  min-width: 18px; padding: 0 5px; line-height: 18px; text-align: center; box-shadow: 0 0 0 2px var(--surface);
}
.actions { display: flex; align-items: center; gap: 4px; }
.lang { font-weight: 600; }
.divider { width: 1px; height: 24px; background: var(--border); margin: 0 6px; }
.menu-wrap { position: relative; }
.user-btn {
  display: inline-flex; align-items: center; gap: 9px; padding: 4px 8px 4px 4px; border-radius: 999px;
  border: 1px solid transparent; background: transparent; color: var(--text); font: inherit; cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
:root[dir='rtl'] .user-btn { padding: 4px 4px 4px 8px; }
.user-btn:hover, .user-btn[aria-expanded='true'] { background: var(--surface-3); border-color: var(--border); }
.avatar {
  width: 32px; height: 32px; border-radius: 50%; display: grid; place-items: center; flex-shrink: 0;
  background: linear-gradient(135deg, var(--brand-2), color-mix(in srgb, var(--brand-2) 55%, #06b6d4));
  color: #fff; font-size: 12px; font-weight: 700; letter-spacing: 0.02em;
}
.avatar.lg { width: 40px; height: 40px; font-size: 14px; }
.user-meta { display: flex; flex-direction: column; line-height: 1.2; text-align: start; max-width: 180px; }
.user-name { font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.user-role { font-size: 11px; color: var(--muted); }
.chev { color: var(--muted); transition: transform 0.2s var(--ease); }
.chev.open { transform: rotate(180deg); }
.menu {
  position: absolute; inset-inline-end: 0; top: calc(100% + 8px); min-width: 260px; display: flex; flex-direction: column;
  padding: 6px; gap: 1px; z-index: 50; background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; box-shadow: var(--shadow-lg); transform-origin: top right;
}
.menu-user { display: flex; align-items: center; gap: 10px; padding: 10px 10px 12px; margin-bottom: 4px; border-bottom: 1px solid var(--border); }
.menu-user-text { display: flex; flex-direction: column; min-width: 0; }
.menu-user-text strong { font-size: 13.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.menu a, .menu button {
  display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 7px; color: var(--text-2);
  font-size: 13.5px; font-weight: 500; width: 100%;
}
.menu a .icon, .menu button .icon { color: var(--muted); }
.menu a:hover, .menu button:hover { background: var(--surface-3); color: var(--text); text-decoration: none; }
.menu a.router-link-active { color: var(--brand-2); }
.menu a.router-link-active .icon { color: var(--brand-2); }
.menu .danger:hover, .menu .danger:hover .icon { color: var(--bad); background: var(--bad-bg); }
.menu-label { padding: 10px 10px 4px; font-size: 10.5px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }
.menu-sep { height: 1px; background: var(--border); margin: 4px 2px; }
.pop-enter-active, .pop-leave-active { transition: opacity 0.14s var(--ease), transform 0.14s var(--ease); }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: translateY(-4px) scale(0.98); }
@media (max-width: 900px) { .brand-text, .user-meta { display: none; } }
@media (max-width: 760px) {
  .topnav { margin-inline-start: 0; padding-inline-start: 0; border: 0; order: 10; width: 100%; overflow-x: auto; }
  .lang span, .divider { display: none; }
}
</style>
