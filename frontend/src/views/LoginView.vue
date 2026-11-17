<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import { applyLocale } from '@/i18n'
import { useAuth } from '@/stores/auth'
import Icon from '@/components/Icon.vue'

const { t, locale } = useI18n()
const auth = useAuth()
const router = useRouter()
const route = useRoute()
const email = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)
const sso = ref(false)

onMounted(async () => {
  try {
    sso.value = (await api.get<{ enabled: boolean }>('/auth/oidc/config')).enabled
  } catch {
    sso.value = false
  }
})
async function submit() {
  busy.value = true
  error.value = ''
  try {
    await auth.login(email.value, password.value)
    router.replace((route.query.next as string) || '/programs')
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main id="main" class="login-wrap">
    <aside class="brand-panel" aria-hidden="true">
      <div class="brand-top">
        <img src="/favicon.svg" alt="" width="36" height="36" />
        <span>{{ t('app.name') }}</span>
      </div>
      <div class="brand-copy">
        <h2>Executive clarity for every programme.</h2>
        <p>Turn MS Project plans into live dashboards, governance registers and AI-assisted insights, all traceable to the underlying tasks.</p>
        <ul>
          <li><Icon name="chart" :size="18" /> KPIs that drill down to every task</li>
          <li><Icon name="shield" :size="18" /> Risks, decisions and attention items in one place</li>
          <li><Icon name="sparkles" :size="18" /> AI summaries grounded in plan data</li>
        </ul>
      </div>
      <div class="glow" />
    </aside>
    <section class="form-panel" aria-labelledby="lt">
      <div class="form-top">
        <img class="mobile-logo" src="/favicon.svg" alt="" width="32" height="32" />
        <span class="spacer" />
        <button class="btn btn-ghost btn-sm" @click="applyLocale(locale === 'ar' ? 'en' : 'ar')"><Icon name="globe" />{{ t('header.language') }}</button>
      </div>
      <div class="login">
        <h1 id="lt">{{ t('login.title') }}</h1>
        <p class="muted lead">{{ t('app.name') }}</p>
        <form class="stack form" @submit.prevent="submit">
          <label class="field">{{ t('login.email') }}<input v-model="email" class="input" type="email" autocomplete="username" placeholder="name@company.com" required /></label>
          <label class="field">{{ t('login.password') }}<input v-model="password" class="input" type="password" autocomplete="current-password" required /></label>
          <p v-if="error" class="alert bad" role="alert">{{ error }}</p>
          <button class="btn btn-primary submit" :disabled="busy"><span v-if="busy" class="spinner" /> {{ t('login.submit') }}</button>
        </form>
        <template v-if="sso">
          <p class="or muted small"><span>{{ t('login.or') }}</span></p>
          <a class="btn submit" href="/api/auth/oidc/login">{{ t('login.sso') }}</a>
        </template>
      </div>
    </section>
  </main>
</template>

<style scoped>
.login-wrap { min-height: 100vh; display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr); background: var(--surface); }
.brand-panel {
  position: relative; overflow: hidden; display: flex; flex-direction: column; justify-content: space-between; padding: 40px 48px;
  color: #eef0ff; background: linear-gradient(150deg, #1e1b4b 0%, #312e81 45%, #3730a3 100%);
}
.brand-panel::before {
  content: ''; position: absolute; inset: 0; opacity: 0.35;
  background-image: linear-gradient(rgb(255 255 255 / 0.06) 1px, transparent 1px), linear-gradient(90deg, rgb(255 255 255 / 0.06) 1px, transparent 1px);
  background-size: 36px 36px; mask-image: radial-gradient(ellipse at 30% 40%, #000 20%, transparent 75%);
}
.glow { position: absolute; width: 520px; height: 520px; border-radius: 50%; inset-inline-end: -160px; bottom: -200px;
  background: radial-gradient(circle, rgb(56 189 248 / 0.35), transparent 65%); filter: blur(10px); }
.brand-top { position: relative; display: flex; align-items: center; gap: 12px; font-weight: 650; font-size: 15px; }
.brand-top img { border-radius: 9px; box-shadow: 0 0 0 1px rgb(255 255 255 / 0.15); }
.brand-copy { position: relative; max-width: 460px; }
.brand-copy h2 { color: #fff; font-size: 32px; line-height: 1.15; font-weight: 700; letter-spacing: -0.03em; }
.brand-copy p { margin-top: 14px; color: #c7cbf5; font-size: 15px; line-height: 1.6; }
.brand-copy ul { list-style: none; padding: 0; margin: 28px 0 0; display: flex; flex-direction: column; gap: 14px; }
.brand-copy li { display: flex; align-items: center; gap: 12px; color: #e0e3ff; font-size: 14px; }
.brand-copy li .icon { padding: 7px; width: 32px; height: 32px; border-radius: 9px; background: rgb(255 255 255 / 0.1); box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.12); }
.form-panel { display: flex; flex-direction: column; padding: 24px 32px; background: var(--surface); }
.form-top { display: flex; align-items: center; }
.mobile-logo { display: none; border-radius: 8px; }
.login { width: min(380px, 100%); margin: auto; padding: 32px 0; }
.lead { margin-top: 6px; }
.form { margin-top: 28px; gap: 16px; }
.submit { width: 100%; height: 42px; font-size: 14px; }
.or { display: flex; align-items: center; gap: 12px; margin: 20px 0 14px; }
.or::before, .or::after { content: ''; flex: 1; height: 1px; background: var(--border); }
@media (max-width: 880px) {
  .login-wrap { grid-template-columns: 1fr; }
  .brand-panel { display: none; }
  .mobile-logo { display: block; }
  .form-panel { padding: 16px; }
}
</style>
