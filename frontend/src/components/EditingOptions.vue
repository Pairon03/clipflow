<script setup>
// opções de edição de um projeto (legenda, enquadramento, ritmo, título, filtro, efeitos e motor).
// Usado em "Criar Shorts" e na aba "Preferências"; edita direto o objeto recebido.
import { Captions } from 'lucide-vue-next'
import { CAPTION_LABELS, LAYOUT_LABELS } from '../utils'
import TitleStylePicker from './TitleStylePicker.vue'
import FilterPicker from './FilterPicker.vue'
import EffectsOptions from './EffectsOptions.vue'

defineProps({ form: { type: Object, required: true }, meta: Object, wide: Boolean })
</script>

<template>
  <div class="space-y-6">
    <div>
      <span class="label flex items-center gap-1.5"><Captions class="h-3.5 w-3.5" /> Legendas</span>
      <div class="grid grid-cols-2 gap-2">
        <button v-for="(c, key) in CAPTION_LABELS" :key="key" class="rounded-xl border p-3 text-left transition"
                :class="form.caption_style === key ? 'border-brand-500 bg-brand-500/10 ring-1 ring-brand-500/40' : 'border-ink-600 bg-ink-850 hover:border-ink-500'"
                @click="form.caption_style = key">
          <div class="rounded-lg bg-black/60 px-2 py-2 text-center text-sm font-extrabold tracking-wide" :class="{ italic: c.italic }" :style="{ fontFamily: c.font === 'Anton' ? 'Impact, Anton, sans-serif' : 'inherit' }">
            <span :style="{ color: c.base || '#fff', textShadow: key === 'minimal' ? '0 2px 4px #000' : '0 0 3px #000, 0 0 3px #000' }">ISSO </span>
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
      <span class="label">Ritmo</span>
      <div class="grid grid-cols-2 gap-2">
        <button class="rounded-xl border p-3 text-left transition" :class="form.pace === 'tiktok' ? 'border-brand-500 bg-brand-500/10 ring-1 ring-brand-500/40' : 'border-ink-600 bg-ink-850 hover:border-ink-500'" @click="form.pace = 'tiktok'">
          <div class="text-sm font-medium text-ink-100">TikTok</div>
          <div class="text-xs text-ink-400">Corta respirações e silêncios entre as falas</div>
        </button>
        <button class="rounded-xl border p-3 text-left transition" :class="form.pace === 'natural' ? 'border-brand-500 bg-brand-500/10 ring-1 ring-brand-500/40' : 'border-ink-600 bg-ink-850 hover:border-ink-500'" @click="form.pace = 'natural'">
          <div class="text-sm font-medium text-ink-100">Natural</div>
          <div class="text-xs text-ink-400">Só remove pausas longas</div>
        </button>
      </div>
      <div class="mt-3 flex flex-wrap items-center gap-2">
        <span class="text-xs text-ink-400">Velocidade:</span>
        <button v-for="v in [1.0, 1.1, 1.2]" :key="v" class="chip py-1.5" :class="{ 'chip-active': form.speed === v }" @click="form.speed = v">{{ v.toFixed(1) }}x</button>
      </div>
      <div class="mt-3 space-y-2 text-sm">
        <label class="flex items-center justify-between gap-3"><span class="text-ink-200">Gancho: começar pela fala mais forte</span><input v-model="form.cold_open" type="checkbox" class="h-4 w-4 accent-violet-500" /></label>
      </div>
    </div>

    <div>
      <span class="label">Título (chamada do vídeo)</span>
      <TitleStylePicker v-model="form.title_style" />
      <div v-if="form.title_style !== 'nenhum'" class="mt-3 flex flex-wrap items-center gap-2">
        <span class="text-xs text-ink-400">Mostrar:</span>
        <button class="chip py-1.5" :class="{ 'chip-active': form.title_duration === 'inteiro' }" @click="form.title_duration = 'inteiro'">Vídeo inteiro</button>
        <button class="chip py-1.5" :class="{ 'chip-active': form.title_duration === 'inicio' }" @click="form.title_duration = 'inicio'">Só no início</button>
      </div>
      <div v-if="form.title_style !== 'nenhum'" class="mt-2 flex flex-wrap items-center gap-2">
        <span class="text-xs text-ink-400">Posição:</span>
        <button class="chip py-1.5" :class="{ 'chip-active': form.title_position === 'topo' }" @click="form.title_position = 'topo'">Topo</button>
        <button class="chip py-1.5" :class="{ 'chip-active': form.title_position === 'meio' }" @click="form.title_position = 'meio'">Meio da tela</button>
      </div>
    </div>

    <div>
      <span class="label">Filtro de cor</span>
      <FilterPicker v-model="form.color_filter" :wide="wide" />
    </div>

    <div>
      <span class="label">Efeitos</span>
      <EffectsOptions :opts="form" :has-hook="form.cold_open" :wide="wide" />
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
  </div>
</template>
