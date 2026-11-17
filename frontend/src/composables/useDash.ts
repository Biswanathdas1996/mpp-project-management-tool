import { computed, onMounted } from 'vue'
import { useProgram } from '@/stores/program'
import { useUi } from '@/stores/ui'

/** Access the current dashboard payload and open drill-downs on it. */
export function useDash() {
  const store = useProgram()
  const ui = useUi()
  onMounted(() => {
    if (store.program) store.loadDashboard()
  })
  const d = computed(() => store.dashboard)
  const sid = computed(() => store.dashboard?.snapshot.id ?? 0)
  return {
    store,
    d,
    sid,
    drillKpi: (kpi: string, title?: string) => ui.openDrill({ snapshotId: sid.value, kpi, title }),
    drillTrack: (trackId: number, title?: string) => ui.openDrill({ snapshotId: sid.value, trackId, title }),
    drillMilestone: (milestoneId: number, title?: string) => ui.openDrill({ snapshotId: sid.value, milestoneId, title }),
    drillUids: (uids: number[], title: string) => ui.openDrill({ snapshotId: sid.value, uids, title }),
  }
}
