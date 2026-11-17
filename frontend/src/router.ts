import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import type { Role } from '@/api/types'
import { useAuth } from '@/stores/auth'

declare module 'vue-router' {
  interface RouteMeta {
    public?: boolean
    role?: Role
    platform?: boolean
    title?: string
  }
}

const routes: RouteRecordRaw[] = [
  { path: '/login', component: () => import('@/views/LoginView.vue'), meta: { public: true, title: 'Sign in' } },
  { path: '/sso-callback', component: () => import('@/views/SsoCallback.vue'), meta: { public: true } },
  { path: '/', redirect: '/programs' },
  { path: '/programs', component: () => import('@/views/ProgramsView.vue'), meta: { title: 'Programs' } },
  { path: '/portfolio', component: () => import('@/views/PortfolioView.vue'), meta: { title: 'Portfolio' } },
  { path: '/alerts', component: () => import('@/views/AlertsView.vue'), meta: { title: 'Alerts' } },
  { path: '/account', component: () => import('@/views/AccountView.vue'), meta: { title: 'My account' } },
  { path: '/admin/users', component: () => import('@/views/admin/AdminUsers.vue'), meta: { role: 'admin', title: 'Users' } },
  { path: '/admin/organisation', component: () => import('@/views/admin/AdminOrganisation.vue'), meta: { role: 'admin', title: 'Organisation' } },
  { path: '/admin/alert-rules', component: () => import('@/views/admin/AlertRules.vue'), meta: { role: 'admin', title: 'Alert rules' } },
  { path: '/admin/audit', component: () => import('@/views/admin/AuditView.vue'), meta: { role: 'admin', title: 'Audit log' } },
  { path: '/admin/ai-logs', component: () => import('@/views/admin/AiLogs.vue'), meta: { role: 'admin', title: 'AI call log' } },
  { path: '/platform/tenants', component: () => import('@/views/admin/PlatformTenants.vue'), meta: { role: 'admin', platform: true, title: 'Tenants' } },
  {
    path: '/p/:pid',
    component: () => import('@/views/ProgramLayout.vue'),
    children: [
      { path: '', redirect: (to) => `/p/${to.params.pid}/overview` },
      { path: 'overview', name: 'overview', component: () => import('@/views/ExecutiveOverview.vue'), meta: { title: 'Executive Overview' } },
      { path: 'tracks', component: () => import('@/views/DeliveryTracks.vue'), meta: { title: 'Delivery Tracks' } },
      { path: 'milestones', component: () => import('@/views/MilestonesView.vue'), meta: { title: 'Milestones' } },
      { path: 'timeline', component: () => import('@/views/TimelineView.vue'), meta: { title: 'Timeline' } },
      { path: 'decisions', component: () => import('@/views/SupportDecisions.vue'), meta: { title: 'Support & Decisions' } },
      { path: 'risks', component: () => import('@/views/RiskRegister.vue'), meta: { title: 'Risk Register' } },
      { path: 'attention', component: () => import('@/views/AttentionView.vue'), meta: { title: 'Attention' } },
      { path: 'changes', component: () => import('@/views/WhatChanged.vue'), meta: { title: 'What Changed' } },
      { path: 'kpis', component: () => import('@/views/KpiCatalogue.vue'), meta: { title: 'KPI Catalogue' } },
      { path: 'insights', component: () => import('@/views/InsightsView.vue'), meta: { title: 'AI Insights' } },
      { path: 'snapshots', component: () => import('@/views/SnapshotsView.vue'), meta: { title: 'Snapshots' } },
      { path: 'mapping', component: () => import('@/views/MappingWizard.vue'), meta: { role: 'admin', title: 'Mapping' } },
      { path: 'settings', component: () => import('@/views/ProgramSettings.vue'), meta: { role: 'admin', title: 'Program settings' } },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/programs' },
]

export const router = createRouter({ history: createWebHistory(), routes, scrollBehavior: () => ({ top: 0 }) })

router.beforeEach(async (to) => {
  const auth = useAuth()
  if (!auth.ready) await auth.load()
  if (to.meta.public) return true
  if (!auth.isAuthenticated) return { path: '/login', query: to.fullPath !== '/programs' ? { next: to.fullPath } : {} }
  if (to.meta.role && !auth.can(to.meta.role)) return '/programs'
  if (to.meta.platform && !auth.user?.is_platform_admin) return '/programs'
  return true
})
router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · PMA` : 'Project Management Accelerator'
  requestAnimationFrame(() => document.getElementById('main')?.focus({ preventScroll: true }))
})
