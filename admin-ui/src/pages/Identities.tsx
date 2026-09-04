import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import * as React from 'react'

import { ApiErrorRow } from '@/components/ApiErrorRow'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, type Identity } from '@/lib/api'

export function IdentitiesPage() {
  const queryClient = useQueryClient()
  const { data, isLoading, isError, error } = useQuery({ queryKey: ['identities'], queryFn: () => api.identities() })
  const [pendingRevoke, setPendingRevoke] = React.useState<Identity | null>(null)
  const revoke = useMutation({
    mutationFn: api.revokeIdentity,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['identities'] })
      setPendingRevoke(null)
    },
  })

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>Enrolled identities</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>ID</TableHead>
                <TableHead>Enrolled</TableHead>
                <TableHead>Consent</TableHead>
                <TableHead>Retention expires</TableHead>
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
              {!isError && data?.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="py-6 text-center text-muted-foreground">
                    No identities enrolled yet.
                  </TableCell>
                </TableRow>
              )}
              {data?.map((identity) => (
                <TableRow key={identity.id}>
                  <TableCell className="font-medium">{identity.name}</TableCell>
                  <TableCell className="font-data text-xs text-muted-foreground">{identity.id.slice(0, 8)}</TableCell>
                  <TableCell className="font-data text-xs">{new Date(identity.created_at).toLocaleString()}</TableCell>
                  <TableCell>
                    <Badge variant={identity.consent_given ? 'success' : 'destructive'}>
                      {identity.consent_given ? 'given' : 'missing'}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-data text-xs">
                    {identity.retention_expires_at ? new Date(identity.retention_expires_at).toLocaleDateString() : '—'}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="icon"
                      title="Revoke — deletes the identity and every enrolled embedding"
                      onClick={() => setPendingRevoke(identity)}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={pendingRevoke !== null} onOpenChange={(open) => !open && setPendingRevoke(null)}>
        <DialogContent>
          <DialogTitle>Revoke {pendingRevoke?.name}?</DialogTitle>
          <DialogDescription>
            This deletes the identity record and every enrolled embedding. It cannot be undone.
          </DialogDescription>
          <div className="mt-4 flex justify-end gap-2">
            <DialogClose asChild>
              <Button variant="outline" size="sm">
                Cancel
              </Button>
            </DialogClose>
            <Button
              variant="destructive"
              size="sm"
              disabled={revoke.isPending}
              onClick={() => pendingRevoke && revoke.mutate(pendingRevoke.id)}
            >
              {revoke.isPending ? 'Revoking…' : 'Revoke'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
