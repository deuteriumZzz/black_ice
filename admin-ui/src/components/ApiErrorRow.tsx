import { ApiError } from '@/contexts/AuthContext'
import { TableCell, TableRow } from '@/components/ui/table'

/** A blank table with no rows and no message is indistinguishable from "no
 * data" — this makes a 401/403 (or any other fetch failure) visible instead
 * of silently rendering as an empty state. */
export function ApiErrorRow({ error, colSpan }: { error: unknown; colSpan: number }) {
  const message =
    error instanceof ApiError && error.status === 403
      ? "Your role doesn't have permission to view this."
      : error instanceof ApiError && error.status === 401
        ? 'Session expired — please sign in again.'
        : 'Could not load this data.'

  return (
    <TableRow>
      <TableCell colSpan={colSpan} className="py-6 text-center text-destructive">
        {message}
      </TableCell>
    </TableRow>
  )
}
