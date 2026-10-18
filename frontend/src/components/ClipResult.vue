<script setup>
import { onMounted, ref } from 'vue'
import { Download, Copy, Trash2, FileText, Pencil, Save, Clapperboard, ExternalLink } from 'lucide-vue-next'
import { api, fileUrl, getMeta } from '../api'
import { fmtDuration, fmtDate, fmtBytes, toast } from '../utils'

const props = defineProps({ clip: Object, showProject: Boolean })
const emit = defineEmits(['changed', 'deleted'])

const editing = ref(false)
const titles = ref([...(props.clip.titles || [])])
const description = ref(props.clip.description)

const concatAvailable = ref(false)
const concatBusy = ref(false)
onMounted(async () => {
  concatAvailable.value = !!(await getMeta().catch(() => ({}))).concat_available
})
async function toConcat() {
  concatBusy.value = true
  try {
    await api(`/api/clips/${props.clip.id}/concat`, { method: 'POST' })
    toast('Preparando projeto no Concat… acompanhe na página do projeto', 'success')
    emit('changed')
  } catch (e) { toast(e.message, 'error', 6000) } finally { concatBusy.value = false }
}
async function openConcat() {
  try {
    await api(`/api/clips/${props.clip.id}/concat/open`, { method: 'POST' })
    toast('Abrindo no Concat…', 'success')
  } catch (e) { toast(e.message, 'error', 6000) }
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast('Copiado!', 'success', 1800) } catch { toast('Não foi possível copiar', 'error') }
}
async function save() {
  try {
    await api(`/api/clips/${props.clip.id}`, { method: 'PATCH', body: { titles: titles.value, description: description.value } })
    editing.value = false
    toast('Textos salvos', 'success')
    emit('changed')
  } catch (e) { toast(e.message, 'error') }
}
async function remove() {
  if (!confirm('Excluir este Short? O arquivo de vídeo será apagado.')) return
  try {
    await api(`/api/clips/${props.clip.id}`, { method: 'DELETE' })
    toast('Short excluído', 'success')
    emit('deleted', props.clip.id)
  } catch (e) { toast(e.message, 'error') }
}
</script>

<template>
  <article class="card flex flex-col overflow-hidden">
    <div class="relative aspect-[9/16] bg-black">
      <video :src="fileUrl(`/api/clips/${clip.id}/video`)" :poster="clip.has_thumb ? fileUrl(`/api/clips/${clip.id}/thumb`) : undefined"
             controls preload="none" playsinline class="h-full w-full object-contain"></video>
      <span class="absolute left-2 top-2 rounded-md bg-black/70 px-2 py-0.5 text-xs font-medium text-white backdrop-blur">{{ fmtDuration(clip.duration) }}</span>
      <span class="absolute right-2 top-2 rounded-md bg-black/70 px-2 py-0.5 text-xs font-medium text-brand-200 backdrop-blur" title="Pontuação editorial (estimativa)">{{ Math.round(clip.score) }}</span>
    </div>
    <div class="flex flex-1 flex-col gap-3 p-4">
      <div v-if="showProject" class="truncate text-xs text-ink-500">
        <RouterLink :to="`/projetos/${clip.project_id}`" class="hover:text-brand-300">{{ clip.project_name }}</RouterLink> · {{ fmtDate(clip.rendered_at) }}
      </div>
      <div v-if="clip.render_info?.stale" class="rounded-lg bg-amber-500/10 px-2 py-1 text-xs text-amber-300">Há alterações ainda não renderizadas</div>

      <div v-if="!editing" class="space-y-1.5">
        <div class="text-[11px] font-medium uppercase tracking-wide text-ink-500">Títulos sugeridos</div>
        <button v-for="t in clip.titles" :key="t" class="group flex w-full items-start gap-2 rounded-lg px-2 py-1 text-left text-sm text-ink-100 hover:bg-ink-800" @click="copy(t)" title="Copiar">
          <span class="flex-1">{{ t }}</span><Copy class="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-500 opacity-0 group-hover:opacity-100" />
        </button>
      </div>
      <div v-else class="space-y-2">
        <input v-for="(t, i) in titles" :key="i" v-model="titles[i]" class="input py-1.5 text-sm" maxlength="100" />
        <textarea v-model="description" rows="5" class="input text-xs"></textarea>
      </div>

      <details v-if="!editing" class="text-xs text-ink-400">
        <summary class="cursor-pointer select-none text-ink-300">Descrição e hashtags</summary>
        <p class="mt-2 whitespace-pre-line">{{ clip.description }}</p>
        <button class="btn-ghost mt-1 px-2 py-1 text-xs" @click="copy(clip.description)"><Copy class="h-3 w-3" /> Copiar descrição</button>
      </details>

      <div class="mt-auto flex flex-wrap items-center gap-1.5 pt-2">
        <a :href="fileUrl(`/api/clips/${clip.id}/video?download=true`)" class="btn-primary flex-1 py-2 text-xs"><Download class="h-3.5 w-3.5" /> MP4</a>
        <a :href="fileUrl(`/api/clips/${clip.id}/srt`)" class="btn-secondary py-2 text-xs" title="Baixar legenda SRT"><FileText class="h-3.5 w-3.5" /> SRT</a>
        <button v-if="!editing" class="btn-ghost p-2" @click="editing = true" title="Editar textos" aria-label="Editar textos"><Pencil class="h-3.5 w-3.5" /></button>
        <button v-else class="btn-secondary p-2" @click="save" title="Salvar" aria-label="Salvar textos"><Save class="h-3.5 w-3.5" /></button>
        <button class="btn-ghost p-2 text-red-300 hover:text-red-200" @click="remove" title="Excluir" aria-label="Excluir"><Trash2 class="h-3.5 w-3.5" /></button>
      </div>
      <div v-if="concatAvailable" class="flex flex-wrap gap-1.5">
        <button class="btn-secondary flex-1 py-2 text-xs" :disabled="concatBusy" @click="toConcat" title="Cria um projeto do Concat com o vídeo sem legenda e as legendas como textos editáveis">
          <Clapperboard class="h-3.5 w-3.5" /> {{ clip.render_info?.concat_project ? 'Recriar no Concat' : 'Editar no Concat' }}
        </button>
        <button v-if="clip.render_info?.concat_project" class="btn-secondary py-2 text-xs" @click="openConcat" :title="clip.render_info.concat_project">
          <ExternalLink class="h-3.5 w-3.5" /> Abrir
        </button>
      </div>
      <div class="text-[11px] text-ink-500">{{ fmtBytes(clip.size_bytes) }} · 1080×1920 · H.264/AAC<span v-if="clip.render_info?.metadata_engine"> · textos: {{ clip.render_info.metadata_engine }}</span></div>
    </div>
  </article>
</template>
