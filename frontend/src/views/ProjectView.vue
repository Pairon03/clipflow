<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft, XCircle, RotateCw, Trash2, Download, FileText, Wand2, RefreshCw, AlertTriangle, ScrollText, Youtube, Upload, ShieldCheck, Loader2 } from 'lucide-vue-next'
import { api, fileUrl } from '../api'
import { fmtDuration, fmtDate, fmtBytes, toast, ACTIVE } from '../utils'
import StatusBadge from '../components/StatusBadge.vue'
import ProgressBar from '../components/ProgressBar.vue'
import ClipEditor from '../components/ClipEditor.vue'
import ClipResult from '../components/ClipResult.vue'
import TitleStylePicker from '../components/TitleStylePicker.vue'

const props = defineProps({ id: String })
const router = useRouter()
const p = ref(null)
const error = ref('')
const log = ref('')
const showLog = ref(false)
const acting = ref(false)
const showAlternatives = ref(false)
const reselect = ref({ count: 5, min_duration: 30, max_duration: 60 })
const edit = ref({ pace: 'tiktok', speed: 1.0, cold_open: true, title_style: 'tweet', title_duration: 'inteiro' })
let timer

const active = computed(() => p.value && ACTIVE.includes(p.value.status))
const selected = computed(() => (p.value?.clips || []).filter((c) => c.selected))
const alternatives = computed(() => (p.value?.clips || []).filter((c) => !c.selected && c.status !== 'done'))
const done = computed(() => (p.value?.clips || []).filter((c) => c.status === 'done').sort((a, b) => a.start - b.start))
const canEdit = computed(() => p.value && !active.value && p.value.has_transcript)

async function load() {
  try {
    p.value = await api(`/api/projects/${props.id}`)
    error.value = ''
    if (showLog.value || p.value.status === 'failed') loadLog()
  } catch (e) {
    error.value = e.message
  }
}
async function loadLog() {
  log.value = await api(`/api/projects/${props.id}/log?lines=300`).catch(() => '')
}
watch(() => p.value?.options, (o) => {
  if (o) {
    reselect.value = { count: o.count, min_duration: o.min_duration, max_duration: o.max_duration }
    edit.value = { pace: o.pace || 'natural', speed: o.speed || 1.0, cold_open: !!o.cold_open,
      title_style: o.title_style || (o.theme === false ? 'nenhum' : 'tweet'), title_duration: o.title_duration || 'inteiro' }
  }
}, { immediate: true })

onMounted(() => {
  load()
  timer = setInterval(() => { if (active.value) load() }, 1500)
})
onUnmounted(() => clearInterval(timer))

async function act(fn, msg) {
  acting.value = true
  try {
    await fn()
    if (msg) toast(msg, 'success')
    await load()
  } catch (e) {
    toast(e.message, 'error', 6000)
  } finally {
    acting.value = false
  }
}
const cancel = () => act(() => api(`/api/projects/${props.id}/cancel`, { method: 'POST' }), 'Cancelamento solicitado')
const retry = () => act(() => api(`/api/projects/${props.id}/retry`, { method: 'POST' }), 'Processamento reiniciado')
const renderAll = () => act(() => api(`/api/projects/${props.id}/render`, { method: 'POST', body: {} }), 'Renderização iniciada')
const renderOne = (id) => act(() => api(`/api/projects/${props.id}/render`, { method: 'POST', body: { clip_ids: [id] } }), 'Renderizando corte')
async function applyEditAndRender() {
  await act(async () => {
    await api(`/api/projects/${props.id}/options`, { method: 'PATCH', body: { options: edit.value } })
    const ids = done.value.map((c) => c.id)
    await api(`/api/projects/${props.id}/render`, { method: 'POST', body: ids.length ? { clip_ids: ids } : {} })
  }, 'Refazendo os Shorts com o novo estilo')
}
const doReselect = () => act(() => api(`/api/projects/${props.id}/reselect`, { method: 'POST', body: reselect.value }), 'Nova seleção pronta')
async function remove() {
  if (!confirm('Excluir o projeto e TODOS os arquivos (vídeo original, transcrição e Shorts)?')) return
  await act(() => api(`/api/projects/${props.id}`, { method: 'DELETE' }))
  router.push('/')
}
</script>

