<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Youtube, Upload, Link2, Loader2, FileVideo, ShieldCheck, Sparkles, Captions, X, AlertTriangle, CheckCircle2, FileText } from 'lucide-vue-next'
import { api, uploadFile, fileUrl } from '../api'
import { fmtBytes, fmtDuration, toast, LAYOUT_LABELS, CAPTION_LABELS } from '../utils'
import ProgressBar from '../components/ProgressBar.vue'

const route = useRoute()
const router = useRouter()
const tab = ref(route.query.tab === 'upload' ? 'upload' : 'youtube')
const meta = ref(null)

// --- YouTube
const url = ref('')
const urlCheck = ref(null)       // validação offline
const yt = ref(null)             // metadados
const ytLoading = ref(false)
const ytError = ref('')
let validateTimer
watch(url, (v) => {
  yt.value = null
  ytError.value = ''
  clearTimeout(validateTimer)
  if (!v.trim()) { urlCheck.value = null; return }
  validateTimer = setTimeout(async () => {
    urlCheck.value = await api('/api/youtube/validate', { method: 'POST', body: { url: v } }).catch(() => null)
  }, 250)
})
async function inspect() {
  ytLoading.value = true
  ytError.value = ''
  try {
    yt.value = await api('/api/youtube/inspect', { method: 'POST', body: { url: url.value } })
    if (!form.name) form.name = ''
  } catch (e) {
    ytError.value = e.message
  } finally {
    ytLoading.value = false
  }
}

// --- Upload
const video = ref(null)
const videoProgress = ref(0)
const videoUploading = ref(false)
const dragging = ref(false)
const subtitle = ref(null)
async function onVideo(file) {
  if (!file) return
  video.value = null
  videoUploading.value = true
  videoProgress.value = 0
  try {
    video.value = await uploadFile('video', file, (p) => (videoProgress.value = p))
  } catch (e) {
    toast(e.message, 'error', 7000)
  } finally {
    videoUploading.value = false
  }
}
function onDrop(e) {
  dragging.value = false
  onVideo(e.dataTransfer.files[0])
}
async function onSubtitle(file) {
  if (!file) return
  try {
    subtitle.value = await uploadFile('subtitle', file)
  } catch (e) {
    toast(e.message, 'error')
  }
}

// --- Configuração
const form = reactive({
  name: '',
  count: 5,
  customCount: 7,
  durationPreset: '30-60',
  minDuration: 30,
  maxDuration: 60,
  style: 'podcast_premium',
  caption_style: 'classic',
  layout: 'auto',
  captions: true,
  trim_silence: true,
  review: false,
  engine: 'ffmpeg',
  hook: true,
  zoom: true,
  rightsConfirmed: false,
  rightsBasis: 'own',
  rightsNote: '',
})
const durationPresets = { '15-30': [15, 30], '30-60': [30, 60], '60-90': [60, 90] }
watch(() => form.style, (s) => {
  const d = meta.value?.style_defaults?.[s]
  if (d) { form.caption_style = d.caption_style; form.layout = d.layout }
})

const count = computed(() => (form.count === 'custom' ? Number(form.customCount) : form.count))
const durations = computed(() => form.durationPreset === 'custom'
  ? [Number(form.minDuration), Number(form.maxDuration)]
  : durationPresets[form.durationPreset])

const sourceReady = computed(() => (tab.value === 'youtube' ? !!yt.value : !!video.value))
const needsNote = computed(() => form.rightsBasis !== 'own')
const canSubmit = computed(() => sourceReady.value && form.rightsConfirmed && (!needsNote.value || form.rightsNote.trim().length >= 5)
  && count.value >= 1 && durations.value[0] < durations.value[1])
const submitting = ref(false)
const duplicate = ref(null)

