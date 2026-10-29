<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Youtube, Upload, Unplug, Link2, ExternalLink, RotateCcw, X, Trash2, CheckCircle2, TriangleAlert } from 'lucide-vue-next'
import { api, auth, fileUrl } from '../api'
import { fmtDate, fmtBytes, toast } from '../utils'

const route = useRoute()
const router = useRouter()
const account = ref(null)
const pubs = ref([])
const busy = ref(false)
let timer

const STATUS = {
  queued: { label: 'Na fila', cls: 'bg-ink-700 text-ink-200' },
  uploading: { label: 'Enviando', cls: 'bg-violet-500/20 text-violet-200' },
  waiting_quota: { label: 'Limite do dia', cls: 'bg-amber-500/15 text-amber-200' },
  scheduled: { label: 'Agendado', cls: 'bg-sky-500/15 text-sky-200' },
  done: { label: 'Enviado', cls: 'bg-emerald-500/15 text-emerald-200' },
  failed: { label: 'Falhou', cls: 'bg-red-500/15 text-red-200' },
  cancelled: { label: 'Cancelado', cls: 'bg-ink-800 text-ink-400' },
}
const PRIVACY = { private: 'privado', unlisted: 'não listado', public: 'público' }

async function load() {
  try {
    const [a, p] = await Promise.all([api('/api/youtube/account'), api('/api/publications')])
    account.value = a
    pubs.value = p
  } catch (e) { toast(e.message, 'error') }
}
const active = computed(() => pubs.value.some((p) => ['queued', 'uploading', 'waiting_quota'].includes(p.status)))

onMounted(async () => {
  if (route.query.youtube === 'ok') toast('Conta do YouTube conectada!', 'success')
  else if (route.query.youtube === 'erro') toast(String(route.query.msg || 'Não foi possível conectar'), 'error', 9000)
  if (route.query.youtube) router.replace('/publicar')
  await load()
  timer = setInterval(() => { if (active.value) load() }, 3000)
})
onUnmounted(() => clearInterval(timer))

async function uploadClient(file) {
  if (!file) return
  busy.value = true
  try {
    const headers = { 'Content-Type': 'application/json' }
    if (auth.token) headers.Authorization = `Bearer ${auth.token}`
    const res = await fetch('/api/youtube/client', { method: 'PUT', headers, body: file })
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Falha no envio')
    toast('Credencial salva. Agora conecte sua conta.', 'success')
    await load()
  } catch (e) { toast(e.message, 'error', 8000) } finally { busy.value = false }
}

const localHost = ['127.0.0.1', 'localhost', '[::1]'].includes(location.hostname)
const port = location.port || '8000'
async function connect() {
  try {
    const { url } = await api('/api/youtube/connect', { method: 'POST' })
    location.href = url
  } catch (e) { toast(e.message, 'error') }
}
async function disconnect() {
  if (!confirm('Desconectar a conta do YouTube? Os envios na fila ficam esperando até você conectar de novo.')) return
  account.value = await api('/api/youtube/disconnect', { method: 'POST' })
}
async function removeClient() {
  if (!confirm('Remover a credencial do Google Cloud? Também desconecta a conta.')) return
  account.value = await api('/api/youtube/client', { method: 'DELETE' })
}

