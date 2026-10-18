<script setup>
defineProps({ value: { type: Number, default: 0 }, size: { type: String, default: 'md' } })
</script>

<template>
  <div class="w-full overflow-hidden rounded-full bg-ink-700/70" :class="size === 'sm' ? 'h-1.5' : 'h-2.5'"
       role="progressbar" :aria-valuenow="Math.round(value * 100)" aria-valuemin="0" aria-valuemax="100">
    <div class="h-full rounded-full bg-gradient-to-r from-brand-500 to-sky-brand transition-[width] duration-500"
         :style="{ width: `${Math.max(2, Math.min(100, value * 100))}%` }"></div>
  </div>
</template>
