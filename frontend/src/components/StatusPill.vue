<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { statusClass } from '@/format'

const props = defineProps<{ status: string | null | undefined }>()
const { t } = useI18n()
const label = computed(() => (props.status ? t(`status.${props.status}`) : '—'))
</script>

<template>
  <span class="pill" :class="statusClass(status)">{{ label }}</span>
</template>
