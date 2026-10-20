<script setup>
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { LayoutDashboard, Sparkles, Library, Settings, Menu, X, KeyRound, SlidersHorizontal } from 'lucide-vue-next'
import { auth, setToken } from './api'
import { toasts } from './utils'

const route = useRoute()
const open = ref(false)
const tokenInput = ref('')
watch(() => route.fullPath, () => { open.value = false })

const nav = [
  { to: '/', label: 'Painel', icon: LayoutDashboard },
  { to: '/novo', label: 'Criar Shorts', icon: Sparkles },
  { to: '/biblioteca', label: 'Biblioteca', icon: Library },
  { to: '/preferencias', label: 'Preferências', icon: SlidersHorizontal },
  { to: '/configuracoes', label: 'Configurações', icon: Settings },
]

function isActive(to) {
  return to === '/' ? route.path === '/' : route.path.startsWith(to)
}

function saveToken() {
  setToken(tokenInput.value.trim())
  auth.required = false
  location.reload()
}
</script>

<template>
  <div class="min-h-screen bg-ink-950">
    <!-- brilho de fundo -->
    <div class="pointer-events-none fixed inset-0 overflow-hidden">
      <div class="absolute -top-40 left-1/3 h-96 w-96 rounded-full bg-brand-600/10 blur-3xl"></div>
      <div class="absolute top-1/2 -right-20 h-80 w-80 rounded-full bg-sky-brand/10 blur-3xl"></div>
    </div>

    <!-- barra superior (mobile) -->
    <header class="sticky top-0 z-30 flex items-center justify-between border-b border-ink-800 bg-ink-950/90 px-4 py-3 backdrop-blur lg:hidden">
      <RouterLink to="/" class="flex items-center gap-2">
        <img src="/favicon.svg" class="h-8 w-8" alt="" />
        <span class="font-display text-lg font-semibold">ClipFlow <span class="text-brand-400">Studio</span></span>
      </RouterLink>
      <button class="btn-ghost p-2" @click="open = !open" :aria-label="open ? 'Fechar menu' : 'Abrir menu'">
        <component :is="open ? X : Menu" class="h-5 w-5" />
      </button>
    </header>

    <!-- barra lateral -->
    <aside
      class="fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-ink-800 bg-ink-900/95 px-4 py-6 backdrop-blur transition-transform lg:translate-x-0"
      :class="open ? 'translate-x-0' : '-translate-x-full'"
    >
      <RouterLink to="/" class="mb-10 flex items-center gap-3 px-2">
        <img src="/favicon.svg" class="h-9 w-9" alt="" />
        <div>
          <div class="font-display text-lg font-semibold leading-tight text-white">ClipFlow</div>
          <div class="text-xs font-medium tracking-[0.2em] text-brand-400">STUDIO</div>
        </div>
      </RouterLink>
      <nav class="space-y-1">
        <RouterLink
          v-for="item in nav" :key="item.to" :to="item.to"
          class="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition"
          :class="isActive(item.to) ? 'bg-brand-500/15 text-white ring-1 ring-brand-500/30' : 'text-ink-300 hover:bg-ink-800 hover:text-white'"
        >
          <component :is="item.icon" class="h-4.5 w-4.5" :class="isActive(item.to) ? 'text-brand-400' : ''" />
          {{ item.label }}
        </RouterLink>
      </nav>
      <div class="mt-auto rounded-xl border border-ink-700 bg-ink-850 p-3 text-xs leading-relaxed text-ink-400">
        Processamento 100% local. Use apenas conteúdo próprio ou com autorização do titular.
      </div>
    </aside>
    <div v-if="open" class="fixed inset-0 z-30 bg-black/60 lg:hidden" @click="open = false"></div>

    <main class="relative lg:pl-64">
      <div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-10 lg:py-10">
        <RouterView v-slot="{ Component }">
          <component :is="Component" />
        </RouterView>
      </div>
    </main>

    <!-- token de acesso -->
    <div v-if="auth.required" class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <form class="card w-full max-w-sm p-6" @submit.prevent="saveToken">
        <div class="mb-4 flex items-center gap-2 text-white"><KeyRound class="h-5 w-5 text-brand-400" /> Token de acesso</div>
        <p class="mb-4 text-sm text-ink-400">Este servidor exige o token definido em <code>config.toml</code>.</p>
        <input v-model="tokenInput" type="password" class="input mb-4" placeholder="Token" autofocus />
        <button class="btn-primary w-full">Entrar</button>
      </form>
    </div>

    <!-- notificações -->
    <div class="fixed bottom-4 right-4 z-50 flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2">
      <div
        v-for="t in toasts" :key="t.id"
        class="animate-fade-in rounded-xl border px-4 py-3 text-sm shadow-xl backdrop-blur"
        :class="{
          'border-red-500/40 bg-red-950/90 text-red-100': t.tone === 'error',
          'border-emerald-500/40 bg-emerald-950/90 text-emerald-100': t.tone === 'success',
          'border-ink-600 bg-ink-800/95 text-ink-100': t.tone === 'info',
        }"
        role="status"
      >{{ t.message }}</div>
    </div>
  </div>
</template>
