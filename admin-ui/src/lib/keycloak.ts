import Keycloak from 'keycloak-js'

// "api_key" (default) keeps the existing X-API-Key login form working
// unchanged — see AuthContext.tsx/Login.tsx's AUTH_MODE branches. "oidc"
// switches the whole app to a real Keycloak login (Authorization Code +
// PKCE via this official adapter, not a hand-rolled flow).
export const AUTH_MODE: 'api_key' | 'oidc' = import.meta.env.VITE_AUTH_MODE === 'oidc' ? 'oidc' : 'api_key'

export const keycloak =
  AUTH_MODE === 'oidc'
    ? new Keycloak({
        url: import.meta.env.VITE_OIDC_URL ?? 'http://localhost:8180',
        realm: import.meta.env.VITE_OIDC_REALM ?? 'black-ice',
        clientId: import.meta.env.VITE_OIDC_CLIENT_ID ?? 'black-ice-admin-ui',
      })
    : null

let initPromise: Promise<boolean> | null = null

// check-sso + a silent iframe (public/silent-check-sso.html) restores an
// existing Keycloak session on page reload without a visible redirect flash;
// memoized because React StrictMode/effect re-runs would otherwise call
// keycloak.init() twice, which keycloak-js itself throws on.
export function initKeycloak(): Promise<boolean> {
  if (!keycloak) return Promise.resolve(false)
  if (!initPromise) {
    initPromise = keycloak.init({
      onLoad: 'check-sso',
      pkceMethod: 'S256',
      silentCheckSsoRedirectUri: `${window.location.origin}/silent-check-sso.html`,
    })
  }
  return initPromise
}
