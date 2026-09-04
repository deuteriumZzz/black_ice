import { useQuery } from '@tanstack/react-query'
import * as React from 'react'

import { ApiErrorRow } from '@/components/ApiErrorRow'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api } from '@/lib/api'

const PAGE_SIZE = 25

export function AuditPage() {
  const [cameraId, setCameraId] = React.useState('')
  const [identityId, setIdentityId] = React.useState('')
  const [offset, setOffset] = React.useState(0)

  const filters = { limit: PAGE_SIZE, offset, camera_id: cameraId, identity_id: identityId }
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['audit', filters],
    queryFn: () => api.audit(filters),
  })

  function resetAndFilter(setter: (v: string) => void) {
    return (value: string) => {
      setter(value)
      setOffset(0)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Audit log</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="mb-4 flex gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="filter-camera">Camera ID</Label>
            <Input
              id="filter-camera"
              value={cameraId}
              onChange={(e) => resetAndFilter(setCameraId)(e.target.value)}
              placeholder="cam-0"
              className="w-40"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="filter-identity">Identity ID</Label>
            <Input
              id="filter-identity"
              value={identityId}
              onChange={(e) => resetAndFilter(setIdentityId)(e.target.value)}
              placeholder="uuid"
              className="w-48"
            />
          </div>
        </div>
      </CardContent>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>Result</TableHead>
              <TableHead>Score</TableHead>
              <TableHead>Identity</TableHead>
              <TableHead>Camera</TableHead>
              <TableHead>Requested by</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={6} className="py-6 text-center text-muted-foreground">
                  Loading…
                </TableCell>
              </TableRow>
            )}
            {isError && <ApiErrorRow error={error} colSpan={6} />}
            {!isError && data?.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="py-6 text-center text-muted-foreground">
                  No matching audit entries.
                </TableCell>
              </TableRow>
            )}
            {data?.map((row, i) => (
              <TableRow key={i}>
                <TableCell className="font-data text-xs">{new Date(row.ts).toLocaleString()}</TableCell>
                <TableCell>
                  <Badge variant={row.matched ? 'success' : 'warning'}>{row.matched ? 'matched' : 'unknown'}</Badge>
                </TableCell>
                <TableCell className="font-data text-xs">{(row.score * 100).toFixed(1)}%</TableCell>
                <TableCell className="font-data text-xs text-muted-foreground">
                  {row.identity_id ? row.identity_id.slice(0, 8) : '—'}
                </TableCell>
                <TableCell className="font-data text-xs">{row.camera_id ?? '—'}</TableCell>
                <TableCell className="text-xs">{row.requested_by}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <div className="flex items-center justify-between border-t border-border px-3 py-2">
          <span className="text-xs text-muted-foreground">Showing {offset + 1}–{offset + (data?.length ?? 0)}</span>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={(data?.length ?? 0) < PAGE_SIZE}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Next
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
