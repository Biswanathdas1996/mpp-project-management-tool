import { defineStore } from 'pinia'
import { ref } from 'vue'

export type Theme = 'light' | 'dark'
export interface Toast { id: number; kind: 'ok' | 'bad' | 'info' | 'warn'; text: string }
export interface DrillRequest { snapshotId: number; title?: string; kpi?: string; trackId?: number; milestoneId?: number; uids?: number[] }

function initialTheme(): Theme {
  try {
    const t = localStorage.getItem('pma.theme')
    if (t === 'light' || t === 'dark') return t
  } catch {
    /* ignore */
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export const useUi = defineStore('ui', () => {
  const theme = ref<Theme>(initialTheme())
  const toasts = ref<Toast[]>([])
  const drill = ref<DrillRequest | null>(null)
  let seq = 0

  function applyTheme() {
    document.documentElement.dataset.theme = theme.value
  }
  function toggleTheme() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
    try {
      localStorage.setItem('pma.theme', theme.value)
    } catch {
      /* ignore */
    }
    applyTheme()
  }
  function toast(text: string, kind: Toast['kind'] = 'ok', ms = 4500) {
    const id = ++seq
    toasts.value.push({ id, kind, text })
    setTimeout(() => (toasts.value = toasts.value.filter((t) => t.id !== id)), ms)
  }
  function error(e: unknown) {
    toast(e instanceof Error ? e.message : String(e), 'bad', 7000)
  }
  function openDrill(req: DrillRequest) {
    drill.value = req
  }
  function closeDrill() {
    drill.value = null
  }

  return { theme, toasts, drill, applyTheme, toggleTheme, toast, error, openDrill, closeDrill }
})
