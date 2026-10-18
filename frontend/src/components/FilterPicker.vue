<script setup>
import { reactive } from 'vue'
import { fileUrl } from '../api'

const props = defineProps({ modelValue: String, projectId: String, wide: Boolean })
const emit = defineEmits(['update:modelValue'])
const filters = [
  { key: 'nenhum', name: 'Original', swatch: 'linear-gradient(135deg,#52525b,#a1a1aa)' },
  { key: 'vivo', name: 'Vivo', swatch: 'linear-gradient(135deg,#f97316,#22c55e)' },
  { key: 'quente', name: 'Quente', swatch: 'linear-gradient(135deg,#b45309,#fbbf24)' },
  { key: 'frio', name: 'Frio', swatch: 'linear-gradient(135deg,#1e3a8a,#7dd3fc)' },
  { key: 'cinema', name: 'Cinema', swatch: 'linear-gradient(135deg,#0f766e,#fb923c)' },
  { key: 'vintage', name: 'Vintage', swatch: 'linear-gradient(135deg,#78350f,#d6b98c)' },
  { key: 'pb', name: 'P&B', swatch: 'linear-gradient(135deg,#111,#e5e5e5)' },
]
// sem vídeo para a prévia (nenhum projeto ainda), mostra só a cor de referência
const failed = reactive({})
const src = (k) => fileUrl(`/api/filters/preview?name=${k}${props.projectId ? `&project_id=${props.projectId}` : ''}`)
</script>

<template>
  <div class="grid grid-cols-4 gap-2" :class="{ 'sm:grid-cols-7': wide }">
    <button v-for="f in filters" :key="f.key" type="button" class="overflow-hidden rounded-xl border text-left transition"
            :class="modelValue === f.key ? 'border-brand-500 bg-brand-500/10 ring-1 ring-brand-500/40' : 'border-ink-600 bg-ink-850 hover:border-ink-500'"
            @click="emit('update:modelValue', f.key)">
      <img v-if="!failed[f.key]" :src="src(f.key)" alt="" class="aspect-[9/16] w-full bg-ink-800 object-cover" loading="lazy"
           @error="failed[f.key] = true" />
      <div v-else class="aspect-[9/16] w-full" :style="{ background: f.swatch }" />
      <div class="truncate px-2 py-1.5 text-xs font-medium text-ink-100">{{ f.name }}</div>
    </button>
  </div>
</template>
