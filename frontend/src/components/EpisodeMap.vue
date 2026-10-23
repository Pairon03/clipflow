<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { Map as MapIcon, Plus, Layers, Sparkles, ChevronDown } from 'lucide-vue-next'
import { api } from '../api'
import { fmtTime, toast } from '../utils'

// Mapa do episódio: blocos de assunto/história com nota, resumo e atalhos para criar corte ou série
const props = defineProps({ projectId: { type: String, required: true }, busy: Boolean, version: { type: [String, Number], default: '' } })
const emit = defineEmits(['changed'])

const data = ref(null)
const open = ref(false)
const showAll = ref(false)
const acting = ref(null)

async function load() {
  try { data.value = await api(`/api/projects/${props.projectId}/map`) } catch { data.value = null }
}
onMounted(load)
watch(() => props.version, load)

const ranked = computed(() => (data.value?.blocks || []).slice().sort((a, b) => b.score - a.score))
const visible = computed(() => (showAll.value ? ranked.value : ranked.value.slice(0, 8)))
const used = (b) => b.clips.length > 0
const seriesIn = (b) => b.clips.find((c) => c.series)?.series

function tone(score) {
  if (score >= 80) return 'bg-emerald-400'
  if (score >= 55) return 'bg-brand-400'
  if (score >= 30) return 'bg-amber-400'
  return 'bg-ink-600'
}

async function act(b, kind) {
  acting.value = `${b.index}-${kind}`
  try {
    await api(`/api/projects/${props.projectId}/map/${b.index}/${kind}`, { method: 'POST' })
    toast(kind === 'series' ? 'Série criada nos cortes selecionados' : 'Corte adicionado à seleção', 'success')
    emit('changed')
    await load()
  } catch (e) { toast(e.message, 'error', 7000) } finally { acting.value = null }
}
</script>

<template>
  <section v-if="data && data.blocks.length" class="card p-5">
    <button class="flex w-full items-center justify-between gap-3 text-left" @click="open = !open">
      <span class="flex items-center gap-2 font-medium text-white"><MapIcon class="h-4.5 w-4.5 text-brand-400" /> Mapa do episódio
        <span class="text-xs font-normal text-ink-400">{{ data.blocks.length }} assuntos<span v-if="data.ai"> · avaliado pela IA local</span></span></span>
      <ChevronDown class="h-4 w-4 text-ink-400 transition" :class="{ 'rotate-180': open }" />
    </button>

    <!-- linha do tempo: cada bloco colorido pela nota; bloco com corte ganha marcador -->
    <div class="mt-3 flex h-3 w-full overflow-hidden rounded-full bg-ink-800" role="img" aria-label="Notas dos assuntos ao longo do episódio">
      <div v-for="b in data.blocks" :key="b.index" class="relative h-full border-r border-ink-950/60" :class="tone(b.score)"
           :style="{ width: `${(b.duration / data.duration) * 100}%`, opacity: 0.35 + b.score / 160 }"
           :title="`${fmtTime(b.start)} · ${b.title || b.kind} · nota ${Math.round(b.score)}`">
        <span v-if="used(b)" class="absolute inset-x-0 -bottom-0 h-1 bg-white"></span>
      </div>
    </div>
    <div class="mt-1 flex justify-between text-[11px] text-ink-500"><span>início</span><span>{{ fmtTime(data.duration) }}</span></div>

    <div v-if="open" class="mt-4 space-y-2">
      <p class="text-xs text-ink-400">Os cortes saem dos assuntos com nota mais alta, no máximo um por assunto. Histórias fortes e longas viram série (Parte 1, 2…) automaticamente; nas outras você decide.</p>
      <div v-for="b in visible" :key="b.index" class="flex flex-col gap-2 rounded-xl border border-ink-700 bg-ink-850 p-3 sm:flex-row sm:items-center">
        <div class="w-14 shrink-0 text-center">
          <div class="font-display text-lg font-semibold text-white">{{ Math.round(b.score) }}</div>
          <div class="mx-auto mt-1 h-1 w-10 overflow-hidden rounded-full bg-ink-700"><div class="h-full" :class="tone(b.score)" :style="{ width: `${b.score}%` }"></div></div>
        </div>
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2 text-sm">
            <span class="font-medium text-white">{{ b.title || b.kind }}</span>
            <span class="rounded-md bg-ink-800 px-1.5 py-0.5 text-[11px] text-ink-300">{{ b.kind }}</span>
            <span class="text-xs text-ink-500">{{ fmtTime(b.start) }}–{{ fmtTime(b.end) }} · {{ Math.round(b.duration) }}s</span>
            <span v-if="seriesIn(b)" class="rounded-md bg-red-500/15 px-1.5 py-0.5 text-[11px] text-red-200">Série · {{ seriesIn(b).total }} partes</span>
            <span v-else-if="used(b)" class="rounded-md bg-emerald-500/15 px-1.5 py-0.5 text-[11px] text-emerald-200">{{ b.clips.length }} corte{{ b.clips.length > 1 ? 's' : '' }}</span>
          </div>
          <p v-if="b.summary" class="mt-1 line-clamp-2 text-xs text-ink-400">{{ b.summary }}</p>
          <p v-if="b.ai?.motivo" class="mt-0.5 flex items-center gap-1 text-[11px] text-brand-300"><Sparkles class="h-3 w-3" /> {{ b.ai.motivo }}</p>
        </div>
        <div class="flex shrink-0 gap-1.5">
          <button class="btn-secondary py-1.5 text-xs" :disabled="busy || !!acting" @click="act(b, 'clip')"><Plus class="h-3.5 w-3.5" /> Corte</button>
          <button v-if="b.series_possible" class="btn-secondary py-1.5 text-xs" :disabled="busy || !!acting" @click="act(b, 'series')"
                  :title="`Divide a história em ~${b.parts_estimate} partes que terminam em suspense`">
            <Layers class="h-3.5 w-3.5" /> {{ seriesIn(b) ? 'Refazer série' : `Série (~${b.parts_estimate})` }}
          </button>
        </div>
      </div>
      <button v-if="ranked.length > 8" class="btn-ghost px-0 text-sm" @click="showAll = !showAll">{{ showAll ? 'Mostrar só os 8 melhores' : `Ver todos os ${ranked.length} assuntos` }}</button>
    </div>
  </section>
</template>
