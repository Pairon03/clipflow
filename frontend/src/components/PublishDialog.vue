<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { X, Send, CalendarClock, Youtube, TriangleAlert } from 'lucide-vue-next'
import { api, fileUrl } from '../api'
import { toast } from '../utils'

// Envia um ou vários Shorts para a fila de publicação do YouTube
const props = defineProps({ clips: { type: Array, required: true } })
const emit = defineEmits(['close', 'done'])

const account = ref(null)
const busy = ref(false)
const again = ref(false)
const taken = ref(new Set())          // horários já usados por outros agendamentos
const form = reactive({ mode: 'agendar', startDate: today(), times: '12:00, 19:00', category_id: '24', notify: true })
const items = reactive(props.clips.map((c) => ({ clip: c, title: (c.titles || [])[0] || '', titleIdx: 0 })))

function today() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

onMounted(async () => {
  try {
    account.value = await api('/api/youtube/account')
    form.category_id = account.value.defaults.category_id
    form.notify = account.value.defaults.notify
    form.times = account.value.defaults.times.join(', ')
    const pubs = await api('/api/publications')
    taken.value = new Set(pubs.filter((p) => p.publish_at && ['queued', 'uploading', 'waiting_quota', 'scheduled'].includes(p.status))
      .map((p) => Math.round(p.publish_at / 60)))
  } catch (e) { toast(e.message, 'error') }
})

const times = computed(() => {
  const out = new Set()
  for (const part of form.times.split(/[,;\s]+/)) {
    const m = part.match(/^([01]?\d|2[0-3])[:h]([0-5]\d)?$/)
    if (m) out.add(`${m[1].padStart(2, '0')}:${m[2] || '00'}`)
  }
  return [...out].sort()
})

// próximos horários livres a partir da data escolhida (pelo menos 20 min no futuro)
const slots = computed(() => {
  if (form.mode !== 'agendar' || !times.value.length) return []
  const out = []
  const [y, mo, d] = form.startDate.split('-').map(Number)
  const minTs = Date.now() + 20 * 60 * 1000
  for (let day = 0; out.length < items.length && day < 400; day++) {
    for (const t of times.value) {
      const [h, mi] = t.split(':').map(Number)
      const dt = new Date(y, mo - 1, d + day, h, mi)
      if (dt.getTime() < minTs || taken.value.has(Math.round(dt.getTime() / 60000))) continue
      out.push(dt)
      if (out.length === items.length) break
    }
  }
  return out
})

