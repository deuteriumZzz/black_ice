import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import * as React from 'react'

import { ApiErrorRow } from '@/components/ApiErrorRow'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, type Camera, type CameraCreateInput } from '@/lib/api'

// No config endpoint exposes the real heartbeat interval (backend default is
// 5s) — this is a generous fixed margin over that, not a computed value.
const STALE_THRESHOLD_MS = 30_000

function relativeLastSeen(lastSeenAt: string | null): { label: string; stale: boolean } {
  if (!lastSeenAt) return { label: 'never', stale: true }
  const ageMs = Date.now() - new Date(lastSeenAt).getTime()
  const label = ageMs < 60_000 ? `${Math.round(ageMs / 1000)}s ago` : `${Math.round(ageMs / 60_000)}m ago`
  return { label, stale: ageMs > STALE_THRESHOLD_MS }
}

const emptyForm: CameraCreateInput = { camera_id: '', name: '', source: '', site: '', ingest_fps: 5 }

export function CamerasPage() {
  const queryClient = useQueryClient()
  const { data, isLoading, isError, error } = useQuery({ queryKey: ['cameras'], queryFn: api.cameras, refetchInterval: 10_000 })

  const [editing, setEditing] = React.useState<Camera | null>(null)
  const [creating, setCreating] = React.useState(false)
  const [form, setForm] = React.useState<CameraCreateInput>(emptyForm)
  const [pendingDelete, setPendingDelete] = React.useState<Camera | null>(null)

  const create = useMutation({
    mutationFn: api.createCamera,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cameras'] })
      setCreating(false)
      setForm(emptyForm)
    },
  })
  const update = useMutation({
    mutationFn: ({ id, ...input }: { id: string } & Parameters<typeof api.updateCamera>[1]) => api.updateCamera(id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cameras'] })
      setEditing(null)
    },
  })
  const remove = useMutation({
    mutationFn: api.deleteCamera,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cameras'] })
      setPendingDelete(null)
    },
  })

  function openEdit(camera: Camera) {
    setEditing(camera)
    setForm({ camera_id: camera.camera_id, name: camera.name, source: camera.source, site: camera.site ?? '', ingest_fps: camera.ingest_fps })
  }

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>Cameras</CardTitle>
          <Button size="sm" onClick={() => { setForm(emptyForm); setCreating(true) }}>
            <Plus className="mr-1 h-4 w-4" /> Add camera
          </Button>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Camera ID</TableHead>
                <TableHead>Site</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>FPS</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Last seen</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading && (
                <TableRow>
                  <TableCell colSpan={8} className="py-6 text-center text-muted-foreground">
                    Loading…
                  </TableCell>
                </TableRow>
              )}
              {isError && <ApiErrorRow error={error} colSpan={8} />}
              {!isError && data?.length === 0 && (
                <TableRow>
                  <TableCell colSpan={8} className="py-6 text-center text-muted-foreground">
                    No cameras registered yet. Adding one here configures it and deploys
                    its ingest process (when orchestration is enabled — see README).
                  </TableCell>
                </TableRow>
              )}
              {data?.map((camera) => {
                const seen = relativeLastSeen(camera.last_seen_at)
                return (
                  <TableRow key={camera.id}>
                    <TableCell className="font-medium">{camera.name}</TableCell>
                    <TableCell className="font-data text-xs text-muted-foreground">{camera.camera_id}</TableCell>
                    <TableCell className="text-xs">{camera.site ?? '—'}</TableCell>
                    <TableCell className="font-data text-xs">{camera.source}</TableCell>
                    <TableCell className="font-data text-xs">{camera.ingest_fps}</TableCell>
                    <TableCell>
                      <Badge variant={camera.enabled ? 'success' : 'neutral'}>{camera.enabled ? 'enabled' : 'disabled'}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={seen.stale ? 'destructive' : 'success'}>{seen.label}</Badge>
                    </TableCell>
                    <TableCell className="flex gap-1">
                      <Button variant="ghost" size="icon" title="Edit" onClick={() => openEdit(camera)}>
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="icon" title="Remove" onClick={() => setPendingDelete(camera)}>
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={creating || editing !== null} onOpenChange={(open) => { if (!open) { setCreating(false); setEditing(null) } }}>
        <DialogContent>
          <DialogTitle>{editing ? `Edit ${editing.name}` : 'Add camera'}</DialogTitle>
          <div className="mt-4 space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="cam-id">Camera ID</Label>
              <Input
                id="cam-id"
                value={form.camera_id}
                disabled={editing !== null}
                onChange={(e) => setForm({ ...form, camera_id: e.target.value })}
                placeholder="cam-lobby"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cam-name">Name</Label>
              <Input id="cam-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cam-source">Source (RTSP URL, webcam index, or file path)</Label>
              <Input id="cam-source" value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cam-site">Site</Label>
              <Input id="cam-site" value={form.site} onChange={(e) => setForm({ ...form, site: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cam-fps">Ingest FPS</Label>
              <Input
                id="cam-fps"
                type="number"
                value={form.ingest_fps}
                onChange={(e) => setForm({ ...form, ingest_fps: Number(e.target.value) })}
              />
            </div>
            {editing && (
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={editing.enabled}
                  onChange={(e) => setEditing({ ...editing, enabled: e.target.checked })}
                />
                Enabled
              </label>
            )}
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <DialogClose asChild>
              <Button variant="outline" size="sm">
                Cancel
              </Button>
            </DialogClose>
            <Button
              size="sm"
              disabled={create.isPending || update.isPending || !form.name || !form.source || !form.camera_id}
              onClick={() =>
                editing
                  ? update.mutate({ id: editing.id, name: form.name, source: form.source, site: form.site, ingest_fps: form.ingest_fps, enabled: editing.enabled })
                  : create.mutate(form)
              }
            >
              {editing ? 'Save' : 'Add'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={pendingDelete !== null} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <DialogContent>
          <DialogTitle>Remove {pendingDelete?.name}?</DialogTitle>
          <DialogDescription>
            This only removes the registry entry — if an ingest process is still deployed for
            this camera_id, it keeps running until you stop it separately.
          </DialogDescription>
          <div className="mt-4 flex justify-end gap-2">
            <DialogClose asChild>
              <Button variant="outline" size="sm">
                Cancel
              </Button>
            </DialogClose>
            <Button variant="destructive" size="sm" disabled={remove.isPending} onClick={() => pendingDelete && remove.mutate(pendingDelete.id)}>
              {remove.isPending ? 'Removing…' : 'Remove'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
