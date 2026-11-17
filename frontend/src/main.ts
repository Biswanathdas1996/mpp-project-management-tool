import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from './App.vue'
import { setUnauthorizedHandler } from './api/client'
import { applyLocale, i18n, type Locale } from './i18n'
import { router } from './router'
import { useAuth } from './stores/auth'
import { useUi } from './stores/ui'
import './styles/main.css'

const app = createApp(App)
app.use(createPinia())
app.use(i18n)
app.use(router)

useUi().applyTheme()
applyLocale(i18n.global.locale.value as Locale)
setUnauthorizedHandler(() => {
  useAuth().clear()
  if (router.currentRoute.value.path !== '/login') router.push({ path: '/login', query: { next: router.currentRoute.value.fullPath } })
})

app.mount('#app')
