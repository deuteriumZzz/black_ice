import { useQuery } from '@tanstack/react-query'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { api } from '@/lib/api'
import { useLiveFeed } from '@/contexts/LiveFeedContext'

export function DashboardPage() {
  const { events, connected } = useLiveFeed()
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 15_000 })

  const confirmed = events.filter((e) => e.status === 'IDENTITY CONFIRMED').length
  const unknown = events.length - confirmed

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-3 gap-4">
        <StatCard label="Service" value={health.data?.status ?? (health.isLoading ? '…' : 'unreachable')} />
        <StatCard label="Confirmed (session)" value={String(confirmed)} tone="success" />
        <StatCard label="Unknown (session)" value={String(unknown)} tone={unknown > 0 ? 'warning' : undefined} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Live access events</CardTitle>
          <Badge variant={connected ? 'success' : 'destructive'}>{connected ? 'connected' : 'disconnected'}</Badge>
        </CardHeader>
        <CardContent className="max-h-[28rem] space-y-1 overflow-y-auto p-2">
          {events.length === 0 && (
            <p className="p-4 text-center text-sm text-muted-foreground">
              No events yet — waiting for the camera pipeline to publish a decision.
            </p>
          )}
          {events.map((event, i) => {
            const confirmedEvent = event.status === 'IDENTITY CONFIRMED'
            return (
              <div key={i} className="flex items-center justify-between rounded-md px-2 py-1.5 hover:bg-muted/50">
                <div className="flex items-center gap-3">
                  <Badge variant={confirmedEvent ? 'success' : 'warning'}>{event.status}</Badge>
                  <span className="font-data text-xs text-muted-foreground">
                    cam:{event.camera_id} track:{event.track_id}
                  </span>
                </div>
                <div className="flex items-center gap-3 font-data text-xs">
                  {confirmedEvent && <span>{event.name}</span>}
                  <span className="text-muted-foreground">{event.match}</span>
                </div>
              </div>
            )
          })}
        </CardContent>
      </Card>
    </div>
  )
}

function StatCard({ label, value, tone }: { label: string; value: string; tone?: 'success' | 'warning' }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-xs text-muted-foreground">{label}</div>
        <div
          className={
            'mt-1 text-2xl font-semibold ' +
            (tone === 'success' ? 'text-success' : tone === 'warning' ? 'text-warning' : '')
          }
        >
          {value}
        </div>
      </CardContent>
    </Card>
  )
}