async function act(p, what) {
  try {
    if (what === 'delete') await api(`/api/publications/${p.id}`, { method: 'DELETE' })
    else await api(`/api/publications/${p.id}/${what}`, { method: 'POST' })
    await load()
  } catch (e) { toast(e.message, 'error') }
}
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="page-title">Publicar</h1>
      <p class="mt-1 text-ink-400">Envio direto para o seu canal do YouTube, com título, descrição, tags e agendamento.</p>
    </div>

    <!-- conta -->
    <section class="card p-5 sm:p-6">
      <div class="flex flex-wrap items-center justify-between gap-4">
        <div class="flex items-center gap-3">
          <img v-if="account?.channel?.thumbnail" :src="account.channel.thumbnail" class="h-11 w-11 rounded-full" alt="" referrerpolicy="no-referrer" />
          <div v-else class="flex h-11 w-11 items-center justify-center rounded-full bg-red-500/15"><Youtube class="h-5 w-5 text-red-400" /></div>
          <div>
            <div class="font-medium text-white">
              <template v-if="account?.connected">{{ account.channel?.title || 'Conta conectada' }}</template>
              <template v-else-if="account?.needs_reconnect">Reconecte sua conta</template>
              <template v-else-if="account?.has_client">Credencial pronta — falta conectar a conta</template>
              <template v-else>YouTube não configurado</template>
            </div>
            <div class="text-xs text-ink-400">
              <template v-if="account?.connected">{{ account.channel?.handle }} · os envios da fila sobem automaticamente</template>
              <template v-else-if="account?.needs_reconnect">{{ account.problem }}</template>
              <template v-else-if="account?.has_client">Projeto do Google Cloud: {{ account.project_id || '—' }}</template>
              <template v-else>Siga os passos abaixo uma vez (uns 15 minutos)</template>
            </div>
          </div>
        </div>
        <div class="flex flex-wrap gap-2">
          <label v-if="!account?.has_client" class="btn-primary cursor-pointer" :class="{ 'opacity-60': busy }">
            <Upload class="h-4 w-4" /> Enviar client_secret.json
            <input type="file" accept=".json,application/json" class="hidden" @change="uploadClient($event.target.files[0]); $event.target.value = ''" />
          </label>
          <button v-if="account?.has_client && !account?.connected" class="btn-primary" :disabled="!localHost" @click="connect"><Link2 class="h-4 w-4" /> {{ account?.needs_reconnect ? 'Reconectar' : 'Conectar conta do YouTube' }}</button>
          <button v-if="account?.connected" class="btn-secondary" @click="disconnect"><Unplug class="h-4 w-4" /> Desconectar</button>
          <button v-if="account?.has_client" class="btn-ghost text-xs" @click="removeClient">Trocar credencial</button>
        </div>
      </div>
      <p v-if="account?.has_client && !account?.connected && !localHost" class="mt-3 text-xs text-amber-300">
        Para conectar, abra o ClipFlow no próprio computador onde ele roda (http://127.0.0.1:{{ port }}). O Google só devolve a autorização para esse endereço.
      </p>
      <div v-if="account?.last_error && !account?.connected" class="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">
        <b>Última tentativa de conexão falhou:</b> {{ account.last_error }}
      </div>
      <div v-if="account?.connected" class="mt-4 flex gap-2 rounded-xl border border-ink-700 bg-ink-850 p-3 text-xs leading-relaxed text-ink-300">
        <TriangleAlert class="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
        <span>Enquanto o Google não auditar o seu projeto, vídeos enviados pela API ficam <b>privados</b> (mesmo os agendados).
          Basta abrir o YouTube Studio e publicar/agendar com um clique. Depois da auditoria (formulário gratuito do Google), fica 100% automático.
          Também há um limite diário de envios; quando ele acaba, a fila espera e continua no dia seguinte.</span>
      </div>
    </section>

    <!-- passo a passo -->
    <details class="card p-5 sm:p-6" :open="account && !account.connected">
      <summary class="cursor-pointer select-none font-medium text-white">Como configurar (uma vez só)</summary>
      <ol class="mt-4 list-decimal space-y-2.5 pl-5 text-sm leading-relaxed text-ink-300">
        <li>Acesse <a href="https://console.cloud.google.com/" target="_blank" rel="noopener" class="text-brand-300 underline">console.cloud.google.com</a> com a conta Google do seu canal e crie um projeto (ex.: "ClipFlow"). É grátis, não precisa de cartão.</li>
        <li>Em <b>APIs e serviços › Biblioteca</b>, procure <b>YouTube Data API v3</b> e clique em <b>Ativar</b>.</li>
        <li>Em <b>APIs e serviços › Tela de consentimento OAuth</b> (ou "Google Auth Platform"): tipo <b>Externo</b>, nome do app "ClipFlow", seu e-mail nos contatos. Em <b>Público-alvo / Usuários de teste</b>, adicione o seu próprio e-mail.</li>
        <li>Ainda na tela de consentimento, clique em <b>Publicar app</b> (colocar "Em produção"). Sem isso, o Google derruba a autorização a cada 7 dias. Não precisa enviar para verificação.</li>
        <li>Em <b>Credenciais › Criar credenciais › ID do cliente OAuth</b>, escolha <b>App para computador</b>. Baixe o JSON.</li>
        <li>Aqui no ClipFlow, clique em <b>Enviar client_secret.json</b> e depois em <b>Conectar conta do YouTube</b>. O Google vai avisar que o app "não foi verificado": clique em <b>Avançado › Acessar ClipFlow</b> (o app é seu) e marque as permissões.</li>
        <li>Opcional, para tirar a trava de "privado": peça a auditoria gratuita no formulário <i>YouTube API Services – Audit and Quota Extension</i> do Google.</li>
      </ol>
    </details>

    <!-- fila -->
    <section class="space-y-3">
      <div class="flex items-center justify-between">
        <h2 class="font-display text-lg font-semibold text-white">Envios</h2>
        <RouterLink to="/biblioteca" class="btn-ghost text-sm">Escolher Shorts na Biblioteca</RouterLink>
      </div>
      <div v-if="!pubs.length" class="card p-10 text-center text-sm text-ink-400">
        Nenhum envio ainda. Na <RouterLink to="/biblioteca" class="text-brand-300 underline">Biblioteca</RouterLink>, marque os Shorts e clique em "Publicar no YouTube".
      </div>
      <div v-for="p in pubs" :key="p.id" class="card flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
        <img v-if="p.has_thumb" :src="fileUrl(`/api/clips/${p.clip_id}/thumb`)" class="h-16 w-9 shrink-0 rounded object-cover" alt="" />
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <span class="rounded-md px-2 py-0.5 text-[11px] font-medium" :class="STATUS[p.status]?.cls">{{ STATUS[p.status]?.label || p.status }}</span>
            <span class="truncate text-sm text-white">{{ p.title }}</span>
          </div>
          <div class="mt-1 text-xs text-ink-400">
            <template v-if="p.publish_at">publica em {{ fmtDate(p.publish_at) }}</template>
            <template v-else>{{ PRIVACY[p.privacy] }}</template>
            <template v-if="p.status === 'uploading'"> · {{ Math.round(p.progress * 100) }}% de {{ fmtBytes(p.size_bytes) }}</template>
            <template v-if="p.status === 'waiting_quota'"> · tenta de novo em {{ fmtDate(p.run_after) }}</template>
            <template v-if="p.finished_at && ['done', 'scheduled'].includes(p.status)"> · enviado {{ fmtDate(p.finished_at) }}</template>
          </div>
          <div v-if="p.status === 'uploading'" class="mt-2 h-1.5 overflow-hidden rounded-full bg-ink-800"><div class="h-full bg-brand-500 transition-all" :style="{ width: `${p.progress * 100}%` }"></div></div>
          <p v-if="p.error && p.status !== 'done' && p.status !== 'scheduled'" class="mt-1 text-xs text-red-300">{{ p.error }}</p>
          <p v-if="p.note" class="mt-1 text-xs text-amber-300">{{ p.note }}</p>
        </div>
        <div class="flex shrink-0 flex-wrap gap-1.5">
          <a v-if="p.url" :href="p.url" target="_blank" rel="noopener" class="btn-secondary py-1.5 text-xs"><ExternalLink class="h-3.5 w-3.5" /> Ver</a>
          <a v-if="p.video_id" :href="`https://studio.youtube.com/video/${p.video_id}/edit`" target="_blank" rel="noopener" class="btn-ghost py-1.5 text-xs"><CheckCircle2 class="h-3.5 w-3.5" /> Studio</a>
          <button v-if="['queued', 'uploading', 'waiting_quota'].includes(p.status)" class="btn-ghost py-1.5 text-xs" @click="act(p, 'cancel')"><X class="h-3.5 w-3.5" /> Cancelar</button>
          <button v-if="['failed', 'cancelled'].includes(p.status)" class="btn-secondary py-1.5 text-xs" @click="act(p, 'retry')"><RotateCcw class="h-3.5 w-3.5" /> Tentar de novo</button>
          <button v-if="!['queued', 'uploading', 'waiting_quota'].includes(p.status)" class="btn-ghost p-1.5 text-ink-500" title="Remover da lista (não apaga no YouTube)" aria-label="Remover da lista" @click="act(p, 'delete')"><Trash2 class="h-3.5 w-3.5" /></button>
        </div>
      </div>
    </section>
  </div>
</template>
