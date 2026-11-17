import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, getToken, setToken } from '@/api/client'
import type { Role, User } from '@/api/types'
import { applyLocale } from '@/i18n'

const RANK: Record<Role, number> = { super_viewer: 1, pmo_editor: 2, admin: 3 }

export const useAuth = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const ready = ref(false)

  const isAuthenticated = computed(() => !!user.value)
  const can = (min: Role) => !!user.value && RANK[user.value.role] >= RANK[min]
  const isAdmin = computed(() => can('admin'))
  const isEditor = computed(() => can('pmo_editor'))

  async function load() {
    if (!getToken()) {
      ready.value = true
      return
    }
    try {
      user.value = await api.get<User>('/auth/me')
      if (user.value.locale) applyLocale(user.value.locale)
    } catch {
      setToken(null)
      user.value = null
    } finally {
      ready.value = true
    }
  }

  async function login(email: string, password: string) {
    const res = await api.post<{ access_token: string; user: User }>('/auth/login', { email, password })
    setToken(res.access_token)
    user.value = res.user
  }

  async function acceptToken(token: string) {
    setToken(token)
    await load()
  }

  async function logout() {
    try {
      await api.post('/auth/logout')
    } catch {
      /* token may already be invalid */
    }
    setToken(null)
    user.value = null
  }

  function clear() {
    setToken(null)
    user.value = null
  }

  return { user, ready, isAuthenticated, isAdmin, isEditor, can, load, login, logout, acceptToken, clear }
})
