<script setup>
import { SCORE_LABELS } from '../utils'
defineProps({ scores: { type: Object, default: () => ({}) } })
</script>

<template>
  <ul class="space-y-1.5">
    <li v-for="(v, k) in scores" :key="k" class="grid grid-cols-[1fr_5rem_2rem] items-center gap-2 text-xs">
      <span class="truncate text-ink-400">{{ SCORE_LABELS[k] || k }}</span>
      <span class="h-1.5 overflow-hidden rounded-full bg-ink-700">
        <span class="block h-full rounded-full" :class="v >= 0.75 ? 'bg-emerald-400' : v >= 0.5 ? 'bg-amber-400' : 'bg-red-400'" :style="{ width: `${v * 100}%` }"></span>
      </span>
      <span class="text-right tabular-nums text-ink-300">{{ Math.round(v * 100) }}</span>
    </li>
  </ul>
</template>
