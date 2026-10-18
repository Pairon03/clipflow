<script setup>
import { computed } from 'vue'
import { STATUS } from '../utils'

const props = defineProps({ status: String })
const info = computed(() => STATUS[props.status] || { label: props.status, tone: 'slate' })
const tones = {
  slate: 'bg-ink-700/60 text-ink-200 ring-ink-500/30',
  sky: 'bg-sky-500/15 text-sky-300 ring-sky-400/30',
  violet: 'bg-brand-500/15 text-brand-300 ring-brand-400/30',
  amber: 'bg-amber-500/15 text-amber-300 ring-amber-400/30',
  emerald: 'bg-emerald-500/15 text-emerald-300 ring-emerald-400/30',
  red: 'bg-red-500/15 text-red-300 ring-red-400/30',
}
</script>

<template>
  <span class="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ring-1" :class="tones[info.tone]">
    <span v-if="['sky', 'violet'].includes(info.tone)" class="h-1.5 w-1.5 animate-pulse rounded-full bg-current"></span>
    {{ info.label }}
  </span>
</template>
