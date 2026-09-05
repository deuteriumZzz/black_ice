import { useQueryClient } from '@tanstack/react-query'
import * as React from 'react'

import { api, ApiError, setApiKey, type LoginResponse } from '@/lib/api'
import { AUTH_MODE, initKeycloak, keycloak } from '@/lib/keycloak'

interface AuthState {
  session: LoginResponse | null
  status: 'loading' | 'authenticated' | 'unauthenticated'
  login: (apiKey?: string) => Promise<void>
  logout: () => void
}

const AuthContext = React.createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = React.useState<LoginResponse | null>(null)
  const [status, setStatus] = React.useState<AuthState['status']>('loading')
  const queryClient = useQueryClient()

  const fetchSession = React.useCallback(async () => {
    const res = await api.login() // /auth/login just echoes back {role, label} for whatever credential request() attaches
    setSession(res)
    setStatus('authenticated')
  }, [])

  React.useEffect(() => {
    if (AUTH_MODE === 'oidc') {
      initKeycloak()
        .then((authenticated) => (authenticated ? fetchSession() : setStatus('unauthenticated')))
        .catch(() => setStatus('unauthenticated'))
      // keycloak-js's own silent refresh; only re-login (redirect) if the refresh token itself is dead
      keycloak!.onTokenExpired = () => keycloak!.updateToken(30).catch(() => keycloak!.login())
      return
    }

    const storedKey = localStorage.getItem('black_ice_api_key')
    if (!storedKey) {
      setStatus('unauthenticated')
      return
    }
    fetchSession().catch(() => {
      setApiKey(null)
      setStatus('unauthenticated')
    })
  }, [fetchSession])

  const login = React.useCallback(
    async (apiKey?: string) => {
      if (AUTH_MODE === 'oidc') {
        await keycloak!.login() // redirects away; nothing below runs in this tab
        return
      }
      setApiKey(apiKey!)
      try {
        const res = await api.login() // throws ApiError(401) on an invalid key — let the caller show it
        setSession(res)
        setStatus('authenticated')
        // a different role's session must never render the previous session's
        // cached rows next to a fresh 403 — see the bug this fixed: an operator
        // login after an admin one showed cached admin rows under the error row.
        queryClient.clear()
      } catch (err) {
        setApiKey(null) // never persist a key that turned out to be invalid
        throw err
      }
    },
    [queryClient],
  )

  const logout = React.useCallback(() => {
    if (AUTH_MODE === 'oidc') {
      keycloak!.logout({ redirectUri: window.location.origin })
      return
    }
    setApiKey(null)
    setSession(null)
    setStatus('unauthenticated')
    queryClient.clear()
  }, [queryClient])

  return <AuthContext.Provider value={{ session, status, login, logout }}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = React.useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

export { ApiError }
