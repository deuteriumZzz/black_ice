import * as React from 'react'

import { connectLiveFeed, type LiveEvent } from '@/lib/api'

const MAX_EVENTS = 100

interface LiveFeedState {
  events: LiveEvent[]
  connected: boolean
}

const LiveFeedContext = React.createContext<LiveFeedState | null>(null)

/** One shared WebSocket connection for the whole app — the header's connection
 * pulse and the dashboard's event list both read from here instead of each
 * opening their own socket to /ws/live. */
export function LiveFeedProvider({ children }: { children: React.ReactNode }) {
  const [events, setEvents] = React.useState<LiveEvent[]>([])
  const [connected, setConnected] = React.useState(false)

  React.useEffect(() => {
    return connectLiveFeed((event) => setEvents((prev) => [event, ...prev].slice(0, MAX_EVENTS)), setConnected)
  }, [])

  return <LiveFeedContext.Provider value={{ events, connected }}>{children}</LiveFeedContext.Provider>
}

export function useLiveFeed() {
  const ctx = React.useContext(LiveFeedContext)
  if (!ctx) throw new Error('useLiveFeed must be used within LiveFeedProvider')
  return ctx
}
