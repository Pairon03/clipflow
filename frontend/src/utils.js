import { reactive } from 'vue'

export function fmtDuration(sec) {
  if (sec == null || isNaN(sec)) return '—'
  sec = Math.round(sec)
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = sec % 60
  if (h) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${m}:${String(s).padStart(2, '0')}`
}

export function fmtTime(sec) {
  if (sec == null) return '—'
  const m = Math.floor(sec / 60)
  const s = (sec % 60).toFixed(1)
  return `${m}:${s.padStart(4, '0')}`
}

export function fmtBytes(b) {
  if (!b) return '0 B'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.min(Math.floor(Math.log(b) / Math.log(1024)), u.length - 1)
  return `${(b / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`
}

export function fmtDate(ts) {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
}

export const STATUS = {
  queued: { label: 'Na fila', tone: 'slate' },
  downloading: { label: 'Baixando', tone: 'sky' },
  transcribing: { label: 'Transcrevendo', tone: 'sky' },
  analyzing: { label: 'Analisando', tone: 'violet' },
  rendering: { label: 'Renderizando', tone: 'violet' },
  awaiting_review: { label: 'Aguardando revisão', tone: 'amber' },
  completed: { label: 'Concluído', tone: 'emerald' },
  failed: { label: 'Falhou', tone: 'red' },
  cancelled: { label: 'Cancelado', tone: 'slate' },
  done: { label: 'Pronto', tone: 'emerald' },
  selected: { label: 'Selecionado', tone: 'violet' },
  candidate: { label: 'Alternativa', tone: 'slate' },
}

export const ACTIVE = ['queued', 'downloading', 'transcribing', 'analyzing', 'rendering']

export const SCORE_LABELS = {
  clareza: 'Clareza',
  independencia: 'Independência de contexto',
  interesse: 'Interesse narrativo',
  retencao: 'Potencial de retenção',
  audio: 'Qualidade do áudio',
  coerencia: 'Coerência da fala',
  cortes_suaves: 'Sem cortes abruptos',
  ia_local: 'Avaliação da IA local',
}

export const LAYOUT_LABELS = {
  auto: 'Automático',
  follow: 'Seguir rosto principal',
  speaker: 'Alternar quem fala (experimental)',
  split: 'Tela dividida (2 pessoas)',
  fit: 'Quadro inteiro + fundo desfocado',
  center: 'Corte central',
  manual: 'Posição manual',
}

export const CAPTION_LABELS = {
  classic: { name: 'Classic', desc: 'Branco com destaque amarelo', hl: '#FFD60A', font: 'Poppins' },
  neon: { name: 'Neon', desc: 'Branco com destaque roxo', hl: '#B266FF', font: 'Poppins' },
  minimal: { name: 'Minimal', desc: 'Branco com sombra discreta', hl: '#FFFFFF', font: 'Poppins' },
  impact: { name: 'Impact', desc: 'Grande, palavras-chave em destaque', hl: '#FFD60A', font: 'Anton' },
}

// Notificações simples
export const toasts = reactive([])
let tid = 0
export function toast(message, tone = 'info', ms = 4500) {
  const id = ++tid
  toasts.push({ id, message, tone })
  setTimeout(() => {
    const i = toasts.findIndex((t) => t.id === id)
    if (i >= 0) toasts.splice(i, 1)
  }, ms)
}
