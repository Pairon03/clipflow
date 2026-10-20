<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Save, RotateCcw } from 'lucide-vue-next'
import { api } from '../api'
import { toast } from '../utils'
import EditingOptions from '../components/EditingOptions.vue'
import { applyPreferences, preferencesFrom, DURATION_PRESETS, COUNT_PRESETS } from '../preferences'

// mesmos valores iniciais de "Criar Shorts"; as preferências salvas sobrescrevem
const defaults = () => ({
  count: 5, customCount: 7, durationPreset: '30-60', minDuration: 30, maxDuration: 60,
  caption_style: 'classic', layout: 'auto', engine: 'ffmpeg', hook: true, zoom: true, pace: 'tiktok', speed: 1.0,
  title_style: 'tweet', title_duration: 'inteiro', title_position: 'meio', cold_open: true, color_filter: 'nenhum',
  transition: 'zoom', zoom_fx: true, flip_fx: true, sfx: 'sutil', censor: 'mudo',
})
const form = reactive(defaults())
const meta = ref(null)
const saved = ref(false)
const saving = ref(false)
const count = computed(() => (form.count === 'custom' ? Number(form.customCount) : form.count))
const durations = computed(() => form.durationPreset === 'custom'
  ? [Number(form.minDuration), Number(form.maxDuration)] : DURATION_PRESETS[form.durationPreset])

onMounted(async () => {
  meta.value = await api('/api/meta').catch(() => null)
  const prefs = await api('/api/preferences').catch(() => null)
  saved.value = !!prefs?.saved
  applyPreferences(form, prefs?.options)
})

async function save() {
  saving.value = true
  try {
    await api('/api/preferences', { method: 'PUT', body: { options: preferencesFrom(form, count.value, durations.value) } })
    saved.value = true
    toast('Preferências salvas. Os próximos projetos já começam assim.', 'success')
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    saving.value = false
  }
}
async function reset() {
  await api('/api/preferences', { method: 'DELETE' }).catch(() => null)
  Object.assign(form, defaults())
  saved.value = false
  toast('Preferências voltaram ao padrão do app', 'success')
}
</script>

<template>
  <div class="mx-auto max-w-3xl space-y-6">
    <div>
      <h1 class="font-display text-2xl font-semibold text-white">Preferências de edição</h1>
      <p class="mt-1 text-sm text-ink-400">O jeito padrão de editar os seus Shorts. Todo projeto novo já começa com estas escolhas; dá para mudar caso a caso em "Criar Shorts" ou no painel do projeto.</p>
    </div>

    <section class="card space-y-6 p-6">
      <div>
        <span class="label">Quantidade de Shorts</span>
        <div class="flex flex-wrap gap-2">
          <button v-for="n in COUNT_PRESETS" :key="n" class="chip" :class="{ 'chip-active': form.count === n }" @click="form.count = n">{{ n }}</button>
          <button class="chip" :class="{ 'chip-active': form.count === 'custom' }" @click="form.count = 'custom'">Personalizado</button>
          <input v-if="form.count === 'custom'" id="pref-count" v-model.number="form.customCount" type="number" min="1" :max="meta?.max_clips || 20" class="input w-24" aria-label="Quantidade personalizada" />
        </div>
      </div>
      <div>
        <span class="label">Duração</span>
        <div class="flex flex-wrap gap-2">
          <button v-for="(v, k) in DURATION_PRESETS" :key="k" class="chip" :class="{ 'chip-active': form.durationPreset === k }" @click="form.durationPreset = k">{{ v[0] }}–{{ v[1] }}s</button>
          <button class="chip" :class="{ 'chip-active': form.durationPreset === 'custom' }" @click="form.durationPreset = 'custom'">Personalizada</button>
        </div>
        <div v-if="form.durationPreset === 'custom'" class="mt-3 flex items-center gap-2 text-sm text-ink-300">
          <input id="pref-min" v-model.number="form.minDuration" type="number" min="5" :max="meta?.max_clip_seconds || 180" class="input w-24" aria-label="Duração mínima" /> a
          <input id="pref-max" v-model.number="form.maxDuration" type="number" min="10" :max="meta?.max_clip_seconds || 180" class="input w-24" aria-label="Duração máxima" /> segundos
        </div>
      </div>
      <EditingOptions :form="form" :meta="meta" wide />
    </section>

    <div class="flex flex-wrap items-center justify-end gap-3">
      <span v-if="saved" class="mr-auto text-xs text-ink-500">Usando as suas preferências salvas.</span>
      <button class="btn-ghost" :disabled="saving" @click="reset"><RotateCcw class="h-4 w-4" /> Voltar ao padrão do app</button>
      <button class="btn-primary" :disabled="saving" @click="save"><Save class="h-4 w-4" /> Salvar preferências</button>
    </div>
  </div>
</template>
