// Cliente da API do ClipFlow Studio
import { reactive } from 'vue'

const TOKEN_KEY = 'clipflow_token'

export const auth = reactive({
  token: safeGet(TOKEN_KEY) || '',
  required: false,
})

function safeGet(k) {
  try { return localStorage.getItem(k) } catch { return null }
}

export function setToken(t) {
  auth.token = t
  try { localStorage.setItem(TOKEN_KEY, t) } catch { /* sem armazenamento */ }
}

export class ApiError extends Error {
  constructor(message, status, detail) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

function errorMessage(detail, status) {
  if (!detail) return `Erro ${status}`
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
  if (detail.message) return detail.message
  return JSON.stringify(detail)
}

export async function api(path, { method = 'GET', body, raw = false } = {}) {
  const headers = {}
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const res = await fetch(path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined })
  if (res.status === 401) auth.required = true
  if (!res.ok) {
    let detail
    try { detail = (await res.json()).detail } catch { detail = await res.text().catch(() => '') }
    throw new ApiError(errorMessage(detail, res.status), res.status, detail)
  }
  if (raw) return res
  const ct = res.headers.get('content-type') || ''
  return ct.includes('application/json') ? res.json() : res.text()
}

// URL de arquivos (vídeo, miniatura) com token quando necessário
export function fileUrl(path) {
  if (!auth.token) return path
  return path + (path.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(auth.token)
}

// Upload com barra de progresso real (XHR envia o arquivo direto, sem multipart)
export function uploadFile(kind, file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', `/api/uploads/${kind}`)
    xhr.setRequestHeader('X-Filename', encodeURIComponent(file.name))
    xhr.setRequestHeader('Content-Type', 'application/octet-stream')
    if (auth.token) xhr.setRequestHeader('Authorization', `Bearer ${auth.token}`)
    xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total) }
    xhr.onload = () => {
      let data
      try { data = JSON.parse(xhr.responseText) } catch { data = {} }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data)
      else reject(new ApiError(errorMessage(data.detail, xhr.status), xhr.status, data.detail))
    }
    xhr.onerror = () => reject(new ApiError('Falha de conexão durante o envio', 0))
    xhr.send(file)
  })
}

// Metadados do servidor (estilos, limites, Concat disponível), buscados uma vez
let metaPromise = null
export function getMeta() {
  if (!metaPromise) metaPromise = api('/api/meta').catch((e) => { metaPromise = null; throw e })
  return metaPromise
}