async function submit(force = false) {
  submitting.value = true
  duplicate.value = null
  try {
    const body = {
      name: form.name || null,
      source: tab.value === 'youtube' ? { type: 'youtube', url: url.value } : { type: 'upload', upload_id: video.value.token },
      subtitle_upload_id: subtitle.value?.token || null,
      rights: { confirmed: form.rightsConfirmed, basis: form.rightsBasis, note: form.rightsNote },
      options: {
        count: count.value, min_duration: durations.value[0], max_duration: durations.value[1],
        style: form.style, caption_style: form.caption_style, layout: form.layout,
        captions: form.captions, trim_silence: form.trim_silence, review: form.review,
        engine: form.engine, hook: form.hook, zoom: form.zoom,
      },
      force,
    }
    const p = await api('/api/projects', { method: 'POST', body })
    toast('Projeto criado! O processamento começou.', 'success')
    router.push(`/projetos/${p.id}`)
  } catch (e) {
    if (e.status === 409 && e.detail?.project_id) duplicate.value = e.detail
    else toast(e.message, 'error', 7000)
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  meta.value = await api('/api/meta').catch(() => null)
})
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="page-title">Criar novos Shorts</h1>
      <p class="mt-1 text-ink-400">Escolha a origem, confirme os direitos de uso e configure os cortes.</p>
    </div>

    <div v-if="meta && meta.ffmpeg_available === false" class="flex items-start gap-3 rounded-2xl border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-100">
      <AlertTriangle class="mt-0.5 h-5 w-5 shrink-0 text-red-300" />
      <div>
        <div class="font-medium">FFmpeg não encontrado — os Shorts não podem ser gerados.</div>
        <div class="mt-1 text-red-200/90">No Windows, abra o PowerShell e rode <code class="rounded bg-black/30 px-1.5 py-0.5">winget install Gyan.FFmpeg</code>. Depois feche a janela preta do ClipFlow e abra o <code class="rounded bg-black/30 px-1.5 py-0.5">start-windows.bat</code> de novo.</div>
      </div>
    </div>

    <div class="grid gap-6 xl:grid-cols-5">
      <div class="space-y-6 xl:col-span-3">
        <!-- 1. Origem -->
        <section class="card p-6">
          <h2 class="mb-4 font-display text-lg font-semibold text-white">1. Vídeo de origem</h2>
          <div class="mb-5 inline-flex rounded-xl border border-ink-700 bg-ink-850 p-1">
            <button class="rounded-lg px-4 py-2 text-sm font-medium transition" :class="tab === 'youtube' ? 'bg-ink-700 text-white' : 'text-ink-400 hover:text-white'" @click="tab = 'youtube'">
              <Youtube class="mr-1.5 inline h-4 w-4" />Link do YouTube
            </button>
            <button class="rounded-lg px-4 py-2 text-sm font-medium transition" :class="tab === 'upload' ? 'bg-ink-700 text-white' : 'text-ink-400 hover:text-white'" @click="tab = 'upload'">
              <Upload class="mr-1.5 inline h-4 w-4" />Enviar arquivo
            </button>
          </div>

          <div v-if="tab === 'youtube'" class="space-y-4">
            <form class="flex flex-col gap-3 sm:flex-row" @submit.prevent="inspect">
              <div class="relative flex-1">
                <Link2 class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-500" />
                <input v-model="url" class="input pl-9" placeholder="https://www.youtube.com/watch?v=..." inputmode="url" aria-label="Link do YouTube" />
              </div>
              <button class="btn-secondary" :disabled="!urlCheck?.valid || ytLoading">
                <Loader2 v-if="ytLoading" class="h-4 w-4 animate-spin" /> Buscar vídeo
              </button>
            </form>
            <p v-if="urlCheck && !urlCheck.valid" class="text-sm text-amber-300">{{ urlCheck.error }}</p>
            <p v-if="ytError" class="flex items-start gap-2 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200"><AlertTriangle class="mt-0.5 h-4 w-4 shrink-0" />{{ ytError }}</p>
            <div v-if="yt" class="flex animate-fade-in gap-4 rounded-xl border border-ink-700 bg-ink-850 p-3">
              <img :src="yt.thumbnail" class="h-24 w-40 shrink-0 rounded-lg object-cover" alt="" />
              <div class="min-w-0">
                <div class="line-clamp-2 font-medium text-white">{{ yt.title }}</div>
                <div class="mt-1 text-sm text-ink-400">{{ yt.channel }}</div>
                <div class="mt-1 text-sm text-ink-400">Duração: {{ fmtDuration(yt.duration) }}<span v-if="yt.license"> · Licença: {{ yt.license }}</span></div>
                <div v-if="yt.duplicate" class="mt-2 text-xs text-amber-300">Já existe um projeto com este vídeo: <RouterLink class="underline" :to="`/projetos/${yt.duplicate.id}`">{{ yt.duplicate.name }}</RouterLink></div>
              </div>
            </div>
            <p class="text-xs text-ink-500">Somente vídeos públicos e individuais. Vídeos privados, com restrição de idade, de membros ou com DRM são recusados — o ClipFlow não contorna proteções.</p>
          </div>

          <div v-else class="space-y-4">
            <label
              class="flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition"
              :class="dragging ? 'border-brand-500 bg-brand-500/10' : 'border-ink-600 hover:border-ink-500 hover:bg-ink-850'"
              @dragover.prevent="dragging = true" @dragleave="dragging = false" @drop.prevent="onDrop"
            >
              <FileVideo class="mb-3 h-10 w-10 text-brand-400" />
              <span class="font-medium text-white">Arraste o vídeo aqui ou clique para escolher</span>
              <span class="mt-1 text-sm text-ink-400">MP4, MOV, MKV, WEBM e outros formatos do FFmpeg · até {{ meta?.max_upload_mb ? fmtBytes(meta.max_upload_mb * 1048576) : '4 GB' }}</span>
              <input type="file" class="hidden" accept="video/*,.mkv,.mov,.ts,.mts" @change="onVideo($event.target.files[0])" />
            </label>
            <div v-if="videoUploading" class="space-y-2">
              <div class="flex justify-between text-sm text-ink-300"><span>Enviando…</span><span class="tabular-nums">{{ Math.round(videoProgress * 100) }}%</span></div>
              <ProgressBar :value="videoProgress" />
              <p v-if="videoProgress >= 1" class="text-xs text-ink-400">Verificando arquivo com FFprobe…</p>
            </div>
            <div v-if="video" class="flex animate-fade-in items-center gap-4 rounded-xl border border-ink-700 bg-ink-850 p-3">
              <img :src="fileUrl(`/api/uploads/${video.token}/thumb`)" class="h-20 w-32 shrink-0 rounded-lg bg-ink-800 object-cover" alt="" @error="$event.target.style.visibility = 'hidden'" />
              <div class="min-w-0 flex-1 text-sm">
                <div class="truncate font-medium text-white">{{ video.filename }}</div>
                <div class="mt-1 text-ink-400">{{ fmtBytes(video.size) }} · {{ fmtDuration(video.info.duration) }} · {{ video.info.width }}×{{ video.info.height }} · {{ Math.round(video.info.fps) }} fps</div>
                <div class="mt-1 flex items-center gap-1 text-emerald-300"><CheckCircle2 class="h-3.5 w-3.5" /> Arquivo válido</div>
              </div>
              <button class="btn-ghost p-2" @click="video = null" aria-label="Remover"><X class="h-4 w-4" /></button>
            </div>
          </div>

          <!-- legenda opcional -->
          <div class="mt-5 rounded-xl border border-ink-700 bg-ink-850/60 p-4">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div class="text-sm">
                <div class="flex items-center gap-2 font-medium text-ink-100"><FileText class="h-4 w-4 text-sky-300" /> Já tem a legenda (.srt/.vtt)? <span class="text-xs font-normal text-ink-500">opcional</span></div>
                <div class="mt-0.5 text-xs text-ink-400">Pula a transcrição com Whisper — útil em computadores mais modestos.</div>
              </div>
              <label v-if="!subtitle" class="btn-secondary cursor-pointer text-xs">
                Escolher legenda <input type="file" class="hidden" accept=".srt,.vtt" @change="onSubtitle($event.target.files[0])" />
              </label>
              <div v-else class="flex items-center gap-2 text-sm text-emerald-300">
                <CheckCircle2 class="h-4 w-4" /> {{ subtitle.filename }} ({{ subtitle.cues }} blocos)
                <button class="btn-ghost p-1" @click="subtitle = null" aria-label="Remover legenda"><X class="h-4 w-4" /></button>
              </div>
            </div>
          </div>
        </section>

        <!-- 2. Direitos -->
        <section class="card p-6">
          <h2 class="mb-1 flex items-center gap-2 font-display text-lg font-semibold text-white"><ShieldCheck class="h-5 w-5 text-emerald-400" /> 2. Direitos de uso</h2>
          <p class="mb-4 text-sm text-ink-400">Fica registrado no projeto junto com a origem do vídeo.</p>
          <div class="grid gap-4 sm:grid-cols-2">
            <div>
              <label class="label" for="basis">Base legal</label>
              <select id="basis" v-model="form.rightsBasis" class="input">
                <option v-for="(label, key) in meta?.rights_bases || { own: 'Conteúdo próprio' }" :key="key" :value="key">{{ label }}</option>
              </select>
            </div>
            <div>
              <label class="label" for="note">Documentação da autorização <span v-if="needsNote" class="text-amber-300">*</span></label>
              <input id="note" v-model="form.rightsNote" class="input" :placeholder="needsNote ? 'Ex.: contrato de 10/2026, e-mail do convidado, link da licença' : 'Opcional'" />
            </div>
          </div>
          <label class="mt-4 flex cursor-pointer items-start gap-3 rounded-xl border border-ink-700 bg-ink-850 p-4 text-sm">
            <input v-model="form.rightsConfirmed" type="checkbox" class="mt-0.5 h-4 w-4 accent-violet-500" />
            <span class="text-ink-200">Confirmo que tenho direito de baixar, editar e publicar trechos deste conteúdo.</span>
          </label>
          <p class="mt-3 text-xs leading-relaxed text-ink-500">Cortes de conteúdo de terceiros podem gerar reivindicações de direitos autorais. Adicionar legendas não torna o conteúdo original e não garante monetização no YouTube — priorize contribuição editorial própria.</p>
        </section>
      </div>

      <!-- 3. Configuração -->
      <div class="space-y-6 xl:col-span-2">
        <section class="card space-y-6 p-6 xl:sticky xl:top-6">
          <h2 class="font-display text-lg font-semibold text-white">3. Configuração dos cortes</h2>

          <div>
            <span class="label">Quantidade de Shorts</span>
            <div class="flex flex-wrap gap-2">
              <button v-for="n in [3, 5, 10]" :key="n" class="chip" :class="{ 'chip-active': form.count === n }" @click="form.count = n">{{ n }}</button>
              <button class="chip" :class="{ 'chip-active': form.count === 'custom' }" @click="form.count = 'custom'">Personalizado</button>
              <input v-if="form.count === 'custom'" v-model.number="form.customCount" type="number" min="1" :max="meta?.max_clips || 20" class="input w-24" aria-label="Quantidade personalizada" />
            </div>
          </div>

          <div>
            <span class="label">Duração</span>
            <div class="flex flex-wrap gap-2">
              <button v-for="(v, k) in durationPresets" :key="k" class="chip" :class="{ 'chip-active': form.durationPreset === k }" @click="form.durationPreset = k">{{ v[0] }}–{{ v[1] }}s</button>
              <button class="chip" :class="{ 'chip-active': form.durationPreset === 'custom' }" @click="form.durationPreset = 'custom'">Personalizada</button>
            </div>
            <div v-if="form.durationPreset === 'custom'" class="mt-3 flex items-center gap-2 text-sm text-ink-300">
              <input v-model.number="form.minDuration" type="number" min="5" :max="meta?.max_clip_seconds || 180" class="input w-24" aria-label="Duração mínima" /> a
              <input v-model.number="form.maxDuration" type="number" min="10" :max="meta?.max_clip_seconds || 180" class="input w-24" aria-label="Duração máxima" /> segundos
            </div>
            <p class="mt-2 text-xs text-ink-500">Limite atual do YouTube Shorts: até {{ meta?.max_clip_seconds || 180 }}s. Exportação: MP4 · H.264 · AAC · 1080×1920.</p>
          </div>

          <div>
            <label class="label" for="style">Estilo</label>
            <select id="style" v-model="form.style" class="input">
              <option v-for="(label, key) in meta?.styles || { podcast_premium: 'Podcast premium' }" :key="key" :value="key">{{ label }}</option>
            </select>
          </div>

          <div>
            <span class="label flex items-center gap-1.5"><Captions class="h-3.5 w-3.5" /> Legendas</span>
            <div class="grid grid-cols-2 gap-2">
              <button v-for="(c, key) in CAPTION_LABELS" :key="key" class="rounded-xl border p-3 text-left transition"
                      :class="form.caption_style === key ? 'border-brand-500 bg-brand-500/10 ring-1 ring-brand-500/40' : 'border-ink-600 bg-ink-850 hover:border-ink-500'"
                      @click="form.caption_style = key">
                <div class="rounded-lg bg-black/60 px-2 py-2 text-center text-sm font-extrabold tracking-wide" :style="{ fontFamily: c.font === 'Anton' ? 'Impact, Anton, sans-serif' : 'inherit' }">
                  <span class="text-white" :style="{ textShadow: key === 'minimal' ? '0 2px 4px #000' : '0 0 3px #000, 0 0 3px #000' }">ISSO </span>
                  <span :style="{ color: c.hl, textShadow: key === 'neon' ? '0 0 8px #7c3aed' : '0 0 3px #000' }">MUDA</span>
                </div>
                <div class="mt-2 text-sm font-medium text-ink-100">{{ c.name }}</div>
                <div class="text-xs text-ink-400">{{ c.desc }}</div>
              </button>
            </div>
          </div>

          <div>
            <label class="label" for="layout">Enquadramento</label>
            <select id="layout" v-model="form.layout" class="input">
              <option v-for="(label, key) in LAYOUT_LABELS" :key="key" :value="key" :disabled="key === 'manual'">{{ label }}</option>
            </select>
            <p class="mt-1.5 text-xs text-ink-500">Automático: segue o rosto principal ou divide a tela quando há duas pessoas distantes. Ajuste fino por corte na revisão.</p>
          </div>

          <div>
            <span class="label">Motor de edição</span>
            <div class="grid grid-cols-2 gap-2">
              <button class="rounded-xl border p-3 text-left transition" :class="form.engine === 'ffmpeg' ? 'border-brand-500 bg-brand-500/10 ring-1 ring-brand-500/40' : 'border-ink-600 bg-ink-850 hover:border-ink-500'" @click="form.engine = 'ffmpeg'">
                <div class="text-sm font-medium text-ink-100">Rápido (FFmpeg)</div>
                <div class="text-xs text-ink-400">Legenda animada palavra a palavra</div>
              </button>
              <button class="rounded-xl border p-3 text-left transition disabled:cursor-not-allowed disabled:opacity-50" :disabled="!meta?.concat_available"
                      :class="form.engine === 'concat' ? 'border-brand-500 bg-brand-500/10 ring-1 ring-brand-500/40' : 'border-ink-600 bg-ink-850 hover:border-ink-500'" @click="form.engine = 'concat'">
                <div class="text-sm font-medium text-ink-100">Edição com IA (Concat)</div>
                <div class="text-xs text-ink-400">{{ meta?.concat_available ? 'Zoom de ênfase, texto de gancho, projeto editável' : 'Instale o Concat para ativar' }}</div>
              </button>
            </div>
            <div v-if="form.engine === 'concat'" class="mt-3 space-y-2 text-sm">
              <label class="flex items-center justify-between gap-3"><span class="text-ink-200">Texto de gancho nos primeiros segundos</span><input v-model="form.hook" type="checkbox" class="h-4 w-4 accent-violet-500" /></label>
              <label class="flex items-center justify-between gap-3"><span class="text-ink-200">Zoom nas frases de ênfase</span><input v-model="form.zoom" type="checkbox" class="h-4 w-4 accent-violet-500" /></label>
              <p class="text-xs text-ink-500">No Concat as legendas aparecem por frase. Se o Concat falhar, o corte é feito pelo FFmpeg automaticamente.</p>
            </div>
          </div>

          <div class="space-y-3 text-sm">
            <label class="flex items-center justify-between gap-3"><span class="text-ink-200">Remover pausas longas</span><input v-model="form.trim_silence" type="checkbox" class="h-4 w-4 accent-violet-500" /></label>
            <label class="flex items-center justify-between gap-3"><span class="text-ink-200">Revisar cortes antes de renderizar</span><input v-model="form.review" type="checkbox" class="h-4 w-4 accent-violet-500" /></label>
          </div>

          <div>
            <label class="label" for="pname">Nome do projeto <span class="normal-case text-ink-500">(opcional)</span></label>
            <input id="pname" v-model="form.name" class="input" maxlength="120" :placeholder="yt?.title || video?.filename || 'Ex.: Episódio 42'" />
          </div>

          <div v-if="duplicate" class="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-100">
            {{ duplicate.message }}
            <div class="mt-3 flex gap-2">
              <RouterLink :to="`/projetos/${duplicate.project_id}`" class="btn-secondary text-xs">Abrir existente</RouterLink>
              <button class="btn-ghost text-xs" @click="submit(true)">Processar mesmo assim</button>
            </div>
          </div>

          <button class="btn-primary w-full py-3.5 text-base" :disabled="!canSubmit || submitting" @click="submit(false)">
            <Loader2 v-if="submitting" class="h-5 w-5 animate-spin" /><Sparkles v-else class="h-5 w-5" /> Gerar Shorts
          </button>
          <ul v-if="!canSubmit" class="space-y-1 text-xs text-ink-500">
            <li v-if="!sourceReady">• {{ tab === 'youtube' ? 'Busque um vídeo do YouTube' : 'Envie um arquivo de vídeo' }}</li>
            <li v-if="!form.rightsConfirmed">• Confirme os direitos de uso</li>
            <li v-if="needsNote && form.rightsNote.trim().length < 5">• Documente a autorização/licença</li>
          </ul>
        </section>
      </div>
    </div>
  </div>
</template>
