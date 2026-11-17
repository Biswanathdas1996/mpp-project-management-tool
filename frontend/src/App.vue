<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import DrillDrawer from '@/components/DrillDrawer.vue'
import Toasts from '@/components/Toasts.vue'
import TopBar from '@/components/TopBar.vue'
import { useAuth } from '@/stores/auth'

const { t } = useI18n()
const route = useRoute()
const auth = useAuth()
const chrome = computed(() => auth.isAuthenticated && !route.meta.public)
</script>

<template>
  <a class="skip-link" href="#main">{{ t('app.skip') }}</a>
  <TopBar v-if="chrome" />
  <RouterView />
  <DrillDrawer />
  <Toasts />
</template>
