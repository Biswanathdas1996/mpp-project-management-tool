import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/client'
import { useAuth } from '@/stores/auth'
import { useProgram } from '@/stores/program'
import { useUi } from '@/stores/ui'

/** CRUD + review for governance data (risks | decisions | attention). */
export function useGovernance<T extends { id?: number }>(kind: 'risks' | 'decisions' | 'attention') {
  const store = useProgram()
  const ui = useUi()
  const auth = useAuth()
  const { t } = useI18n()
  const items = ref<T[]>([])
  const loading = ref(false)
  const editing = ref<Partial<T> | null>(null)
  const saving = ref(false)
  const base = computed(() => `/programs/${store.program?.id}/${kind}`)

  async function load() {
    if (!store.program) return
    loading.value = true
    try {
      items.value = await api.get<T[]>(base.value)
    } catch (e) {
      ui.error(e)
    } finally {
      loading.value = false
    }
  }
  async function save(payload: Record<string, unknown>) {
    saving.value = true
    try {
      const clean = Object.fromEntries(Object.entries(payload).map(([k, v]) => [k, v === '' ? null : v]))
      if (editing.value?.id) await api.put(`${base.value}/${editing.value.id}`, clean)
      else await api.post(base.value, clean)
      ui.toast('Saved')
      editing.value = null
      await Promise.all([load(), store.loadDashboard(true)])
    } catch (e) {
      ui.error(e)
    } finally {
      saving.value = false
    }
  }
  async function review(item: T, action: 'approve' | 'reject') {
    try {
      await api.post(`${base.value}/${item.id}/review`, { action })
      ui.toast(action === 'approve' ? 'Approved' : 'Rejected')
      await Promise.all([load(), store.loadDashboard(true)])
    } catch (e) {
      ui.error(e)
    }
  }
  async function remove(item: T) {
    if (!confirm(t('common.confirmDelete'))) return
    try {
      await api.del(`${base.value}/${item.id}`)
      await Promise.all([load(), store.loadDashboard(true)])
    } catch (e) {
      ui.error(e)
    }
  }
  onMounted(load)
  return { items, loading, editing, saving, load, save, review, remove, canEdit: computed(() => auth.isEditor) }
}
