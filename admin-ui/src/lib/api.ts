import { AUTH_MODE, keycloak } from './keycloak'

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

// Refreshes the access token first when it's within 30s of expiry (keycloak-js's
// own refresh-token exchange) so a request never goes out already-expired.
async function authHeader(): Promise<[string, string] | null> {
  if (AUTH_MODE === 'oidc') {
    if (!keycloak) return null
    try {
      await keycloak.updateToken(30)
    } catch {
      // refresh token itself expired/invalid — let the request go without one and 401 naturally
    }
    return keycloak.token ? ['Authorization', `Bearer ${keycloak.token}`] : null
  }
  const apiKey = getApiKey()
  return apiKey ? ['X-API-Key', apiKey] : null
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  const header = await authHeader()
  if (header) headers.set(...header)

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(res.status, body.detail ?? res.statusText)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

function requestJson<T>(path: string, method: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
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

export interface Camera {
  id: string
  camera_id: string
  name: string
  source: string
  site: string | null
  enabled: boolean
  ingest_fps: number
  created_at: string
  last_seen_at: string | null
}

export interface CameraCreateInput {
  camera_id: string
  name: string
  source: string
  site?: string
  ingest_fps?: number
}

export interface CameraUpdateInput {
  name?: string
  source?: string
  site?: string
  ingest_fps?: number
  enabled?: boolean
}

export interface AccessRule {
  id: string
  identity_id: string
  camera_id: string | null
  weekdays: string | null
  start_time: string | null
  end_time: string | null
  enabled: boolean
  created_at: string
}

export interface AccessRuleCreateInput {
  identity_id: string
  camera_id?: string | null
  weekdays?: string | null
  start_time?: string | null
  end_time?: string | null
}

export interface AccessRuleUpdateInput {
  camera_id?: string | null
  weekdays?: string | null
  start_time?: string | null
  end_time?: string | null
  enabled?: boolean
}

export type AlertEventType = 'access_denied' | 'camera_offline'

export interface AlertRule {
  id: string
  event_type: AlertEventType
  identity_id: string | null
  camera_id: string | null
  webhook_url: string
  enabled: boolean
  created_at: string
}

export interface AlertRuleCreateInput {
  event_type: AlertEventType
  identity_id?: string | null
  camera_id?: string | null
  webhook_url: string
}

export interface AlertRuleUpdateInput {
  identity_id?: string | null
  camera_id?: string | null
  webhook_url?: string
  enabled?: boolean
}

export const api = {
  login: () => request<LoginResponse>('/auth/login', { method: 'POST' }),
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
  cameras: () => request<Camera[]>('/cameras'),
  createCamera: (input: CameraCreateInput) => requestJson<Camera>('/cameras', 'POST', input),
  updateCamera: (id: string, input: CameraUpdateInput) => requestJson<Camera>(`/cameras/${id}`, 'PATCH', input),
  deleteCamera: (id: string) => request<{ status: string }>(`/cameras/${id}`, { method: 'DELETE' }),
  accessRules: () => request<AccessRule[]>('/access-rules'),
  createAccessRule: (input: AccessRuleCreateInput) => requestJson<AccessRule>('/access-rules', 'POST', input),
  updateAccessRule: (id: string, input: AccessRuleUpdateInput) => requestJson<AccessRule>(`/access-rules/${id}`, 'PATCH', input),
  deleteAccessRule: (id: string) => request<{ status: string }>(`/access-rules/${id}`, { method: 'DELETE' }),
  alertRules: () => request<AlertRule[]>('/alert-rules'),
  createAlertRule: (input: AlertRuleCreateInput) => requestJson<AlertRule>('/alert-rules', 'POST', input),
  updateAlertRule: (id: string, input: AlertRuleUpdateInput) => requestJson<AlertRule>(`/alert-rules/${id}`, 'PATCH', input),
  deleteAlertRule: (id: string) => request<{ status: string }>(`/alert-rules/${id}`, { method: 'DELETE' }),
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
