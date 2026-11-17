import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, qs } from '@/api/client'
import type { Dashboard, Program, Snapshot } from '@/api/types'

/** Current program context: program, its snapshots, selected snapshot and the dashboard payload. */
export const useProgram = defineStore('program', () => {
  const program = ref<Program | null>(null)
  const snapshots = ref<Snapshot[]>([])
  const selectedSnapshotId = ref<number | null>(null)
  const dashboard = ref<Dashboard | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const readySnapshots = computed(() => snapshots.value.filter((s) => s.status === 'ready'))
  const snapshotId = computed(() => selectedSnapshotId.value ?? dashboard.value?.snapshot.id ?? null)

  async function open(programId: number) {
    if (program.value?.id !== programId) {
      program.value = null
      dashboard.value = null
      selectedSnapshotId.value = null
      snapshots.value = []
    }
    program.value = await api.get<Program>(`/programs/${programId}`)
    await refreshSnapshots()
  }

  async function refreshSnapshots() {
    if (!program.value) return
    snapshots.value = await api.get<Snapshot[]>(`/programs/${program.value.id}/snapshots`)
  }

  async function loadDashboard(force = false) {
    if (!program.value) return
    if (!force && dashboard.value && dashboard.value.program_id === program.value.id &&
        (selectedSnapshotId.value === null || dashboard.value.snapshot.id === selectedSnapshotId.value)) return
    if (!program.value.latest_snapshot && selectedSnapshotId.value === null) {
      // nothing processed yet (or it just finished): refresh before asking for a dashboard
      program.value = await api.get<Program>(`/programs/${program.value.id}`)
      if (!program.value.latest_snapshot) {
        dashboard.value = null
        error.value = 'No processed snapshot yet — upload a plan and approve the mapping.'
        return
      }
    }
    loading.value = true
    error.value = null
    try {
      dashboard.value = await api.get<Dashboard>(
        `/programs/${program.value.id}/dashboard${qs({ snapshot_id: selectedSnapshotId.value })}`,
      )
    } catch (e) {
      dashboard.value = null
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  async function selectSnapshot(id: number | null) {
    selectedSnapshotId.value = id
    await loadDashboard(true)
  }

  function reset() {
    program.value = null
    snapshots.value = []
    dashboard.value = null
    selectedSnapshotId.value = null
  }

  return { program, snapshots, readySnapshots, selectedSnapshotId, snapshotId, dashboard, loading, error, open,
    refreshSnapshots, loadDashboard, selectSnapshot, reset }
})
