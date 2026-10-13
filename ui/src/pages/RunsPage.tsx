import { useState } from 'react'
import { Link } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Film, Loader2, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { api, busyStatuses, fmtTime, shortUrl, type Run } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

function StatusBadge({ r }: { r: Run }) {
  const v = r.status === 'done' ? 'secondary' : r.status === 'failed' ? 'destructive' : 'outline'
  return (
    <Badge variant={v} className={r.status === 'done' ? 'text-emerald-300' : ''}>
      {busyStatuses.includes(r.status) && <Loader2 className="size-3 animate-spin" />}
      {r.status}
    </Badge>
  )
}

export function RunsPage() {
  const qc = useQueryClient()
  const runs = useQuery({
    queryKey: ['runs'],
    queryFn: api.runs,
    refetchInterval: (q) =>
      q.state.data?.runs.some((r) => busyStatuses.includes(r.status) || r.export?.status === 'running' || r.export?.status === 'queued')
        ? 3000
        : 15000,
  })
  const [toDelete, setToDelete] = useState<Run | null>(null)
  const del = useMutation({
    mutationFn: (id: string) => api.deleteRun(id),
    onSuccess: () => {
      toast.success('Run deleted')
      qc.invalidateQueries({ queryKey: ['runs'] })
    },
    onError: (e) => toast.error(String(e)),
    onSettled: () => setToDelete(null),
  })
  const exp = useMutation({
    mutationFn: (id: string) => api.exportVideo(id),
    onSuccess: () => {
      toast.info('Video export queued')
      qc.invalidateQueries({ queryKey: ['runs'] })
    },
    onError: (e) => toast.error(String(e)),
  })
  const list = runs.data?.runs ?? []

  return (
    <div className="mx-auto h-full max-w-7xl overflow-auto p-6">
      <div className="mb-4 flex items-end justify-between">
        <div>
          <h2 className="text-lg font-semibold">Runs</h2>
          <p className="text-sm text-muted-foreground">
            Start a recording from the Chrome extension, or{' '}
            <code className="mono text-xs">scanmyweb agent URL --goal "…"</code>
          </p>
        </div>
        {runs.isError && <span className="text-sm text-red-400">{String(runs.error)}</span>}
      </div>
      <div className="rounded-xl border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Run</TableHead>
              <TableHead>Site</TableHead>
              <TableHead>Mode / goal</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="w-48">Progress</TableHead>
              <TableHead className="text-right">Steps</TableHead>
              <TableHead className="text-right">Flow</TableHead>
              <TableHead className="w-56" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {list.map((r) => {
              const ex = r.export
              return (
                <TableRow key={r.id}>
                  <TableCell className="mono text-xs">
                    {r.status === 'done' ? <Link to={`/view/${r.id}`} className="hover:underline">{r.id}</Link> : r.id}
                  </TableCell>
                  <TableCell>
                    <a href={r.url} target="_blank" rel="noreferrer" className="text-sky-300 hover:underline">
                      {shortUrl(r.url)}
                    </a>
                  </TableCell>
                  <TableCell className="max-w-xs truncate" title={r.goal}>
                    <span className="text-muted-foreground">{r.mode}</span>
                    {r.goal && <span> · {r.goal}</span>}
                  </TableCell>
                  <TableCell>
                    <StatusBadge r={r} />
                  </TableCell>
                  <TableCell>
                    <Progress value={r.progress?.pct ?? (r.status === 'done' ? 100 : 0)} className="h-1.5" />
                    <div className="mt-1 truncate text-[11px] text-muted-foreground">
                      {r.status === 'failed' ? r.error : r.progress?.stage ?? r.status}
                      {ex && ex.status !== 'done' && ` · export ${ex.status}${ex.pct != null ? ` ${Math.round(ex.pct)}%` : ''}`}
                    </div>
                  </TableCell>
                  <TableCell className="text-right">{r.n_steps}</TableCell>
                  <TableCell className="text-right text-muted-foreground">{r.duration_s != null ? fmtTime(r.duration_s) : ''}</TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      {r.status === 'done' && (
                        <Button size="sm" variant="outline" render={<Link to={`/view/${r.id}`} />}>
                          open
                        </Button>
                      )}
                      {r.status === 'done' && ex?.status === 'done' && (
                        <Button size="sm" variant="outline" render={<a href={api.urls.exportMp4(r.id)} download />}>
                          <Download /> mp4
                        </Button>
                      )}
                      {r.status === 'done' && (!ex || ex.status === 'failed' || ex.status === 'done') && (
                        <Button
                          size="sm"
                          variant="ghost"
                          title={ex?.status === 'done' ? 'Re-export video' : 'Export side-by-side video'}
                          onClick={() => exp.mutate(r.id)}
                        >
                          <Film />
                        </Button>
                      )}
                      <Button size="sm" variant="ghost" className="text-red-300" onClick={() => setToDelete(r)}>
                        <Trash2 />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              )
            })}
            {!list.length && !runs.isLoading && (
              <TableRow>
                <TableCell colSpan={8} className="py-8 text-center text-muted-foreground">
                  No runs yet.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog open={!!toDelete} onOpenChange={(o) => !o && setToDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete run {toDelete?.id}?</DialogTitle>
            <DialogDescription>
              Removes the recording, TRIBE predictions and interpretation for {toDelete && shortUrl(toDelete.url)}. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setToDelete(null)}>
              Cancel
            </Button>
            <Button variant="destructive" disabled={del.isPending} onClick={() => toDelete && del.mutate(toDelete.id)}>
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
