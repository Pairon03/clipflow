<script setup>
defineProps({ label: String, value: [String, Number], hint: String, icon: Object, accent: { type: String, default: 'brand' } })
</script>

<template>
  <div class="card p-5">
    <div class="flex items-start justify-between gap-3">
      <div class="text-xs font-medium uppercase tracking-wide text-ink-400">{{ label }}</div>
      <div v-if="icon" class="rounded-lg p-2" :class="accent === 'sky' ? 'bg-sky-brand/15 text-sky-300' : 'bg-brand-500/15 text-brand-300'">
        <component :is="icon" class="h-4 w-4" />
      </div>
    </div>
    <div class="mt-2 font-display text-3xl font-semibold tabular-nums text-white">{{ value }}</div>
    <div v-if="hint" class="mt-1 text-xs text-ink-400">{{ hint }}</div>
  </div>
</template>
