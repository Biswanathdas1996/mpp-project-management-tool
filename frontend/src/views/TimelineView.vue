<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import GanttChart from '@/components/GanttChart.vue'
import { useDash } from '@/composables/useDash'

const { t } = useI18n()
const { d, drillMilestone } = useDash()
</script>

<template>
  <div v-if="d">
    <div class="page-head"><div><h1>{{ t('nav.timeline') }}</h1><p>Monthly view of every milestone with progress fill, plan-to-date marker and today line. Click a bar to see its tasks.</p></div></div>
    <section class="card">
      <GanttChart :gantt="d.gantt" @open="(id) => drillMilestone(id)" />
    </section>
  </div>
</template>
