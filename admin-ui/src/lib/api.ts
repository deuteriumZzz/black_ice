const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const WS_BASE = API_BASE.replace(/^http/, 'ws')

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

function getApiKey(): string | null {
  return localStorage.getItem('black_ice_api_key')
}

export function setApiKey(key: string | null) {
  if (key) localStorage.setItem('black_ice_api_key', key)
  else localStorage.removeItem('black_ice_api_key')
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const apiKey = getApiKey()
  const headers = new Headers(options.headers)
  if (apiKey) headers.set('X-API-Key', apiKey)

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(res.status, body.detail ?? res.statusText)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export interface LoginResponse {
  role: 'admin' | 'operator' | 'viewer'
  label: string
}

export interface Identity {
  id: string
  name: string
  created_at: string
  consent_given: boolean
  retention_expires_at: string | null
}

export interface AuditRow {
  ts: string
  identity_id: string | null
  matched: boolean
  score: number
  requested_by: string
  camera_id: string | null
}

export interface AuditFilters {
  limit?: number
  offset?: number
  camera_id?: string
  identity_id?: string
  from_ts?: string
  to_ts?: string
}

export const api = {
  login: (apiKey: string) =>
    request<LoginResponse>('/auth/login', { method: 'POST', headers: { 'X-API-Key': apiKey } }),
  identities: (limit = 50, offset = 0) => request<Identity[]>(`/identities?limit=${limit}&offset=${offset}`),
  revokeIdentity: (id: string) => request<{ status: string }>(`/identities/${id}`, { method: 'DELETE' }),
  audit: (filters: AuditFilters = {}) => {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== '') params.set(key, String(value))
    }
    return request<AuditRow[]>(`/audit?${params.toString()}`)
  },
  health: () => request<{ status: string }>('/health'),
}

export interface LiveEvent {
  status: string
  camera_id: string
  track_id: number
  match: string
  name: string | null
  bbox: number[]
}

export function connectLiveFeed(onEvent: (event: LiveEvent) => void, onStatusChange: (connected: boolean) => void) {
  const ws = new WebSocket(`${WS_BASE}/ws/live`)
  ws.onopen = () => onStatusChange(true)
  ws.onclose = () => onStatusChange(false)
  ws.onerror = () => ws.close()
  ws.onmessage = (evt) => {
    try {
      onEvent(JSON.parse(evt.data))
    } catch {
      // malformed frame, ignore
    }
  }
  return () => ws.close()
}
