<script setup>
import { onMounted, ref, watch } from 'vue'
import { Plus, Trash2, Save, RotateCcw } from 'lucide-vue-next'
import { api } from '../api'
import { fmtTime, toast } from '../utils'

// Editor das animações de um corte: modo, blocos (início/fim) e cenas (tipo, textos, ícone)
const props = defineProps({ clipId: { type: String, required: true }, busy: Boolean })
const emit = defineEmits(['changed'])

const data = ref(null)
const blocks = ref([])
const mode = ref('projeto')
const saving = ref(false)
const dirty = ref(false)        // cenas mexidas pelo usuário (senão o modo escolhido gera a sugestão de novo)
let loading = false
const KIND_LABEL = { destaque: 'Título + ícone', numero: 'Número', cartoes: 'Cartões', comparacao: 'Comparação' }
const MODES = [['projeto', 'Igual ao projeto'], ['auto', 'Automático'], ['inicio', 'No começo'], ['off', 'Sem animação']]

async function load() {
  data.value = await api(`/api/clips/${props.clipId}/motion`).catch(() => null)
  if (data.value) reset()
}
function reset() {
  loading = true
  mode.value = data.value.mode
  blocks.value = JSON.parse(JSON.stringify(data.value.blocks))
  dirty.value = false
  queueMicrotask(() => { loading = false })
}
watch(blocks, () => { if (!loading) dirty.value = true }, { deep: true })
onMounted(load)

function addBlock() {
  const last = blocks.value[blocks.value.length - 1]
  const start = last ? Math.min(last.end + 4, data.value.duration - 5) : 2
  blocks.value.push({ start, end: start + 5, scenes: [{ kind: 'destaque', at: start, title: '', highlight: '', number: '', icon: 'message-circle', items: [] }] })
}
function addScene(b) {
  const at = b.scenes.length ? Math.min(b.scenes[b.scenes.length - 1].at + 2, b.end - 1) : b.start
  b.scenes.push({ kind: 'destaque', at, title: '', highlight: '', number: '', icon: 'message-circle', items: [] })
}
function itemsText(sc) { return (sc.items || []).map((i) => i.text).join(', ') }
function setItems(sc, txt) {
  const names = txt.split(',').map((t) => t.trim().toUpperCase()).filter(Boolean).slice(0, 3)
  sc.items = names.map((t, k) => ({ text: t, at: (sc.items?.[k]?.at) ?? sc.at + 0.6 + 0.8 * k }))
}

async function save(useAuto = false) {
  saving.value = true
  try {
    const keep = !useAuto && (dirty.value || data.value.edited)
    data.value = await api(`/api/clips/${props.clipId}/motion`, { method: 'PUT', body: { mode: mode.value, blocks: keep ? blocks.value : null } })
    reset()
    toast(useAuto ? 'Voltou para as cenas automáticas' : 'Animações salvas. Renderize o corte de novo para ver.', 'success')
    emit('changed')
  } catch (e) { toast(e.message, 'error') } finally { saving.value = false }
}
</script>