<template>
  <div class="space-y-6">
    <RouterLink to="/" class="inline-flex items-center gap-1.5 text-sm text-ink-400 hover:text-white"><ArrowLeft class="h-4 w-4" /> Painel</RouterLink>

    <div v-if="error" class="card p-8 text-center text-red-300">{{ error }}</div>
    <div v-else-if="!p" class="card h-40 animate-pulse"></div>

    <template v-else>
      <!-- cabeçalho -->
      <header class="card flex flex-col gap-5 p-6 md:flex-row md:items-center">
        <div class="h-24 w-40 shrink-0 overflow-hidden rounded-xl bg-ink-800">
          <img v-if="p.source_thumbnail" :src="p.source_thumbnail" class="h-full w-full object-cover" alt="" />
          <img v-else :src="fileUrl(`/api/projects/${p.id}/thumb`)" class="h-full w-full object-cover" alt="" @error="$event.target.style.visibility = 'hidden'" />
        </div>
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-3">
            <h1 class="truncate font-display text-2xl font-semibold text-white">{{ p.name }}</h1>
            <StatusBadge :status="p.status" />
          </div>
          <div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-400">
            <span class="flex items-center gap-1.5"><component :is="p.source_type === 'youtube' ? Youtube : Upload" class="h-4 w-4" />{{ p.source_type === 'youtube' ? (p.source_channel || 'YouTube') : 'Upload' }}</span>
            <span>{{ fmtDuration(p.source_duration) }}</span>
            <span v-if="p.source_width">{{ p.source_width }}×{{ p.source_height }}</span>
            <span v-if="p.source_size">{{ fmtBytes(p.source_size) }}</span>
            <span>Criado em {{ fmtDate(p.created_at) }}</span>
            <span v-if="p.processing_seconds">Processamento: {{ fmtDuration(p.processing_seconds) }}</span>
          </div>
          <div class="mt-2 flex items-center gap-1.5 text-xs text-ink-500"><ShieldCheck class="h-3.5 w-3.5 text-emerald-400" /> {{ p.rights_label }}<span v-if="p.rights_note"> — {{ p.rights_note }}</span></div>
        </div>
        <div class="flex flex-wrap gap-2">
          <button v-if="active" class="btn-danger" :disabled="acting" @click="cancel"><XCircle class="h-4 w-4" /> Cancelar</button>
          <button v-if="['failed', 'cancelled'].includes(p.status)" class="btn-secondary" :disabled="acting" @click="retry"><RotateCw class="h-4 w-4" /> Tentar novamente</button>
          <a v-if="done.length" :href="fileUrl(`/api/projects/${p.id}/zip`)" class="btn-primary"><Download class="h-4 w-4" /> Baixar todos (ZIP)</a>
          <a v-if="p.has_transcript" :href="fileUrl(`/api/projects/${p.id}/transcript.srt`)" class="btn-secondary" title="Transcrição completa em SRT"><FileText class="h-4 w-4" /> SRT</a>
          <button class="btn-ghost text-red-300" :disabled="acting" @click="remove" aria-label="Excluir projeto"><Trash2 class="h-4 w-4" /></button>
        </div>
      </header>

      <!-- progresso -->
      <section v-if="active" class="card p-6">
        <div class="mb-3 flex items-center justify-between gap-4">
          <div class="flex items-center gap-2 font-medium text-white"><Loader2 class="h-4 w-4 animate-spin text-brand-400" /> {{ p.stage || 'Processando' }}</div>
          <div class="font-display text-lg tabular-nums text-brand-200">{{ Math.round(p.progress * 100) }}%</div>
        </div>
        <ProgressBar :value="p.progress" />
        <p class="mt-3 text-xs text-ink-500">
          Etapa {{ p.job?.kind === 'render' ? '2/2: renderização' : '1/2: download, transcrição e seleção' }}
          <span v-if="p.job?.attempts > 1"> · tentativa {{ p.job.attempts }} de {{ p.job.max_attempts }}</span>.
          Você pode fechar esta página — o processamento continua.
        </p>
      </section>

      <!-- erro -->
      <section v-if="p.status === 'failed'" class="card border-red-500/30 p-6">
        <div class="flex items-start gap-3 text-red-200"><AlertTriangle class="mt-0.5 h-5 w-5 shrink-0" /><div><div class="font-medium">O processamento falhou</div><p class="mt-1 text-sm text-red-300/90">{{ p.error }}</p></div></div>
      </section>

      <!-- resultados -->
      <section v-if="done.length">
        <div class="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 class="font-display text-xl font-semibold text-white">Shorts prontos <span class="text-ink-500">({{ done.length }})</span></h2>
            <p class="text-sm text-ink-400">Revise antes de publicar. Títulos e descrições são sugestões geradas a partir da própria fala.</p>
          </div>
        </div>
        <div class="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
          <ClipResult v-for="c in done" :key="c.id + (c.rendered_at || '')" :clip="c" @changed="load" @deleted="load" />
        </div>
      </section>

      <!-- estilo de edição (refazer Shorts prontos) -->
      <section v-if="p.has_transcript" class="card p-5">
        <div class="flex flex-wrap items-end gap-4">
          <div>
            <span class="label">Ritmo</span>
            <div class="flex gap-2">
              <button class="chip py-1.5" :class="{ 'chip-active': edit.pace === 'tiktok' }" @click="edit.pace = 'tiktok'">TikTok</button>
              <button class="chip py-1.5" :class="{ 'chip-active': edit.pace === 'natural' }" @click="edit.pace = 'natural'">Natural</button>
            </div>
          </div>
          <div>
            <span class="label">Velocidade</span>
            <div class="flex gap-2">
              <button v-for="v in [1.0, 1.1, 1.2]" :key="v" class="chip py-1.5" :class="{ 'chip-active': edit.speed === v }" @click="edit.speed = v">{{ v.toFixed(1) }}x</button>
            </div>
          </div>
          <label class="flex items-center gap-2 pb-2 text-sm text-ink-200"><input v-model="edit.cold_open" type="checkbox" class="h-4 w-4 accent-violet-500" /> Gancho no início</label>
          <div class="w-full">
            <span class="label">Título (chamada do vídeo)</span>
            <TitleStylePicker v-model="edit.title_style" compact />
            <div v-if="edit.title_style !== 'nenhum'" class="mt-2 flex gap-2">
              <button class="chip py-1.5" :class="{ 'chip-active': edit.title_duration === 'inteiro' }" @click="edit.title_duration = 'inteiro'">Vídeo inteiro</button>
              <button class="chip py-1.5" :class="{ 'chip-active': edit.title_duration === 'inicio' }" @click="edit.title_duration = 'inicio'">Só no início</button>
            </div>
          </div>
          <button class="btn-primary ml-auto" :disabled="!canEdit || acting" @click="applyEditAndRender"><Wand2 class="h-4 w-4" /> {{ done.length ? 'Refazer Shorts com este estilo' : 'Salvar estilo' }}</button>
        </div>
        <p class="mt-2 text-xs text-ink-500">Refaz os vídeos e também as descrições, sem transcrever de novo.</p>
      </section>

      <!-- revisão -->
      <section v-if="p.has_transcript">
        <div class="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 class="font-display text-xl font-semibold text-white">Cortes selecionados <span class="text-ink-500">({{ selected.length }})</span></h2>
            <p class="text-sm text-ink-400">Ouça a prévia, ajuste início/fim, corrija a legenda, troque por alternativas e renderize.</p>
          </div>
          <button class="btn-primary" :disabled="!canEdit || acting || !selected.length" @click="renderAll"><Wand2 class="h-4 w-4" /> {{ p.status === 'awaiting_review' ? 'Gerar Shorts' : 'Renderizar selecionados' }}</button>
        </div>
        <div class="space-y-4">
          <ClipEditor v-for="(c, i) in selected" :key="c.id" :clip="c" :project="p" :index="i" :alternatives="alternatives" :busy="!canEdit || acting" @changed="load" @render="renderOne" />
          <div v-if="!selected.length" class="card p-6 text-center text-sm text-ink-400">Nenhum corte selecionado. Escolha entre as alternativas abaixo.</div>
        </div>

        <div class="card mt-6 p-5">
          <div class="flex flex-wrap items-end gap-3">
            <div>
              <label class="label" for="rc">Quantidade</label>
              <input id="rc" v-model.number="reselect.count" type="number" min="1" max="20" class="input w-24 py-2" />
            </div>
            <div>
              <label class="label" for="rmin">Mín. (s)</label>
              <input id="rmin" v-model.number="reselect.min_duration" type="number" min="5" max="175" class="input w-24 py-2" />
            </div>
            <div>
              <label class="label" for="rmax">Máx. (s)</label>
              <input id="rmax" v-model.number="reselect.max_duration" type="number" min="10" max="180" class="input w-24 py-2" />
            </div>
            <button class="btn-secondary" :disabled="!canEdit || acting" @click="doReselect"><RefreshCw class="h-4 w-4" /> Refazer seleção</button>
            <p class="text-xs text-ink-500 md:ml-2 md:max-w-xs">Usa a transcrição já feita — leva poucos segundos. Shorts já renderizados são mantidos.</p>
          </div>
        </div>

        <div v-if="alternatives.length" class="mt-6">
          <button class="btn-ghost px-0 text-sm" @click="showAlternatives = !showAlternatives">{{ showAlternatives ? 'Ocultar' : 'Mostrar' }} alternativas ({{ alternatives.length }})</button>
          <div v-if="showAlternatives" class="mt-3 space-y-4">
            <ClipEditor v-for="c in alternatives" :key="c.id" :clip="c" :project="p" :busy="!canEdit || acting" @changed="load" />
          </div>
        </div>
      </section>

      <!-- log -->
      <section class="card p-5">
        <button class="flex items-center gap-2 text-sm text-ink-300 hover:text-white" @click="showLog = !showLog; showLog && loadLog()"><ScrollText class="h-4 w-4" /> {{ showLog ? 'Ocultar' : 'Ver' }} registro de processamento</button>
        <pre v-if="showLog" class="mt-3 max-h-80 overflow-auto whitespace-pre-wrap rounded-xl bg-ink-950 p-4 font-mono text-xs leading-relaxed text-ink-300">{{ log || 'Sem registros ainda.' }}</pre>
      </section>
    </template>
  </div>
</template>
