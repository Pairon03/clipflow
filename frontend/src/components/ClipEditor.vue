<script setup>
import { computed, ref, watch } from 'vue'
import { Play, Pause, ChevronDown, ChevronUp, Save, RotateCcw, Replace, Check, Minus, Plus, Wand2, AlertTriangle } from 'lucide-vue-next'
import { api, fileUrl } from '../api'
import { fmtTime, toast, LAYOUT_LABELS, STATUS } from '../utils'
import ScoreBreakdown from './ScoreBreakdown.vue'
import HookPicker from './HookPicker.vue'

const props = defineProps({
  clip: Object,
  project: Object,
  alternatives: { type: Array, default: () => [] },
  index: Number,
  busy: Boolean,
})
const emit = defineEmits(['changed', 'render'])

const expanded = ref(false)
const editingText = ref(false)
const text = ref(props.clip.text)
const start = ref(props.clip.start)
const end = ref(props.clip.end)
const layout = ref(props.clip.layout)
const manualX = ref(props.clip.manual_x ?? 0.5)
const saving = ref(false)
const swapWith = ref('')
watch(() => props.clip, (c) => {
  text.value = c.text; start.value = c.start; end.value = c.end; layout.value = c.layout; manualX.value = c.manual_x ?? 0.5
})

const dirtyRange = computed(() => Math.abs(start.value - props.clip.start) > 0.01 || Math.abs(end.value - props.clip.end) > 0.01)
const scoreTone = computed(() => props.clip.score >= 75 ? 'text-emerald-300' : props.clip.score >= 55 ? 'text-amber-300' : 'text-red-300')

// prévia do trecho no vídeo original
const videoEl = ref(null)
const playing = ref(false)
function togglePreview() {
  const v = videoEl.value
  if (!v) return
  if (playing.value) { v.pause(); return }
  if (v.currentTime < start.value || v.currentTime >= end.value - 0.1) v.currentTime = start.value
  v.play()
}
function onTime() {
  const v = videoEl.value
  if (v && v.currentTime >= end.value) { v.pause(); v.currentTime = start.value }
}
const previewX = computed(() => `${(layout.value === 'manual' ? manualX.value : 0.5) * 100}%`)

// manchete do estilo viral: vazia = automática (tirada da fala)
const headline = ref(props.clip.headline || '')
const autoHeadline = ref('')
watch(expanded, async (open) => {
  if (open && props.project?.options?.viral_headline && !autoHeadline.value) {
    autoHeadline.value = (await api(`/api/clips/${props.clip.id}/headline`).catch(() => ({}))).auto || ''
  }
})
async function saveHeadline() {
  await patch({ headline: headline.value }, headline.value ? 'Manchete salva' : 'Manchete automática')
}

async function patch(body, msg) {
  saving.value = true
  try {
    await api(`/api/clips/${props.clip.id}`, { method: 'PATCH', body })
    if (msg) toast(msg, 'success')
    emit('changed')
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    saving.value = false
  }
}
const saveRange = () => patch({ start: Number(start.value), end: Number(end.value) }, 'Intervalo atualizado')
const saveText = async () => { await patch({ text: text.value }, 'Legenda corrigida (sincronização mantida)'); editingText.value = false }
const saveLayout = () => patch({ layout: layout.value, manual_x: layout.value === 'manual' ? Number(manualX.value) : null })
const toggleSelect = () => patch({ selected: !props.clip.selected })
const chooseHook = (choice) => patch({ hook_choice: choice }, choice === 'none' ? 'Corte sem gancho' : 'Gancho escolhido')
async function resetText() {
  await api(`/api/clips/${props.clip.id}/reset-text`, { method: 'POST' }).catch((e) => toast(e.message, 'error'))
  emit('changed')
}
async function swap() {
  if (!swapWith.value) return
  try {
    await api(`/api/clips/${props.clip.id}/swap`, { method: 'POST', body: { with_id: swapWith.value } })
    toast('Sugestão substituída', 'success')
    swapWith.value = ''
    emit('changed')
  } catch (e) { toast(e.message, 'error') }
}
function nudge(which, delta) {
  if (which === 'start') start.value = Math.max(0, +(start.value + delta).toFixed(2))
  else end.value = +(end.value + delta).toFixed(2)
}
</script>

