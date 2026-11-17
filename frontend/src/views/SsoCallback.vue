<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'

const auth = useAuth()
const router = useRouter()
const error = ref('')
onMounted(async () => {
  const token = new URLSearchParams(window.location.hash.slice(1)).get('token')
  history.replaceState(null, '', window.location.pathname) // drop the token from the URL
  if (!token) {
    error.value = 'Single sign-on did not return a session.'
    return
  }
  await auth.acceptToken(token)
  if (auth.isAuthenticated) router.replace('/programs')
  else error.value = 'Single sign-on session could not be verified.'
})
</script>

<template>
  <main id="main" class="page empty">
    <p v-if="!error"><span class="spinner" /> Signing you in…</p>
    <div v-else class="alert bad">{{ error }} <RouterLink to="/login">Back to sign in</RouterLink></div>
  </main>
</template>
