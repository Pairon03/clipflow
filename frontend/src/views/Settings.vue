<script setup>
import { onMounted, ref } from 'vue'
import { CheckCircle2, XCircle, Save, RefreshCw, Cpu, Brain, ScanFace, Film, Gauge, BadgeCheck, Upload, Trash2 } from 'lucide-vue-next'
import { api, auth, fileUrl } from '../api'
import { toast } from '../utils'

const status = ref(null)
const settings = ref(null)
const form = ref({})
const saving = ref(false)
const previewKey = ref(Date.now())
const hasAvatar = ref(false)
async function loadBranding() {
  const b = await api('/api/branding').catch(() => null)
  hasAvatar.value = !!b?.has_avatar
}
async function uploadAvatar(file) {
  if (!file) return
  try {
    const headers = { 'Content-Type': 'application/octet-stream' }
    if (auth.token) headers.Authorization = `Bearer ${auth.token}`
    const res = await fetch('/api/branding/avatar', { method: 'PUT', headers, body: file })
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Falha no envio')
    toast('Logo atualizada', 'success')
    hasAvatar.value = true
    previewKey.value = Date.now()
  } catch (e) { toast(e.message, 'error') }
}
async function removeAvatar() {
  await api('/api/branding/avatar', { method: 'DELETE' }).catch(() => {})
  hasAvatar.value = false
  previewKey.value = Date.now()
}

async function load() {
  const [s, cfg] = await Promise.all([api('/api/system/status'), api('/api/settings')]).catch((e) => { toast(e.message, 'error'); return [null, null] })
  status.value = s
  settings.value = cfg
  if (cfg) {
    const f = {}
    for (const key of cfg.editable) {
      const [sec, name] = key.split('.')
      f[key] = cfg.values[sec][name]
    }
    form.value = f
  }
}
onMounted(() => { load(); loadBranding() })

async function save() {
  saving.value = true
  try {
    settings.value = await api('/api/settings', { method: 'PUT', body: { values: form.value } })
    toast('Configurações salvas', 'success')
    status.value = await api('/api/system/status')
    previewKey.value = Date.now()
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    saving.value = false
  }
}

