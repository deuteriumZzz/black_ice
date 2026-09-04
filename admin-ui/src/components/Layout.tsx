import { Activity, LogOut, ScrollText, Users } from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'

import { useAuth } from '@/contexts/AuthContext'
import { useLiveFeed } from '@/contexts/LiveFeedContext'
import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', icon: Activity },
  { to: '/identities', label: 'Identities', icon: Users },
  { to: '/audit', label: 'Audit log', icon: ScrollText },
]

export function Layout() {
  const { session, logout } = useAuth()
  const { connected } = useLiveFeed()

  return (
    <div className="flex h-full">
      <aside className="flex w-56 shrink-0 flex-col border-r border-border bg-card">
        <div className="border-b border-border px-4 py-3">
          <div className="text-sm font-semibold tracking-tight">BLACK ICE</div>
          <div className="text-xs text-muted-foreground">Access control console</div>
        </div>
        <nav className="flex-1 space-y-0.5 p-2">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors',
                  isActive ? 'bg-muted text-foreground' : 'text-muted-foreground hover:bg-muted/50',
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-border p-3">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs font-medium">{session?.label ?? '—'}</div>
              <div className="text-xs capitalize text-muted-foreground">{session?.role}</div>
            </div>
            <button
              onClick={logout}
              className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
              title="Log out"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
      </aside>

      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex h-11 shrink-0 items-center justify-end gap-2 border-b border-border px-4 text-xs">
          <span className={cn('h-2 w-2 rounded-full', connected ? 'bg-success animate-pulse' : 'bg-destructive')} />
          <span className="text-muted-foreground">{connected ? 'Live feed connected' : 'Live feed disconnected'}</span>
        </header>
        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
