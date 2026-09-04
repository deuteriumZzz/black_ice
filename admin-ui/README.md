# BLACK ICE admin console

Operations console for the match service — replaces curl/`ui/index.html` for
day-to-day identity, audit, and monitoring work. React + TypeScript + Vite +
Tailwind, talking to the existing FastAPI backend (`services/match`).

## Run

```bash
npm install
echo "VITE_API_BASE_URL=http://localhost:8000" > .env.local
npm run dev
```

Needs the match service running and reachable (`docker compose up -d qdrant
postgres match` from `infra/`, or the full stack). Sign in with any seeded
API key (`dev-admin-key` / `dev-operator-key` by default — see
`BLACK_ICE_API_KEYS` in the match service's env).

## What's here (Milestone 1)

- Login (`POST /auth/login`) backed by the `ApiKey` DB table, not the old
  static env-var lookup
- Dashboard: service health, live access-event feed (`WS /ws/live`)
- Identities: list, revoke (`GET`/`DELETE /identities`)
- Audit log: filterable, paginated (`GET /audit`)
- RBAC-aware: a role without permission for a page sees why, not a blank table

Camera/site management, access rules, and alerting are later milestones —
see the repo's `STATUS.md` for the full phase plan.

## Build / deploy

```bash
docker build -t black-ice-admin-ui --build-arg VITE_API_BASE_URL=https://your-match-host .
```

`VITE_API_BASE_URL` is baked in at build time (Vite inlines `import.meta.env.*`
into the bundle) — it isn't a runtime container env var. Served via nginx with
SPA fallback (`nginx.conf`) so client-side routes like `/identities` survive a
refresh.