<template>
  <article class="card overflow-hidden" :class="clip.selected ? '' : 'opacity-80'">
    <div class="flex flex-col gap-4 p-5 lg:flex-row">
      <!-- prévia vertical do trecho -->
      <div class="relative mx-auto aspect-[9/16] w-40 shrink-0 overflow-hidden rounded-xl bg-black ring-1 ring-ink-700 lg:mx-0">
        <video
          v-if="project.has_source" ref="videoEl" :src="fileUrl(`/api/projects/${project.id}/source`) + `#t=${clip.start}`"
          preload="metadata" playsinline class="absolute inset-0 h-full w-full object-cover" :style="{ objectPosition: `${previewX} 50%` }"
          @play="playing = true" @pause="playing = false" @timeupdate="onTime"
        ></video>
        <button class="absolute inset-0 flex items-center justify-center bg-black/20 opacity-0 transition hover:opacity-100 focus:opacity-100" :class="{ 'opacity-100': !playing }" @click="togglePreview" :aria-label="playing ? 'Pausar prévia' : 'Reproduzir prévia'">
          <span class="rounded-full bg-black/60 p-3 backdrop-blur"><component :is="playing ? Pause : Play" class="h-5 w-5 text-white" /></span>
        </button>
        <span class="absolute bottom-1.5 left-1.5 rounded bg-black/70 px-1.5 py-0.5 text-[10px] text-ink-200">prévia do original</span>
      </div>

      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-2">
          <span v-if="index != null" class="font-display text-sm font-semibold text-brand-300">#{{ index + 1 }}</span>
          <span v-if="clip.series" class="rounded-md bg-red-500/15 px-2 py-0.5 text-xs font-semibold text-red-200" :title="clip.series.auto ? 'Série sugerida automaticamente: história forte e longa' : 'Série criada por você'">Parte {{ clip.series.part }}/{{ clip.series.total }}</span>
          <span class="rounded-md bg-ink-800 px-2 py-0.5 text-xs text-ink-300">{{ clip.category }}</span>
          <span class="text-xs tabular-nums text-ink-400">{{ fmtTime(clip.start) }} → {{ fmtTime(clip.end) }} · {{ clip.duration_planned }}s</span>
          <span v-if="clip.status === 'done'" class="rounded-md bg-emerald-500/15 px-2 py-0.5 text-xs text-emerald-300">Renderizado</span>
          <span v-if="clip.status === 'rendering'" class="rounded-md bg-brand-500/15 px-2 py-0.5 text-xs text-brand-300">Renderizando…</span>
          <span v-if="clip.status === 'failed'" class="rounded-md bg-red-500/15 px-2 py-0.5 text-xs text-red-300" :title="clip.error">Falhou</span>
          <span v-if="clip.render_info?.stale" class="rounded-md bg-amber-500/15 px-2 py-0.5 text-xs text-amber-300">Alterações não renderizadas</span>
          <span v-if="clip.edited_words" class="rounded-md bg-sky-500/15 px-2 py-0.5 text-xs text-sky-300">Legenda corrigida</span>
          <span class="ml-auto text-right">
            <span class="font-display text-xl font-semibold tabular-nums" :class="scoreTone">{{ Math.round(clip.score) }}</span>
            <span class="block text-[10px] uppercase tracking-wide text-ink-500">pontuação editorial</span>
          </span>
        </div>

        <p v-if="!editingText" class="mt-3 line-clamp-4 text-sm leading-relaxed text-ink-200">{{ clip.text }}</p>
        <div v-else class="mt-3 space-y-2">
          <textarea v-model="text" rows="5" class="input font-mono text-xs leading-relaxed"></textarea>
          <p class="text-xs text-ink-500">Corrija palavras, pontuação ou maiúsculas. Os tempos por palavra são mantidos automaticamente.</p>
          <div class="flex gap-2">
            <button class="btn-primary py-1.5 text-xs" :disabled="saving || busy" @click="saveText"><Save class="h-3.5 w-3.5" /> Salvar legenda</button>
            <button class="btn-ghost py-1.5 text-xs" @click="editingText = false; text = clip.text">Cancelar</button>
          </div>
        </div>
        <p v-if="clip.error && clip.status === 'failed'" class="mt-2 flex items-start gap-1.5 text-xs text-red-300"><AlertTriangle class="mt-0.5 h-3.5 w-3.5 shrink-0" />{{ clip.error }}</p>

        <div class="mt-4 flex flex-wrap gap-2">
          <button class="btn-secondary py-1.5 text-xs" :disabled="saving || busy" @click="toggleSelect">
            <Check v-if="!clip.selected" class="h-3.5 w-3.5" />{{ clip.selected ? 'Remover da seleção' : 'Selecionar' }}
          </button>
          <button v-if="!editingText" class="btn-ghost py-1.5 text-xs" :disabled="busy" @click="editingText = true">Corrigir legenda</button>
          <button v-if="clip.edited_words" class="btn-ghost py-1.5 text-xs" :disabled="busy" @click="resetText"><RotateCcw class="h-3.5 w-3.5" /> Texto original</button>
          <button v-if="clip.selected" class="btn-ghost py-1.5 text-xs" :disabled="busy" @click="emit('render', clip.id)"><Wand2 class="h-3.5 w-3.5" /> Renderizar este</button>
          <button class="btn-ghost py-1.5 text-xs" @click="expanded = !expanded">
            <component :is="expanded ? ChevronUp : ChevronDown" class="h-3.5 w-3.5" /> Ajustes e detalhes
          </button>
        </div>
      </div>
    </div>

    <div v-if="expanded" class="grid gap-6 border-t border-ink-800 bg-ink-850/50 p-5 md:grid-cols-2">
      <div class="space-y-5">
        <div>
          <span class="label">Início e fim (segundos)</span>
          <div class="flex flex-wrap items-center gap-2">
            <div class="flex items-center gap-1">
              <button class="btn-ghost p-1.5" @click="nudge('start', -0.5)" aria-label="Início -0,5s"><Minus class="h-3.5 w-3.5" /></button>
              <input v-model.number="start" type="number" step="0.1" class="input w-24 py-1.5 text-center" aria-label="Início" />
              <button class="btn-ghost p-1.5" @click="nudge('start', 0.5)" aria-label="Início +0,5s"><Plus class="h-3.5 w-3.5" /></button>
            </div>
            <span class="text-ink-500">→</span>
            <div class="flex items-center gap-1">
              <button class="btn-ghost p-1.5" @click="nudge('end', -0.5)" aria-label="Fim -0,5s"><Minus class="h-3.5 w-3.5" /></button>
              <input v-model.number="end" type="number" step="0.1" class="input w-24 py-1.5 text-center" aria-label="Fim" />
              <button class="btn-ghost p-1.5" @click="nudge('end', 0.5)" aria-label="Fim +0,5s"><Plus class="h-3.5 w-3.5" /></button>
            </div>
            <button v-if="dirtyRange" class="btn-primary py-1.5 text-xs" :disabled="saving || busy" @click="saveRange"><Save class="h-3.5 w-3.5" /> Aplicar</button>
          </div>
        </div>
        <div>
          <label class="label" :for="`layout-${clip.id}`">Enquadramento deste corte</label>
          <select :id="`layout-${clip.id}`" v-model="layout" class="input py-2" @change="layout !== 'manual' && saveLayout()">
            <option v-for="(label, key) in LAYOUT_LABELS" :key="key" :value="key">{{ label }}</option>
          </select>
          <div v-if="layout === 'manual'" class="mt-3">
            <input v-model.number="manualX" type="range" min="0" max="1" step="0.01" class="w-full accent-violet-500" aria-label="Posição horizontal" />
            <div class="mt-1 flex justify-between text-xs text-ink-500"><span>esquerda</span><span>centro</span><span>direita</span></div>
            <button class="btn-primary mt-2 py-1.5 text-xs" :disabled="saving" @click="saveLayout"><Save class="h-3.5 w-3.5" /> Salvar posição</button>
          </div>
          <p v-if="clip.render_info?.layout" class="mt-2 text-xs text-ink-500">Último render: {{ LAYOUT_LABELS[clip.render_info.layout] }} · {{ clip.render_info.faces ?? 0 }} rosto(s) · {{ clip.render_info.detector || 'sem detector' }}<span v-if="clip.render_info.note"> · {{ clip.render_info.note }}</span></p>
        </div>
        <div v-if="project?.options?.viral_headline" class="rounded-xl border border-ink-700 bg-ink-850 p-3">
          <label class="label" :for="`hl-${clip.id}`">Manchete de gancho (estilo viral)</label>
          <div class="flex gap-2">
            <input :id="`hl-${clip.id}`" v-model="headline" class="input py-1.5 text-sm uppercase" maxlength="90"
                   :placeholder="autoHeadline ? `Automática: ${autoHeadline}` : 'Automática (tirada da fala)'" />
            <button type="button" class="btn-secondary py-1.5 text-xs" :disabled="saving || busy" @click="saveHeadline">Salvar</button>
          </div>
          <p class="mt-1 text-xs text-ink-500">Deixe vazio para usar a automática. Aparece em letras grandes nos 2–3 primeiros segundos.</p>
        </div>
        <div v-if="project?.options?.cold_open">
          <span class="label">Gancho de abertura</span>
          <HookPicker :hook="clip.hook" :clip-start="clip.start" :disabled="saving || busy" @choose="chooseHook" />
        </div>
        <div v-if="clip.selected && alternatives.length">
          <span class="label">Substituir por uma alternativa</span>
          <div class="flex gap-2">
            <select v-model="swapWith" class="input py-2">
              <option value="">Escolha um trecho…</option>
              <option v-for="a in alternatives" :key="a.id" :value="a.id">{{ Math.round(a.score) }} · {{ fmtTime(a.start) }} · {{ a.text.slice(0, 70) }}…</option>
            </select>
            <button class="btn-secondary py-2" :disabled="!swapWith || busy" @click="swap"><Replace class="h-4 w-4" /></button>
          </div>
        </div>
      </div>
      <div>
        <span class="label">Critérios da pontuação</span>
        <ScoreBreakdown :scores="clip.scores" />
        <ul v-if="clip.reasons?.length" class="mt-4 space-y-1 text-xs text-ink-400">
          <li v-for="r in clip.reasons" :key="r">• {{ r }}</li>
        </ul>
        <p class="mt-4 text-[11px] leading-relaxed text-ink-500">A pontuação é uma estimativa de qualidade editorial do trecho (clareza, contexto, coerência…). Não é previsão nem garantia de visualizações.</p>
      </div>
    </div>
  </article>
</template>