const models = [
  { v: 'tiny', d: 'Mais rápido, menos preciso (~1 GB RAM)' },
  { v: 'base', d: 'Rápido (~1 GB RAM)' },
  { v: 'small', d: 'Equilíbrio recomendado (~2 GB RAM)' },
  { v: 'medium', d: 'Mais preciso, lento em CPU (~5 GB RAM)' },
  { v: 'large-v3-turbo', d: 'Alta precisão, ideal com GPU NVIDIA (~6 GB)' },
  { v: 'large-v3', d: 'Máxima precisão, exige GPU (~10 GB)' },
]
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="page-title">Configurações</h1>
      <p class="mt-1 text-ink-400">Ajuste o processamento ao seu computador. Tudo roda localmente, sem custos de API.</p>
    </div>

    <section v-if="status" class="card p-6">
      <div class="mb-4 flex items-center justify-between">
        <h2 class="font-display text-lg font-semibold text-white">Verificação do sistema</h2>
        <button class="btn-ghost text-xs" @click="load"><RefreshCw class="h-3.5 w-3.5" /> Verificar de novo</button>
      </div>
      <ul class="grid gap-3 md:grid-cols-2">
        <li class="flex items-start gap-3 rounded-xl bg-ink-850 p-4">
          <component :is="status.ffmpeg.ffmpeg && status.ffmpeg.libass ? CheckCircle2 : XCircle" class="mt-0.5 h-5 w-5 shrink-0" :class="status.ffmpeg.ffmpeg && status.ffmpeg.libass ? 'text-emerald-400' : 'text-red-400'" />
          <div class="text-sm"><div class="font-medium text-white">FFmpeg</div><div class="text-ink-400">{{ status.ffmpeg.version || 'Não encontrado — instale e adicione ao PATH' }}</div><div v-if="status.ffmpeg.ffmpeg && !status.ffmpeg.libass" class="text-red-300">Sem libass: legendas não funcionarão (use a build "full" do FFmpeg)</div></div>
        </li>
        <li class="flex items-start gap-3 rounded-xl bg-ink-850 p-4">
          <component :is="status.whisper.installed ? CheckCircle2 : XCircle" class="mt-0.5 h-5 w-5 shrink-0" :class="status.whisper.installed ? 'text-emerald-400' : 'text-red-400'" />
          <div class="text-sm"><div class="font-medium text-white">Transcrição (faster-whisper)</div><div class="text-ink-400">Modelo {{ status.whisper.model }} — {{ status.whisper.model_cached ? 'já baixado' : 'será baixado no primeiro uso (precisa de internet)' }}</div></div>
        </li>
        <li class="flex items-start gap-3 rounded-xl bg-ink-850 p-4">
          <component :is="status.face_detector ? CheckCircle2 : XCircle" class="mt-0.5 h-5 w-5 shrink-0" :class="status.face_detector ? 'text-emerald-400' : 'text-amber-400'" />
          <div class="text-sm"><div class="font-medium text-white">Detecção de rostos</div><div class="text-ink-400">{{ status.face_detector === 'mediapipe' ? 'MediaPipe (BlazeFace) + OpenCV' : status.face_detector === 'haar' ? 'OpenCV Haar (MediaPipe indisponível)' : 'Indisponível — usará corte central' }}</div></div>
        </li>
        <li class="flex items-start gap-3 rounded-xl bg-ink-850 p-4">
          <component :is="status.ollama.reachable && status.ollama.model_installed ? CheckCircle2 : XCircle" class="mt-0.5 h-5 w-5 shrink-0" :class="status.ollama.reachable && status.ollama.model_installed ? 'text-emerald-400' : 'text-ink-500'" />
          <div class="text-sm"><div class="font-medium text-white">IA local (Ollama) — opcional</div>
            <div class="text-ink-400">{{ !status.ollama.enabled ? 'Desativada — usando o motor heurístico local' : !status.ollama.reachable ? 'Ativada, mas o Ollama não respondeu em ' + status.ollama.url : status.ollama.model_installed ? 'Pronta com ' + status.ollama.model : 'Modelo ' + status.ollama.model + ' não instalado (ollama pull ' + status.ollama.model + ')' }}</div></div>
        </li>
        <li class="flex items-start gap-3 rounded-xl bg-ink-850 p-4">
          <component :is="status.yt_dlp ? CheckCircle2 : XCircle" class="mt-0.5 h-5 w-5 shrink-0" :class="status.yt_dlp ? 'text-emerald-400' : 'text-red-400'" />
          <div class="text-sm"><div class="font-medium text-white">yt-dlp</div><div class="text-ink-400">{{ status.yt_dlp ? 'Versão ' + status.yt_dlp + ' — mantenha atualizado (pip install -U yt-dlp)' : 'Não instalado' }}</div></div>
        </li>
        <li class="flex items-start gap-3 rounded-xl bg-ink-850 p-4">
          <component :is="status.concat?.path ? CheckCircle2 : XCircle" class="mt-0.5 h-5 w-5 shrink-0" :class="status.concat?.path ? 'text-emerald-400' : 'text-ink-500'" />
          <div class="min-w-0 text-sm"><div class="font-medium text-white">Editor Concat — opcional</div><div class="break-all text-ink-400">{{ status.concat?.path || 'Não encontrado. Instale em concatenate.pages.dev ou informe o caminho abaixo.' }}</div></div>
        </li>
        <li class="flex items-start gap-3 rounded-xl bg-ink-850 p-4">
          <CheckCircle2 class="mt-0.5 h-5 w-5 shrink-0 text-emerald-400" />
          <div class="min-w-0 text-sm"><div class="font-medium text-white">Pasta de dados</div><div class="break-all text-ink-400">{{ status.data_dir }}</div></div>
        </li>
      </ul>
    </section>

    <form v-if="settings" class="grid gap-6 lg:grid-cols-2" @submit.prevent="save">
      <section class="card space-y-4 p-6 lg:col-span-2">
        <h2 class="flex items-center gap-2 font-display text-lg font-semibold text-white"><BadgeCheck class="h-5 w-5 text-brand-400" /> Seu canal (título estilo tweet)</h2>
        <div class="grid gap-6 md:grid-cols-2">
          <div class="space-y-4">
            <div class="grid grid-cols-2 gap-4">
              <div><label class="label" for="bname">Nome do canal</label><input id="bname" v-model="form['branding.channel_name']" class="input" maxlength="40" placeholder="Cortes do Pairon" /></div>
              <div><label class="label" for="bhandle">@ do canal</label><input id="bhandle" v-model="form['branding.channel_handle']" class="input" maxlength="40" placeholder="@cortesdopairon" /></div>
            </div>
            <div>
              <span class="label">Texto do tweet</span>
              <div class="mb-2 flex gap-2">
                <button type="button" class="chip py-1.5" :class="{ 'chip-active': form['branding.tweet_mode'] === 'fixo' }" @click="form['branding.tweet_mode'] = 'fixo'">Frase fixa do canal</button>
                <button type="button" class="chip py-1.5" :class="{ 'chip-active': form['branding.tweet_mode'] === 'resumo' }" @click="form['branding.tweet_mode'] = 'resumo'">Resumo de cada corte</button>
              </div>
              <input v-if="form['branding.tweet_mode'] === 'fixo'" v-model="form['branding.tweet_text']" class="input" maxlength="140" placeholder="Você achou a melhor página de cortes do TikTok" />
            </div>
            <div>
              <span class="label">Logo (aparece redonda no cartão)</span>
              <div class="flex items-center gap-3">
                <img v-if="hasAvatar" :src="fileUrl(`/api/branding/avatar?k=${previewKey}`)" class="h-14 w-14 rounded-full object-cover ring-1 ring-ink-600" alt="" />
                <label class="btn-secondary cursor-pointer text-xs"><Upload class="h-3.5 w-3.5" /> Enviar logo <input type="file" accept="image/png,image/jpeg,image/webp" class="hidden" @change="uploadAvatar($event.target.files[0])" /></label>
                <button v-if="hasAvatar" type="button" class="btn-ghost text-xs" @click="removeAvatar"><Trash2 class="h-3.5 w-3.5" /> Remover</button>
              </div>
            </div>
            <p class="text-xs text-ink-500">O cartão usa sempre a identidade do <b>seu</b> canal — nunca a do convidado — para não parecer uma postagem real de outra pessoa. Salve para atualizar a prévia.</p>
          </div>
          <div>
            <span class="label">Prévia</span>
            <img :src="fileUrl(`/api/branding/preview?style=tweet&k=${previewKey}`)" class="w-full rounded-xl ring-1 ring-ink-700" alt="Prévia do cartão" />
          </div>
        </div>
      </section>

      <section class="card space-y-4 p-6">
        <h2 class="flex items-center gap-2 font-display text-lg font-semibold text-white"><Brain class="h-5 w-5 text-brand-400" /> Transcrição</h2>
        <div>
          <label class="label" for="model">Modelo Whisper</label>
          <select id="model" v-model="form['transcription.model']" class="input">
            <option v-for="m in models" :key="m.v" :value="m.v">{{ m.v }} — {{ m.d }}</option>
          </select>
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div>
            <label class="label" for="device">Dispositivo</label>
            <select id="device" v-model="form['transcription.device']" class="input">
              <option value="auto">Automático</option><option value="cpu">CPU</option><option value="cuda">GPU NVIDIA (CUDA)</option>
            </select>
          </div>
          <div>
            <label class="label" for="ct">Precisão</label>
            <select id="ct" v-model="form['transcription.compute_type']" class="input">
              <option v-for="v in settings.allowed['transcription.compute_type']" :key="v" :value="v">{{ v }}</option>
            </select>
          </div>
        </div>
        <div>
          <label class="label" for="lang">Idioma</label>
          <input id="lang" v-model="form['transcription.language']" class="input" placeholder="pt" />
        </div>
        <label class="flex items-center justify-between text-sm text-ink-200">Filtrar silêncios antes de transcrever (VAD)<input v-model="form['transcription.vad_filter']" type="checkbox" class="h-4 w-4 accent-violet-500" /></label>
      </section>

      <section class="card space-y-4 p-6">
        <h2 class="flex items-center gap-2 font-display text-lg font-semibold text-white"><Cpu class="h-5 w-5 text-brand-400" /> IA local (Ollama)</h2>
        <p class="text-sm text-ink-400">Opcional e gratuito. Melhora a seleção de cortes e os títulos. Requer o Ollama instalado e um modelo baixado (ex.: <code class="text-ink-200">ollama pull llama3.2:3b</code>).</p>
        <label class="flex items-center justify-between text-sm text-ink-200">Usar Ollama<input v-model="form['ai.ollama_enabled']" type="checkbox" class="h-4 w-4 accent-violet-500" /></label>
        <div><label class="label" for="ourl">Endereço</label><input id="ourl" v-model="form['ai.ollama_url']" class="input" /></div>
        <div><label class="label" for="omodel">Modelo</label><input id="omodel" v-model="form['ai.ollama_model']" class="input" />
          <p class="mt-1.5 text-xs text-ink-500">Para avaliar ganchos, use <code class="text-ink-200">qwen2.5:7b</code> (ou <code class="text-ink-200">qwen2.5:3b</code> em PCs com menos memória). O <code class="text-ink-200">llama3.2:3b</code> não diferencia bem os candidatos e o app volta para as regras.</p></div>
        <div><label class="label" for="hooktimeout">Tempo máximo da IA por gancho (segundos)</label><input id="hooktimeout" v-model.number="form['ai.hook_timeout_s']" type="number" min="10" max="600" class="input" />
          <p class="mt-1.5 text-xs text-ink-500">Se a IA demorar mais que isso, o gancho é escolhido pelas regras.</p></div>
        <div><label class="label" for="mapblocks">Assuntos do episódio avaliados pela IA</label><input id="mapblocks" v-model.number="form['ai.map_blocks']" type="number" min="0" max="30" class="input" />
          <p class="mt-1.5 text-xs text-ink-500">A IA lê os melhores assuntos inteiros, dá nota, título e resumo (cerca de 1,5 min por assunto em CPU sem placa de vídeo; padrão 6). 0 = só as regras.</p></div>
        <div class="border-t border-ink-700 pt-4">
          <label class="label" for="cpath">Executável do Concat (opcional)</label>
          <input id="cpath" v-model="form['concat.path']" class="input" placeholder="Detectado automaticamente — ex.: C:\Program Files\Concat\concat.exe" />
          <p class="mt-1.5 text-xs text-ink-500">Editor de vídeo gratuito (estilo CapCut). Com ele, cada Short ganha um botão "Editar no Concat" com legendas editáveis.</p>
        </div>
      </section>

      <section class="card space-y-4 p-6">
        <h2 class="flex items-center gap-2 font-display text-lg font-semibold text-white"><Film class="h-5 w-5 text-brand-400" /> Renderização</h2>
        <div class="grid grid-cols-2 gap-4">
          <div>
            <label class="label" for="preset">Velocidade (preset x264)</label>
            <select id="preset" v-model="form['render.video_preset']" class="input">
              <option v-for="v in settings.allowed['render.video_preset']" :key="v" :value="v">{{ v }}</option>
            </select>
          </div>
          <div>
            <label class="label" for="crf">Qualidade (CRF)</label>
            <input id="crf" v-model.number="form['render.crf']" type="number" min="14" max="30" class="input" />
          </div>
        </div>
        <p class="text-xs text-ink-500">CRF menor = melhor qualidade e arquivo maior (18–23 é um bom intervalo).</p>
        <label class="flex items-center justify-between text-sm text-ink-200"><span class="flex items-center gap-2"><ScanFace class="h-4 w-4" /> Rastreamento de rostos</span><input v-model="form['render.face_tracking']" type="checkbox" class="h-4 w-4 accent-violet-500" /></label>
        <label class="flex items-center justify-between text-sm text-ink-200">Normalização de áudio (-14 LUFS)<input v-model="form['render.loudnorm']" type="checkbox" class="h-4 w-4 accent-violet-500" /></label>
        <label class="flex items-center justify-between text-sm text-ink-200">Verificar integridade decodificando o arquivo final<input v-model="form['render.verify_decode']" type="checkbox" class="h-4 w-4 accent-violet-500" /></label>
        <div class="border-t border-ink-700 pt-4">
          <label class="label" for="cwords">Palavras extras para mutar</label>
          <textarea id="cwords" v-model="form['censor.extra_words']" rows="2" maxlength="2000" class="input" placeholder="separe por vírgula — ex.: treta, nome de marca" />
          <p class="mt-1.5 text-xs text-ink-500">Os palavrões mais comuns já são silenciados. Use para acrescentar outras palavras.</p>
        </div>
      </section>

      <section class="card space-y-4 p-6">
        <h2 class="flex items-center gap-2 font-display text-lg font-semibold text-white"><Gauge class="h-5 w-5 text-brand-400" /> Limites</h2>
        <div class="grid grid-cols-2 gap-4">
          <div><label class="label" for="lup">Upload máx. (MB)</label><input id="lup" v-model.number="form['limits.max_upload_mb']" type="number" min="10" class="input" /></div>
          <div><label class="label" for="ldur">Duração máx. (min)</label><input id="ldur" v-model.number="form['limits.max_source_minutes']" type="number" min="1" class="input" /></div>
          <div><label class="label" for="lconc">Tarefas simultâneas</label><input id="lconc" v-model.number="form['limits.max_concurrent_jobs']" type="number" min="1" max="8" class="input" /></div>
          <div><label class="label" for="latt">Tentativas por tarefa</label><input id="latt" v-model.number="form['limits.max_attempts']" type="number" min="1" max="5" class="input" /></div>
        </div>
        <p class="text-xs text-ink-500">Computadores modestos: use modelo "base", 1 tarefa simultânea, preset "veryfast" e desative o rastreamento de rostos se o render ficar lento.</p>
      </section>

      <div class="lg:col-span-2">
        <button class="btn-primary" :disabled="saving"><Save class="h-4 w-4" /> Salvar configurações</button>
      </div>
    </form>
  </div>
</template>
