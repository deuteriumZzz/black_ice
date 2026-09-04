import * as React from 'react'

import { api, ApiError, setApiKey, type LoginResponse } from '@/lib/api'

interface AuthState {
  session: LoginResponse | null
  status: 'loading' | 'authenticated' | 'unauthenticated'
  login: (apiKey: string) => Promise<void>
  logout: () => void
}

const AuthContext = React.createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = React.useState<LoginResponse | null>(null)
  const [status, setStatus] = React.useState<AuthState['status']>('loading')

  const tryRestore = React.useCallback(async () => {
    const storedKey = localStorage.getItem('black_ice_api_key')
    if (!storedKey) {
      setStatus('unauthenticated')
      return
    }
    try {
      const res = await api.login(storedKey)
      setSession(res)
      setStatus('authenticated')
    } catch {
      setApiKey(null)
      setStatus('unauthenticated')
    }
  }, [])

  React.useEffect(() => {
    tryRestore()
  }, [tryRestore])

  const login = React.useCallback(async (apiKey: string) => {
    const res = await api.login(apiKey) // throws ApiError(401) on an invalid key — let the caller show it
    setApiKey(apiKey)
    setSession(res)
    setStatus('authenticated')
  }, [])

  const logout = React.useCallback(() => {
    setApiKey(null)
    setSession(null)
    setStatus('unauthenticated')
  }, [])

  return <AuthContext.Provider value={{ session, status, login, logout }}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = React.useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

export { ApiError }