<template>
  <div v-if="data" class="rounded-xl border border-ink-700 bg-ink-850 p-3 text-sm">
    <div class="mb-2 flex flex-wrap items-center justify-between gap-2">
      <span class="label mb-0">Explicação animada</span>
      <span class="text-xs text-ink-500">{{ data.edited ? 'Cenas editadas por você' : 'Sugestão automática (pela fala)' }}</span>
    </div>
    <div class="mb-3 flex flex-wrap gap-1.5">
      <button v-for="m in MODES" :key="m[0]" type="button" class="chip py-1 text-xs" :class="{ 'chip-active': mode === m[0] }" @click="mode = m[0]">{{ m[1] }}</button>
    </div>
    <p v-if="!blocks.length" class="mb-2 text-xs text-ink-500">Nenhum trecho animado sugerido neste corte. Adicione um bloco, se quiser.</p>
    <div v-for="(b, bi) in blocks" :key="bi" class="mb-3 rounded-lg border border-ink-700 p-2.5">
      <div class="mb-2 flex flex-wrap items-center gap-2 text-xs text-ink-300">
        <span class="font-medium text-white">Bloco {{ bi + 1 }}</span>
        <label>de <input v-model.number="b.start" type="number" step="0.1" min="0" :max="data.duration" class="input w-20 px-2 py-1 text-xs" /> s</label>
        <label>até <input v-model.number="b.end" type="number" step="0.1" min="0" :max="data.duration" class="input w-20 px-2 py-1 text-xs" /> s</label>
        <span class="text-ink-500">({{ fmtTime(b.start) }}–{{ fmtTime(b.end) }} do corte)</span>
        <button type="button" class="btn-ghost ml-auto p-1 text-red-300" aria-label="Remover bloco" @click="blocks.splice(bi, 1)"><Trash2 class="h-3.5 w-3.5" /></button>
      </div>
      <div v-for="(sc, si) in b.scenes" :key="si" class="mb-2 grid gap-1.5 rounded-md bg-ink-900/60 p-2 sm:grid-cols-6">
        <select v-model="sc.kind" class="input py-1 text-xs sm:col-span-2">
          <option v-for="k in data.kinds" :key="k" :value="k">{{ KIND_LABEL[k] || k }}</option>
        </select>
        <label class="flex items-center gap-1 text-xs text-ink-400">aos <input v-model.number="sc.at" type="number" step="0.1" class="input w-16 px-2 py-1 text-xs" /> s</label>
        <select v-model="sc.icon" class="input py-1 text-xs sm:col-span-2" aria-label="Ícone">
          <option v-for="i in data.icons" :key="i" :value="i">{{ i }}</option>
        </select>
        <button type="button" class="btn-ghost justify-self-end p-1 text-red-300" aria-label="Remover cena" @click="b.scenes.splice(si, 1)"><Trash2 class="h-3.5 w-3.5" /></button>
        <input v-model="sc.title" class="input py-1 text-xs uppercase sm:col-span-3" maxlength="24" placeholder="Título" />
        <input v-if="sc.kind === 'destaque' || sc.kind === 'numero' || sc.kind === 'comparacao'" v-model="sc.highlight" class="input py-1 text-xs uppercase sm:col-span-2" maxlength="22" placeholder="Destaque" />
        <input v-if="sc.kind === 'numero'" v-model="sc.number" class="input py-1 text-xs" maxlength="6" placeholder="Nº" />
        <input v-if="sc.kind === 'cartoes' || sc.kind === 'comparacao'" :value="itemsText(sc)" class="input py-1 text-xs uppercase sm:col-span-3"
               :placeholder="sc.kind === 'comparacao' ? 'Antes, Depois' : 'Nomes, separados por vírgula'" @change="setItems(sc, $event.target.value)" />
      </div>
      <button type="button" class="btn-ghost px-1 text-xs" @click="addScene(b)"><Plus class="h-3.5 w-3.5" /> Cena</button>
    </div>
    <div class="flex flex-wrap gap-2">
      <button type="button" class="btn-secondary py-1.5 text-xs" @click="addBlock"><Plus class="h-3.5 w-3.5" /> Bloco</button>
      <button type="button" class="btn-primary py-1.5 text-xs" :disabled="saving || busy" @click="save(false)"><Save class="h-3.5 w-3.5" /> Salvar cenas</button>
      <button v-if="data.edited" type="button" class="btn-ghost py-1.5 text-xs" :disabled="saving || busy" @click="save(true)"><RotateCcw class="h-3.5 w-3.5" /> Voltar à sugestão</button>
    </div>
    <p class="mt-2 text-xs text-ink-500">Use só palavras que aparecem na fala. Tempos em segundos a partir do início do corte.</p>
  </div>
</template>
