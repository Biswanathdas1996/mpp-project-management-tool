// Typed fetch wrapper for the PMA API (bearer token, JSON, uploads, downloads, error normalisation).
const BASE = '/api'
const TOKEN_KEY = 'pma.token'

export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, message: string, detail: unknown) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}
export function setToken(token: string | null) {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token)
    else sessionStorage.removeItem(TOKEN_KEY)
  } catch {
    /* storage unavailable */
  }
}

function messageFrom(detail: unknown, fallback: string): string {
  if (!detail) return fallback
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail))
    return detail.map((d: { msg?: string; loc?: unknown[] }) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ')
  if (typeof detail === 'object' && detail && 'message' in detail) return String((detail as { message: string }).message)
  return fallback
}

async function request<T>(method: string, path: string, body?: unknown, opts: { form?: FormData; raw?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  let payload: BodyInit | undefined
  if (opts.form) payload = opts.form
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  const res = await fetch(BASE + path, { method, headers, body: payload })
  if (res.status === 401 && onUnauthorized && !path.startsWith('/auth/login')) onUnauthorized()
  if (!res.ok) {
    let detail: unknown = null
    try {
      detail = (await res.json()).detail
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, messageFrom(detail, `${res.status} ${res.statusText}`), detail)
  }
  if (opts.raw) return res as unknown as T
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  get: <T>(p: string) => request<T>('GET', p),
  post: <T>(p: string, b?: unknown) => request<T>('POST', p, b ?? {}),
  put: <T>(p: string, b?: unknown) => request<T>('PUT', p, b ?? {}),
  patch: <T>(p: string, b?: unknown) => request<T>('PATCH', p, b ?? {}),
  del: <T = void>(p: string) => request<T>('DELETE', p),
  upload: <T>(p: string, form: FormData) => request<T>('POST', p, undefined, { form }),
  async download(p: string, fallbackName: string) {
    const res = await request<Response>('GET', p, undefined, { raw: true })
    const cd = res.headers.get('Content-Disposition') || ''
    const m = /filename="?([^";]+)"?/.exec(cd)
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = m ? m[1] : fallbackName
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 2000)
  },
}

/**
 * Subscribe to a Server-Sent Events endpoint. Uses fetch (not EventSource) so the bearer token can be
 * sent. Reconnects with backoff until the server sends `end` or the returned stop() is called.
 */
export function streamSse(
  path: string,
  onEvent: (event: string, data: unknown) => void,
  opts: { onError?: (e: unknown) => void } = {},
): () => void {
  const ctrl = new AbortController()
  let stopped = false
  let attempt = 0

  async function connect() {
    while (!stopped) {
      try {
        const headers: Record<string, string> = { Accept: 'text/event-stream' }
        const token = getToken()
        if (token) headers.Authorization = `Bearer ${token}`
        const res = await fetch(BASE + path, { headers, signal: ctrl.signal })
        if (res.status === 401 && onUnauthorized) onUnauthorized()
        if (!res.ok || !res.body) throw new ApiError(res.status, `${res.status} ${res.statusText}`, null)
        attempt = 0
        const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
        let buf = ''
        for (;;) {
          const { value, done } = await reader.read()
          if (done) break
          buf += value.replace(/\r\n/g, '\n')
          let idx: number
          while ((idx = buf.indexOf('\n\n')) >= 0) {
            const block = buf.slice(0, idx)
            buf = buf.slice(idx + 2)
            let event = 'message'
            const data: string[] = []
            for (const line of block.split('\n')) {
              if (line.startsWith('event:')) event = line.slice(6).trim()
              else if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
            }
            if (!data.length) continue
            let parsed: unknown = data.join('\n')
            try {
              parsed = JSON.parse(parsed as string)
            } catch {
              /* plain text payload */
            }
            onEvent(event, parsed)
            if (event === 'end') {
              stopped = true
              ctrl.abort()
              return
            }
          }
        }
      } catch (e) {
        if (stopped || ctrl.signal.aborted) return
        opts.onError?.(e)
        if (e instanceof ApiError && [401, 403, 404].includes(e.status)) return
      }
      if (stopped) return
      attempt += 1
      await new Promise((r) => setTimeout(r, Math.min(10000, 500 * 2 ** attempt)))
    }
  }
  connect()
  return () => {
    stopped = true
    ctrl.abort()
  }
}

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const s = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join('&')
  return s ? `?${s}` : ''
}
