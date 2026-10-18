<script setup>
import { onMounted, onUnmounted, ref, computed } from 'vue'
import { Film, Clapperboard, Loader, CheckCircle2, HardDrive, Cpu, Sparkles, ArrowRight, Youtube, Upload } from 'lucide-vue-next'
import { api, fileUrl } from '../api'
import { fmtBytes, fmtDuration, fmtDate, ACTIVE, toast } from '../utils'
import StatCard from '../components/StatCard.vue'
import StatusBadge from '../components/StatusBadge.vue'
import ProgressBar from '../components/ProgressBar.vue'

const data = ref(null)
const loading = ref(true)
let timer

async function load() {
  try {
    data.value = await api('/api/dashboard')
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    loading.value = false
  }
}

const hasActive = computed(() => data.value?.recent?.some((p) => ACTIVE.includes(p.status)))

onMounted(() => {
  load()
  timer = setInterval(() => { if (hasActive.value) load() }, 2500)
})
onUnmounted(() => clearInterval(timer))

const areas = { downloads: 'Vídeos originais', exports: 'Shorts exportados', transcripts: 'Transcrições', subtitles: 'Legendas', clips: 'Intermediários', projects: 'Metadados', logs: 'Logs', tmp: 'Temporários' }
</script>

<template>
  <div class="space-y-8">
    <!-- destaque principal -->
    <section class="relative overflow-hidden rounded-3xl border border-brand-500/20 bg-gradient-to-br from-brand-600/25 via-ink-900 to-sky-brand/15 p-6 sm:p-10">
      <div class="absolute -right-16 -top-16 h-64 w-64 rounded-full bg-brand-500/20 blur-3xl"></div>
      <div class="relative max-w-2xl">
        <div class="mb-3 inline-flex items-center gap-2 rounded-full border border-brand-400/30 bg-brand-500/10 px-3 py-1 text-xs font-medium text-brand-200">
          <Sparkles class="h-3.5 w-3.5" /> Transcrição, seleção, enquadramento e legendas automáticos
        </div>
        <h1 class="font-display text-3xl font-semibold tracking-tight text-white sm:text-4xl">Transforme episódios longos em Shorts prontos para revisão</h1>
        <p class="mt-3 text-ink-300">Cole o link de um vídeo autorizado ou envie o arquivo. O ClipFlow encontra os melhores momentos e entrega vídeos verticais 1080×1920 com legendas animadas.</p>
        <div class="mt-6 flex flex-wrap gap-3">
          <RouterLink to="/novo" class="btn-primary px-5 py-3 text-base"><Sparkles class="h-5 w-5" /> Criar novos Shorts</RouterLink>
          <RouterLink to="/biblioteca" class="btn-secondary px-5 py-3 text-base">Ver biblioteca <ArrowRight class="h-4 w-4" /></RouterLink>
        </div>
      </div>
    </section>

    <div v-if="loading" class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <div v-for="i in 4" :key="i" class="card h-32 animate-pulse"></div>
    </div>

    <template v-else-if="data">
      <section class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Vídeos processados" :value="data.videos_processed" :icon="Film" :hint="`${fmtDuration(data.source_seconds)} de material de origem`" />
        <StatCard label="Shorts produzidos" :value="data.shorts_total" :icon="Clapperboard" accent="sky" :hint="`${fmtDuration(data.shorts_seconds)} de conteúdo vertical`" />
        <StatCard label="Em andamento" :value="data.projects_active" :icon="Loader" :hint="`${data.queue.queued} na fila · ${data.projects_review} aguardando revisão`" />
        <StatCard label="Concluídos" :value="data.projects_completed" :icon="CheckCircle2" accent="sky" :hint="data.projects_failed ? `${data.projects_failed} com falha` : 'Nenhuma falha'" />
      </section>

      <section class="grid gap-6 xl:grid-cols-3">
        <div class="card p-6 xl:col-span-2">
          <div class="mb-4 flex items-center justify-between">
            <h2 class="font-display text-lg font-semibold text-white">Projetos recentes</h2>
            <RouterLink to="/novo" class="btn-ghost text-xs">Novo projeto</RouterLink>
          </div>
          <div v-if="!data.recent.length" class="rounded-xl border border-dashed border-ink-600 p-10 text-center text-ink-400">
            <p class="mb-4">Nenhum projeto ainda.</p>
            <div class="flex justify-center gap-3">
              <RouterLink to="/novo?tab=youtube" class="btn-secondary"><Youtube class="h-4 w-4" /> Link do YouTube</RouterLink>
              <RouterLink to="/novo?tab=upload" class="btn-secondary"><Upload class="h-4 w-4" /> Enviar vídeo</RouterLink>
            </div>
          </div>
          <ul v-else class="divide-y divide-ink-800">
            <li v-for="p in data.recent" :key="p.id">
              <RouterLink :to="`/projetos/${p.id}`" class="flex items-center gap-4 rounded-xl px-2 py-3 transition hover:bg-ink-800/60">
                <div class="h-12 w-20 shrink-0 overflow-hidden rounded-lg bg-ink-800">
                  <img v-if="p.source_thumbnail" :src="p.source_thumbnail" class="h-full w-full object-cover" alt="" loading="lazy" />
                  <img v-else :src="fileUrl(`/api/projects/${p.id}/thumb`)" class="h-full w-full object-cover" alt="" loading="lazy" @error="$event.target.style.display = 'none'" />
                </div>
                <div class="min-w-0 flex-1">
                  <div class="truncate font-medium text-ink-100">{{ p.name }}</div>
                  <div class="mt-0.5 flex flex-wrap items-center gap-x-3 text-xs text-ink-400">
                    <span>{{ fmtDate(p.created_at) }}</span>
                    <span>{{ fmtDuration(p.source_duration) }}</span>
                    <span v-if="p.clips_done">{{ p.clips_done }} Shorts</span>
                  </div>
                  <div v-if="ACTIVE.includes(p.status)" class="mt-2 flex items-center gap-3">
                    <ProgressBar :value="p.progress" size="sm" class="max-w-xs" />
                    <span class="truncate text-xs text-ink-400">{{ p.stage }}</span>
                  </div>
                </div>
                <StatusBadge :status="p.status" />
              </RouterLink>
            </li>
          </ul>
        </div>

        <div class="card p-6">
          <h2 class="mb-1 flex items-center gap-2 font-display text-lg font-semibold text-white"><Cpu class="h-4 w-4 text-brand-400" /> Consumo de processamento</h2>
          <p class="mb-5 text-xs text-ink-400">Estimativa baseada nos projetos já processados neste computador.</p>
          <dl class="space-y-3 text-sm">
            <div class="flex justify-between"><dt class="text-ink-400">Tempo total de processamento</dt><dd class="tabular-nums text-ink-100">{{ fmtDuration(data.processing_seconds) }}</dd></div>
            <div class="flex justify-between"><dt class="text-ink-400">Processamento por minuto de vídeo</dt><dd class="tabular-nums text-ink-100">{{ data.realtime_factor != null ? fmtDuration(data.realtime_factor * 60) : '—' }}</dd></div>
            <div class="flex justify-between"><dt class="text-ink-400">Tarefas simultâneas</dt><dd class="tabular-nums text-ink-100">{{ data.queue.running }} / {{ data.queue.max_concurrent }}</dd></div>
          </dl>
          <h3 class="mb-3 mt-6 flex items-center gap-2 text-sm font-medium text-ink-200"><HardDrive class="h-4 w-4 text-sky-300" /> Armazenamento: {{ fmtBytes(data.storage_bytes) }}</h3>
          <ul class="space-y-2 text-xs">
            <li v-for="(bytes, area) in data.storage_by_area" :key="area" v-show="bytes > 0" class="flex justify-between">
              <span class="text-ink-400">{{ areas[area] || area }}</span><span class="tabular-nums text-ink-200">{{ fmtBytes(bytes) }}</span>
            </li>
          </ul>
          <div class="mt-4 text-xs text-ink-500">Espaço livre no disco: {{ fmtBytes(data.disk_free_bytes) }}</div>
        </div>
      </section>
    </template>
  </div>
</template>
