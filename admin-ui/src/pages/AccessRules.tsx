import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import * as React from 'react'

import { ApiErrorRow } from '@/components/ApiErrorRow'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogClose, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, type AccessRule, type AccessRuleCreateInput } from '@/lib/api'

const DAYS = [
  { code: 'mon', label: 'Mon' },
  { code: 'tue', label: 'Tue' },
  { code: 'wed', label: 'Wed' },
  { code: 'thu', label: 'Thu' },
  { code: 'fri', label: 'Fri' },
  { code: 'sat', label: 'Sat' },
  { code: 'sun', label: 'Sun' },
]

const emptyForm: AccessRuleCreateInput = { identity_id: '', camera_id: '', weekdays: null, start_time: '', end_time: '' }

function summarizeWindow(rule: AccessRule): string {
  const days = rule.weekdays ? rule.weekdays.split(',').join(', ') : 'every day'
  const hours = rule.start_time && rule.end_time ? `${rule.start_time}–${rule.end_time}` : 'all day'
  return `${days}, ${hours}`
}

export function AccessRulesPage() {
  const queryClient = useQueryClient()
  const { data: rules, isLoading, isError, error } = useQuery({ queryKey: ['access-rules'], queryFn: api.accessRules })
  const { data: identities } = useQuery({ queryKey: ['identities'], queryFn: () => api.identities() })
  const { data: cameras } = useQuery({ queryKey: ['cameras'], queryFn: api.cameras })

  const [creating, setCreating] = React.useState(false)
  const [form, setForm] = React.useState<AccessRuleCreateInput>(emptyForm)
  const [selectedDays, setSelectedDays] = React.useState<Set<string>>(new Set())
  const [allDays, setAllDays] = React.useState(true)
  const [pendingDelete, setPendingDelete] = React.useState<AccessRule | null>(null)

  const create = useMutation({
    mutationFn: api.createAccessRule,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['access-rules'] })
      setCreating(false)
      setForm(emptyForm)
      setSelectedDays(new Set())
      setAllDays(true)
    },
  })
  const remove = useMutation({
    mutationFn: api.deleteAccessRule,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['access-rules'] })
      setPendingDelete(null)
    },
  })

  function toggleDay(code: string) {
    const next = new Set(selectedDays)
    if (next.has(code)) next.delete(code)
    else next.add(code)
    setSelectedDays(next)
  }

  function submit() {
    create.mutate({
      identity_id: form.identity_id,
      camera_id: form.camera_id || null,
      weekdays: allDays || selectedDays.size === 0 ? null : Array.from(selectedDays).join(','),
      start_time: form.start_time || null,
      end_time: form.end_time || null,
    })
  }

  const identityName = (id: string) => identities?.find((i) => i.id === id)?.name ?? id.slice(0, 8)

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>Access rules</CardTitle>
          <Button size="sm" onClick={() => { setForm(emptyForm); setSelectedDays(new Set()); setAllDays(true); setCreating(true) }}>
            <Plus className="mr-1 h-4 w-4" /> Add rule
          </Button>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Identity</TableHead>
                <TableHead>Camera</TableHead>
                <TableHead>Window</TableHead>
                <TableHead>Enabled</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading && (
                <TableRow>
                  <TableCell colSpan={5} className="py-6 text-center text-muted-foreground">
                    Loading…
                  </TableCell>
                </TableRow>
              )}
              {isError && <ApiErrorRow error={error} colSpan={5} />}
              {!isError && rules?.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="py-6 text-center text-muted-foreground">
                    No rules yet — with none, every identity is denied everywhere (default-deny).
                  </TableCell>
                </TableRow>
              )}
              {rules?.map((rule) => (
                <TableRow key={rule.id}>
                  <TableCell className="font-medium">{identityName(rule.identity_id)}</TableCell>
                  <TableCell className="font-data text-xs text-muted-foreground">{rule.camera_id ?? 'all cameras'}</TableCell>
                  <TableCell className="text-xs">{summarizeWindow(rule)}</TableCell>
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
          <DialogTitle>Add access rule</DialogTitle>
          <div className="mt-4 space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="rule-identity">Identity</Label>
              <Select id="rule-identity" value={form.identity_id} onChange={(e) => setForm({ ...form, identity_id: e.target.value })}>
                <option value="">Select an identity…</option>
                {identities?.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rule-camera">Camera</Label>
              <Select id="rule-camera" value={form.camera_id ?? ''} onChange={(e) => setForm({ ...form, camera_id: e.target.value })}>
                <option value="">All cameras</option>
                {cameras?.map((c) => (
                  <option key={c.id} value={c.camera_id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Days</Label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={allDays} onChange={(e) => setAllDays(e.target.checked)} />
                Every day
              </label>
              {!allDays && (
                <div className="flex flex-wrap gap-3 pt-1">
                  {DAYS.map((d) => (
                    <label key={d.code} className="flex items-center gap-1 text-xs">
                      <input type="checkbox" checked={selectedDays.has(d.code)} onChange={() => toggleDay(d.code)} />
                      {d.label}
                    </label>
                  ))}
                </div>
              )}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="rule-start">Start time</Label>
                <input
                  id="rule-start"
                  type="time"
                  className="flex h-9 w-full rounded-md border border-border bg-muted px-3 py-1 text-sm outline-none"
                  value={form.start_time ?? ''}
                  onChange={(e) => setForm({ ...form, start_time: e.target.value })}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="rule-end">End time</Label>
                <input
                  id="rule-end"
                  type="time"
                  className="flex h-9 w-full rounded-md border border-border bg-muted px-3 py-1 text-sm outline-none"
                  value={form.end_time ?? ''}
                  onChange={(e) => setForm({ ...form, end_time: e.target.value })}
                />
              </div>
            </div>
            <p className="text-xs text-muted-foreground">Leave both times empty for all-day access. Overnight windows (e.g. 22:00–06:00) aren't supported yet.</p>
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <DialogClose asChild>
              <Button variant="outline" size="sm">
                Cancel
              </Button>
            </DialogClose>
            <Button size="sm" disabled={create.isPending || !form.identity_id} onClick={submit}>
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
