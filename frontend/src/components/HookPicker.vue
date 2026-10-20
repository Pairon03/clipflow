<script setup>
import { computed } from 'vue'
import { fmtTime } from '../utils'

// candidatos a gancho de um corte (clip.hook, vindo de pipeline/hooks.py) e a escolha manual
const props = defineProps({ hook: Object, clipStart: Number, disabled: Boolean })
const emit = defineEmits(['choose'])
const LABELS = { curiosidade: 'Curiosidade', clareza: 'Clareza', impacto: 'Impacto', relevancia: 'Relevância',
  continuidade: 'Continuidade', fidelidade: 'Fidelidade', payoff: 'Payoff' }
const current = computed(() => {
  const h = props.hook
  if (!h) return null
  if (h.choice === 'none') return 'none'
  return Number.isInteger(h.choice) ? h.choice : (h.chosen ?? 'none')
})
const isAuto = computed(() => props.hook && (props.hook.choice === null || props.hook.choice === undefined))
const engineLabel = computed(() => props.hook?.engine === 'ollama+heuristica' ? 'IA local + regras' : 'regras')
</script>

<template>
  <div v-if="hook" class="space-y-2">
    <p class="text-xs text-ink-500">
      Avaliado por {{ engineLabel }}. A frase abre o vídeo e volta no lugar original, já com contexto.
      <span v-if="hook.reason"> {{ hook.reason }}.</span>
    </p>
    <ul class="space-y-1.5">
      <li v-for="(c, i) in hook.candidates" :key="i">
        <button type="button" class="w-full rounded-lg border px-3 py-2 text-left text-sm transition disabled:opacity-60"
                :class="current === i ? 'border-brand-500 bg-brand-500/10' : 'border-ink-700 bg-ink-850 hover:border-ink-500'"
                :disabled="disabled" @click="emit('choose', i)">
          <span class="flex items-baseline justify-between gap-3">
            <span class="text-ink-100">“{{ c.clean }}”</span>
            <span class="shrink-0 font-mono text-xs" :class="c.usable ? 'text-emerald-300' : 'text-ink-500'">{{ c.total.toFixed(1) }}</span>
          </span>
          <span class="mt-1 block text-[11px] text-ink-500">
            {{ fmtTime(c.start - clipStart) }} no corte · payoff com {{ Math.round(c.payoff.context_s) }} s de contexto antes
            <span v-if="!c.usable"> · abaixo da nota mínima</span>
          </span>
          <span class="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-ink-400">
            <span v-for="(v, k) in c.scores" :key="k">{{ LABELS[k] }} {{ v.toFixed(1) }}</span>
          </span>
          <span v-if="c.reason_ai" class="mt-1 block text-[11px] italic text-ink-400">IA: {{ c.reason_ai }}</span>
        </button>
      </li>
    </ul>
    <div class="flex flex-wrap gap-2">
      <button type="button" class="chip py-1.5" :class="{ 'chip-active': isAuto }" :disabled="disabled" @click="emit('choose', 'auto')">Automático</button>
      <button type="button" class="chip py-1.5" :class="{ 'chip-active': hook.choice === 'none' }" :disabled="disabled" @click="emit('choose', 'none')">Sem gancho</button>
    </div>
  </div>
  <p v-else class="text-xs text-ink-500">Os ganchos são avaliados na análise ou no primeiro render deste corte.</p>
</template>
