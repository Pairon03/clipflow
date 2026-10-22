<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { Search, Download, CheckSquare, Square, Clapperboard, Youtube } from 'lucide-vue-next'
import { api, fileUrl } from '../api'
import { toast } from '../utils'
import ClipResult from '../components/ClipResult.vue'
import PublishDialog from '../components/PublishDialog.vue'

const clips = ref([])
const projects = ref([])
const loading = ref(true)
const q = ref('')
const projectId = ref('')
const selected = ref(new Set())
let t

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams()
    if (q.value) params.set('q', q.value)
    if (projectId.value) params.set('project_id', projectId.value)
    clips.value = await api(`/api/library?${params}`)
    const ids = new Set(clips.value.map((c) => c.id))
    selected.value = new Set([...selected.value].filter((id) => ids.has(id)))
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    loading.value = false
  }
}
watch(q, () => { clearTimeout(t); t = setTimeout(load, 300) })
watch(projectId, load)
onMounted(async () => {
  load()
  projects.value = await api('/api/projects').catch(() => [])
})

function toggle(id) {
  const s = new Set(selected.value)
  s.has(id) ? s.delete(id) : s.add(id)
  selected.value = s
}
const allSelected = computed(() => clips.value.length && selected.value.size === clips.value.length)
function toggleAll() {
  selected.value = allSelected.value ? new Set() : new Set(clips.value.map((c) => c.id))
}
const publishing = ref(null)
function openPublish() {
  publishing.value = clips.value.filter((c) => selected.value.has(c.id))
}
function published() {
  publishing.value = null
  selected.value = new Set()
  load()
}
const zipUrl = computed(() => fileUrl(`/api/library/zip?ids=${[...(selected.value.size ? selected.value : clips.value.map((c) => c.id))].join(',')}`))
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 class="page-title">Biblioteca</h1>
        <p class="mt-1 text-ink-400">Todos os Shorts produzidos, prontos para revisão e download.</p>
      </div>
      <div v-if="clips.length" class="flex flex-wrap gap-2">
        <button class="btn-secondary" :disabled="!selected.size" :title="selected.size ? '' : 'Marque os Shorts que quer publicar'" @click="openPublish"><Youtube class="h-4 w-4 text-red-400" /> Publicar {{ selected.size || '' }} no YouTube</button>
        <a :href="zipUrl" class="btn-primary"><Download class="h-4 w-4" /> {{ selected.size ? `Baixar ${selected.size} selecionados` : 'Baixar todos' }} (ZIP)</a>
      </div>
    </div>

    <div class="card flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
      <div class="relative flex-1">
        <Search class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-500" />
        <input v-model="q" class="input pl-9" placeholder="Buscar por título, fala ou projeto" aria-label="Buscar" />
      </div>
      <select v-model="projectId" class="input sm:w-64" aria-label="Filtrar por projeto">
        <option value="">Todos os projetos</option>
        <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>
      <button v-if="clips.length" class="btn-ghost" @click="toggleAll"><component :is="allSelected ? CheckSquare : Square" class="h-4 w-4" /> Selecionar todos</button>
    </div>

    <div v-if="loading && !clips.length" class="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
      <div v-for="i in 4" :key="i" class="card aspect-[9/16] animate-pulse"></div>
    </div>
    <div v-else-if="!clips.length" class="card flex flex-col items-center p-14 text-center text-ink-400">
      <Clapperboard class="mb-3 h-10 w-10 text-ink-600" />
      <p>Nenhum Short encontrado.</p>
      <RouterLink to="/novo" class="btn-primary mt-5">Criar novos Shorts</RouterLink>
    </div>
    <div v-else class="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
      <div v-for="c in clips" :key="c.id" class="relative">
        <button class="absolute left-3 top-10 z-10 rounded-md bg-black/70 p-1 text-white backdrop-blur" @click="toggle(c.id)" :aria-label="selected.has(c.id) ? 'Desmarcar' : 'Marcar'">
          <component :is="selected.has(c.id) ? CheckSquare : Square" class="h-4 w-4" :class="selected.has(c.id) ? 'text-brand-300' : ''" />
        </button>
        <ClipResult :clip="c" show-project @changed="load" @deleted="load" @publish="publishing = [c]" />
      </div>
    </div>
    <PublishDialog v-if="publishing" :clips="publishing" @close="publishing = null" @done="published" />
  </div>
</template>
