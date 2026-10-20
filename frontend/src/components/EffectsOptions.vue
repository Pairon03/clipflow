<script setup>
// edita os campos de efeitos direto no objeto de opções recebido (formulário do projeto)
defineProps({ opts: { type: Object, required: true }, hasHook: { type: Boolean, default: true }, wide: Boolean })
const transitions = [
  { key: 'zoom', name: 'Zoom' },
  { key: 'flash', name: 'Flash' },
  { key: 'fade', name: 'Escurecer' },
  { key: 'nenhuma', name: 'Nenhuma' },
]
const sfxLevels = [
  { key: 'sutil', name: 'Sutil' },
  { key: 'normal', name: 'Normal' },
  { key: 'nenhum', name: 'Desligado' },
]
const censors = [
  { key: 'mudo', name: 'Mutar' },
  { key: 'bip', name: 'Bipe' },
  { key: 'nenhum', name: 'Manter' },
]
</script>

<template>
  <div class="grid gap-4 text-sm" :class="{ 'sm:grid-cols-2': wide }">
    <div>
      <span class="label">Transição depois do gancho</span>
      <div class="flex flex-wrap gap-2">
        <button v-for="t in transitions" :key="t.key" type="button" class="chip py-1.5" :class="{ 'chip-active': opts.transition === t.key }"
                :disabled="!hasHook" @click="opts.transition = t.key">{{ t.name }}</button>
      </div>
      <p v-if="!hasHook" class="mt-1 text-xs text-ink-500">Ative o gancho para usar a transição.</p>
    </div>
    <div>
      <span class="label">Efeitos sonoros</span>
      <div class="flex flex-wrap gap-2">
        <button v-for="s in sfxLevels" :key="s.key" type="button" class="chip py-1.5" :class="{ 'chip-active': opts.sfx === s.key }" @click="opts.sfx = s.key">{{ s.name }}</button>
      </div>
      <p class="mt-1 text-xs text-ink-500">Whoosh na transição e um "pop" leve no título e nos zooms.</p>
    </div>
    <div>
      <span class="label">Palavrões</span>
      <div class="flex flex-wrap gap-2">
        <button v-for="c in censors" :key="c.key" type="button" class="chip py-1.5" :class="{ 'chip-active': opts.censor === c.key }" @click="opts.censor = c.key">{{ c.name }}</button>
      </div>
      <p class="mt-1 text-xs text-ink-500">Silencia o áudio e troca por p**** na legenda e nos títulos.</p>
    </div>
    <label class="flex items-center justify-between gap-3 text-ink-200" :class="{ 'self-end pb-1': wide }">
      <span>Zoom nos momentos mais fortes<span class="block text-xs text-ink-500">No máximo um a cada ~8 s</span></span>
      <input v-model="opts.zoom_fx" type="checkbox" class="h-4 w-4 accent-violet-500" />
    </label>
    <label class="flex items-center justify-between gap-3 text-ink-200" :class="{ 'self-end pb-1': wide }">
      <span>Inversão momentânea da imagem<span class="block text-xs text-ink-500">Espelha por ~1 s e volta; uma vez por vídeo</span></span>
      <input v-model="opts.flip_fx" type="checkbox" class="h-4 w-4 accent-violet-500" />
    </label>
  </div>
</template>