function fmtSlot(dt) {
  return dt ? dt.toLocaleString('pt-BR', { weekday: 'short', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—'
}

const stale = computed(() => items.filter((i) => i.clip.render_info?.stale).length)

function pickTitle(it, idx) {
  it.titleIdx = idx
  it.title = it.clip.titles[idx]
}

async function submit() {
  if (items.some((i) => !i.title.trim())) return toast('Preencha o título de todos os Shorts', 'error')
  if (form.mode === 'agendar' && slots.value.length < items.length) return toast('Informe horários válidos (ex.: 12:00, 19:00)', 'error')
  busy.value = true
  try {
    const body = {
      items: items.map((it, i) => ({
        clip_id: it.clip.id, title: it.title.trim(),
        publish_at: form.mode === 'agendar' ? slots.value[i].getTime() / 1000 : null,
      })),
      privacy: form.mode === 'agendar' ? 'private' : form.mode,
      category_id: form.category_id, notify: form.notify, again: again.value,
    }
    const res = await api('/api/publish/youtube', { method: 'POST', body })
    toast(res.connected ? `${res.created.length} Short(s) na fila do YouTube` : 'Na fila. Conecte sua conta em Publicar para começar o envio.', 'success', 6000)
    emit('done', res.created)
  } catch (e) {
    toast(e.message, 'error', 8000)
  } finally { busy.value = false }
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 sm:items-center" @click.self="emit('close')">
    <form class="card my-6 w-full max-w-2xl p-5 sm:p-6" @submit.prevent="submit">
      <div class="mb-4 flex items-center justify-between">
        <h2 class="flex items-center gap-2 text-lg font-semibold text-white"><Youtube class="h-5 w-5 text-red-400" /> Publicar no YouTube</h2>
        <button type="button" class="btn-ghost p-2" aria-label="Fechar" @click="emit('close')"><X class="h-4 w-4" /></button>
      </div>

      <div v-if="account && !account.connected" class="mb-4 flex gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
        <TriangleAlert class="mt-0.5 h-4 w-4 shrink-0" />
        <span>Sua conta do YouTube ainda não está conectada. Os vídeos ficam na fila e sobem assim que você conectar em
          <RouterLink to="/publicar" class="underline" @click="emit('close')">Publicar</RouterLink>.</span>
      </div>

      <div class="space-y-3">
        <span class="label">Quando publicar</span>
        <div class="flex flex-wrap gap-2">
          <button v-for="m in [['agendar', 'Agendar'], ['private', 'Privado'], ['unlisted', 'Não listado'], ['public', 'Público agora']]" :key="m[0]"
                  type="button" class="chip py-1.5" :class="{ 'chip-active': form.mode === m[0] }" @click="form.mode = m[0]">{{ m[1] }}</button>
        </div>
        <div v-if="form.mode === 'agendar'" class="grid gap-3 sm:grid-cols-2">
          <label class="text-sm"><span class="label">A partir de</span><input v-model="form.startDate" type="date" class="input" :min="today()" /></label>
          <label class="text-sm"><span class="label">Horários (um vídeo por horário)</span><input v-model="form.times" class="input" placeholder="12:00, 19:00" /></label>
          <p class="text-xs text-ink-500 sm:col-span-2">O vídeo sobe agora como privado e o próprio YouTube publica no horário, mesmo com o PC desligado. Horários já ocupados por outros agendamentos são pulados.</p>
        </div>
      </div>

      <div class="mt-5 space-y-3">
        <span class="label">Shorts ({{ items.length }})</span>
        <div class="max-h-[45vh] space-y-3 overflow-y-auto pr-1">
          <div v-for="(it, i) in items" :key="it.clip.id" class="flex gap-3 rounded-xl border border-ink-700 bg-ink-850 p-3">
            <img v-if="it.clip.has_thumb" :src="fileUrl(`/api/clips/${it.clip.id}/thumb`)" class="h-20 w-12 shrink-0 rounded-md object-cover" alt="" />
            <div class="min-w-0 flex-1 space-y-1.5">
              <input v-model="it.title" class="input py-1.5 text-sm" maxlength="100" :aria-label="`Título do Short ${i + 1}`" />
              <div v-if="(it.clip.titles || []).length > 1" class="flex flex-wrap gap-1">
                <button v-for="(t, k) in it.clip.titles" :key="k" type="button" class="rounded-md px-1.5 py-0.5 text-[11px]"
                        :class="it.titleIdx === k ? 'bg-brand-500/20 text-brand-200' : 'bg-ink-800 text-ink-400 hover:text-ink-200'"
                        :title="t" @click="pickTitle(it, k)">Título {{ k + 1 }}</button>
              </div>
              <div class="flex items-center justify-between gap-2 text-xs text-ink-500">
                <span>{{ it.title.length }}/100 · descrição e tags do corte</span>
                <span v-if="form.mode === 'agendar'" class="flex items-center gap-1 text-ink-300"><CalendarClock class="h-3.5 w-3.5" /> {{ fmtSlot(slots[i]) }}</span>
              </div>
            </div>
          </div>
        </div>
        <p v-if="stale" class="text-xs text-amber-300">{{ stale }} Short(s) têm alterações ainda não renderizadas; vai a versão já renderizada.</p>
      </div>

      <div class="mt-5 grid gap-3 sm:grid-cols-2">
        <label class="text-sm"><span class="label">Categoria</span>
          <select v-model="form.category_id" class="input">
            <option v-for="(name, id) in account?.categories || { 24: 'Entretenimento' }" :key="id" :value="id">{{ name }}</option>
          </select>
        </label>
        <div class="space-y-2 text-sm text-ink-200 sm:pt-6">
          <label class="flex items-center gap-2"><input v-model="form.notify" type="checkbox" class="h-4 w-4 accent-violet-500" /> Notificar inscritos</label>
          <label class="flex items-center gap-2"><input v-model="again" type="checkbox" class="h-4 w-4 accent-violet-500" /> Enviar de novo se já foi publicado</label>
        </div>
      </div>

      <div class="mt-6 flex justify-end gap-2">
        <button type="button" class="btn-ghost" @click="emit('close')">Cancelar</button>
        <button class="btn-primary" :disabled="busy"><Send class="h-4 w-4" /> {{ busy ? 'Enviando…' : form.mode === 'agendar' ? 'Agendar' : 'Colocar na fila' }}</button>
      </div>
    </form>
  </div>
</template>
