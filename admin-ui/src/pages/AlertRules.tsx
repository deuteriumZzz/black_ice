import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import * as React from 'react'

import { ApiErrorRow } from '@/components/ApiErrorRow'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogClose, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, type AlertEventType, type AlertRule, type AlertRuleCreateInput } from '@/lib/api'

const EVENT_LABELS: Record<AlertEventType, string> = {
  access_denied: 'Access denied',
  camera_offline: 'Camera offline',
}

const emptyForm: AlertRuleCreateInput = { event_type: 'access_denied', identity_id: '', camera_id: '', webhook_url: '' }

export function AlertRulesPage() {
  const queryClient = useQueryClient()
  const { data: rules, isLoading, isError, error } = useQuery({ queryKey: ['alert-rules'], queryFn: api.alertRules })
  const { data: identities } = useQuery({ queryKey: ['identities'], queryFn: () => api.identities() })
  const { data: cameras } = useQuery({ queryKey: ['cameras'], queryFn: api.cameras })

  const [creating, setCreating] = React.useState(false)
  const [form, setForm] = React.useState<AlertRuleCreateInput>(emptyForm)
  const [pendingDelete, setPendingDelete] = React.useState<AlertRule | null>(null)

  const create = useMutation({
    mutationFn: api.createAlertRule,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alert-rules'] })
      setCreating(false)
      setForm(emptyForm)
    },
  })
  const remove = useMutation({
    mutationFn: api.deleteAlertRule,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alert-rules'] })
      setPendingDelete(null)
    },
  })

  function submit() {
    create.mutate({
      event_type: form.event_type,
      identity_id: form.identity_id || null,
      camera_id: form.camera_id || null,
      webhook_url: form.webhook_url,
    })
  }

  const identityName = (id: string | null) => (id ? (identities?.find((i) => i.id === id)?.name ?? id.slice(0, 8)) : 'any identity')
  const cameraName = (id: string | null) => (id ? (cameras?.find((c) => c.camera_id === id)?.name ?? id) : 'any camera')

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>Alert rules</CardTitle>
          <Button size="sm" onClick={() => { setForm(emptyForm); setCreating(true) }}>
            <Plus className="mr-1 h-4 w-4" /> Add rule
          </Button>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Event</TableHead>
                <TableHead>Identity</TableHead>
                <TableHead>Camera</TableHead>
                <TableHead>Webhook</TableHead>
                <TableHead>Enabled</TableHead>
                <TableHead />
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
              {!isError && rules?.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="py-6 text-center text-muted-foreground">
                    No alert rules yet — configured events won't notify anywhere until you add one.
                  </TableCell>
                </TableRow>
              )}
              {rules?.map((rule) => (
                <TableRow key={rule.id}>
                  <TableCell className="font-medium">{EVENT_LABELS[rule.event_type]}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{identityName(rule.identity_id)}</TableCell>
                  <TableCell className="font-data text-xs text-muted-foreground">{cameraName(rule.camera_id)}</TableCell>
                  <TableCell className="font-data text-xs">{rule.webhook_url}</TableCell>
                  <TableCell className="text-xs">{rule.enabled ? 'yes' : 'no'}</TableCell>
                  <TableCell>
                    <Button variant="ghost" size="icon" title="Remove" onClick={() => setPendingDelete(rule)}>
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={creating} onOpenChange={(open) => !open && setCreating(false)}>
        <DialogContent>
          <DialogTitle>Add alert rule</DialogTitle>
          <div className="mt-4 space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="alert-event">Event</Label>
              <Select
                id="alert-event"
                value={form.event_type}
                onChange={(e) => setForm({ ...form, event_type: e.target.value as AlertEventType })}
              >
                <option value="access_denied">Access denied</option>
                <option value="camera_offline">Camera offline</option>
              </Select>
            </div>
            {form.event_type === 'access_denied' && (
              <div className="space-y-1.5">
                <Label htmlFor="alert-identity">Identity (optional — blank matches any)</Label>
                <Select id="alert-identity" value={form.identity_id ?? ''} onChange={(e) => setForm({ ...form, identity_id: e.target.value })}>
                  <option value="">Any identity</option>
                  {identities?.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.name}
                    </option>
                  ))}
                </Select>
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="alert-camera">Camera (optional — blank matches any)</Label>
              <Select id="alert-camera" value={form.camera_id ?? ''} onChange={(e) => setForm({ ...form, camera_id: e.target.value })}>
                <option value="">Any camera</option>
                {cameras?.map((c) => (
                  <option key={c.id} value={c.camera_id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="alert-webhook">Webhook URL</Label>
              <Input
                id="alert-webhook"
                value={form.webhook_url}
                onChange={(e) => setForm({ ...form, webhook_url: e.target.value })}
                placeholder="https://hooks.example.com/black-ice"
              />
            </div>
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <DialogClose asChild>
              <Button variant="outline" size="sm">
                Cancel
              </Button>
            </DialogClose>
            <Button size="sm" disabled={create.isPending || !form.webhook_url} onClick={submit}>
              Add
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={pendingDelete !== null} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <DialogContent>
          <DialogTitle>Remove this rule?</DialogTitle>
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
