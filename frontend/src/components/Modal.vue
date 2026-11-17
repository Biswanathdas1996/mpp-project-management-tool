<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import Icon from './Icon.vue'

withDefaults(defineProps<{ title: string; wide?: boolean }>(), { wide: false })
const emit = defineEmits<{ (e: 'close'): void }>()
const panel = ref<HTMLElement>()
let previous: HTMLElement | null = null
const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
  if (e.key === 'Tab' && panel.value) {
    const f = panel.value.querySelectorAll<HTMLElement>(FOCUSABLE)
    if (!f.length) return
    const first = f[0]
    const last = f[f.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      last.focus()
      e.preventDefault()
    } else if (!e.shiftKey && document.activeElement === last) {
      first.focus()
      e.preventDefault()
    }
  }
}
onMounted(async () => {
  previous = document.activeElement as HTMLElement
  document.addEventListener('keydown', onKey)
  await nextTick()
  panel.value?.querySelector<HTMLElement>('input, select, textarea')?.focus()
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKey)
  previous?.focus?.()
})
</script>

<template>
  <div class="backdrop" @mousedown.self="emit('close')">
    <section ref="panel" class="modal card" :class="{ wide }" role="dialog" aria-modal="true" :aria-label="title">
      <header class="card-head">
        <h2>{{ title }}</h2>
        <button type="button" class="btn btn-ghost btn-sm btn-icon" aria-label="Close" @click="emit('close')"><Icon name="x" /></button>
      </header>
      <div class="modal-body"><slot /></div>
      <footer v-if="$slots.footer" class="modal-foot"><slot name="footer" /></footer>
    </section>
  </div>
</template>

<style scoped>
.backdrop { position: fixed; inset: 0; background: rgb(10 12 18 / 0.45); backdrop-filter: blur(4px); -webkit-backdrop-filter: blur(4px); display: grid; place-items: center; z-index: 60; padding: 16px; animation: fade 0.18s var(--ease); }
.modal { width: min(640px, 100%); max-height: calc(100vh - 32px); display: flex; flex-direction: column; box-shadow: var(--shadow-lg); padding: 0; border-radius: 16px; animation: rise 0.22s var(--ease); }
.modal > .card-head { padding: 18px 22px 0; margin-bottom: 16px; }
.modal.wide { width: min(1180px, 100%); }
.modal-body { overflow: auto; padding: 0 22px 20px; }
.modal-foot { display: flex; justify-content: flex-end; gap: 8px; padding: 14px 22px; border-top: 1px solid var(--border); background: var(--surface-2); border-radius: 0 0 16px 16px; }
@keyframes fade { from { opacity: 0; } }
@keyframes rise { from { opacity: 0; transform: translateY(8px) scale(0.985); } }
</style>
