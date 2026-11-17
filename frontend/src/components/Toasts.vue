<script setup lang="ts">
import { useUi } from '@/stores/ui'
import Icon from './Icon.vue'
const ui = useUi()
const ICON = { ok: 'check', bad: 'octagon', warn: 'alert', info: 'info' } as const
function dismiss(id: number) {
  ui.toasts = ui.toasts.filter((x) => x.id !== id)
}
</script>

<template>
  <div class="toasts" role="status" aria-live="polite">
    <TransitionGroup name="toast">
      <div v-for="t in ui.toasts" :key="t.id" class="toast" :class="t.kind">
        <Icon :name="ICON[t.kind]" :size="18" />
        <span>{{ t.text }}</span>
        <button class="close" aria-label="Dismiss" @click="dismiss(t.id)"><Icon name="x" :size="14" /></button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toasts { position: fixed; inset-block-end: 20px; inset-inline-end: 20px; display: flex; flex-direction: column; gap: 10px; z-index: 80; width: min(400px, calc(100vw - 32px)); pointer-events: none; }
.toast {
  display: flex; align-items: flex-start; gap: 10px; padding: 12px 12px 12px 14px; border-radius: 12px; font-size: 13.5px; line-height: 1.45;
  background: var(--surface); color: var(--text); border: 1px solid var(--border); box-shadow: var(--shadow-lg);
  border-inline-start: 3px solid var(--info); pointer-events: auto;
}
.toast > span { flex: 1; min-width: 0; padding-top: 1px; }
.toast.ok { border-inline-start-color: var(--ok); }
.toast.ok > .icon { color: var(--ok); }
.toast.bad { border-inline-start-color: var(--bad); }
.toast.bad > .icon { color: var(--bad); }
.toast.warn { border-inline-start-color: var(--warn); }
.toast.warn > .icon { color: var(--warn); }
.toast.info > .icon { color: var(--info); }
.close { background: none; border: 0; padding: 2px; color: var(--muted); cursor: pointer; border-radius: 6px; display: grid; place-items: center; }
.close:hover { background: var(--surface-3); color: var(--text); }
.toast-enter-active, .toast-leave-active { transition: opacity 0.2s var(--ease), transform 0.2s var(--ease); }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateY(8px); }
</style>
