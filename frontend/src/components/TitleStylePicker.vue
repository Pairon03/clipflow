<script setup>
import { fileUrl } from '../api'

defineProps({ modelValue: String, compact: Boolean })
const emit = defineEmits(['update:modelValue'])
const styles = [
  { key: 'tweet', name: 'Tweet', desc: 'Cartão com o seu canal' },
  { key: 'caixa', name: 'Caixa', desc: 'Chamada + pergunta' },
  { key: 'citacao', name: 'Citação', desc: 'Frase forte entre aspas' },
  { key: 'variar', name: 'Variar', desc: 'Alterna entre os três' },
  { key: 'nenhum', name: 'Nenhum', desc: 'Sem título' },
]
</script>

<template>
  <div class="grid gap-2" :class="compact ? 'grid-cols-3 sm:grid-cols-5' : 'grid-cols-2 sm:grid-cols-3'">
    <button v-for="s in styles" :key="s.key" type="button" class="overflow-hidden rounded-xl border text-left transition"
            :class="modelValue === s.key ? 'border-brand-500 bg-brand-500/10 ring-1 ring-brand-500/40' : 'border-ink-600 bg-ink-850 hover:border-ink-500'"
            @click="emit('update:modelValue', s.key)">
      <img v-if="['tweet', 'caixa', 'citacao'].includes(s.key)" :src="fileUrl(`/api/branding/preview?style=${s.key}`)" alt=""
           class="aspect-[540/380] w-full bg-ink-800 object-cover" loading="lazy" />
      <div v-else class="flex aspect-[540/380] w-full items-center justify-center bg-ink-800 text-2xl text-ink-400">{{ s.key === 'variar' ? '⟳' : '—' }}</div>
      <div class="p-2">
        <div class="text-sm font-medium text-ink-100">{{ s.name }}</div>
        <div v-if="!compact" class="text-xs text-ink-400">{{ s.desc }}</div>
      </div>
    </button>
  </div>
</template>
