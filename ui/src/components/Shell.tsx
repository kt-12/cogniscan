import { Link, Outlet, useNavigate, useParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { Activity, Brain, Cpu, List } from 'lucide-react'
import { api, busyStatuses, shortUrl } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

export function Shell() {
  const { id } = useParams()
  const nav = useNavigate()
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 15000 })
  const runs = useQuery({
    queryKey: ['runs'],
    queryFn: api.runs,
    refetchInterval: (q) => (q.state.data?.runs.some((r) => busyStatuses.includes(r.status)) ? 3000 : 15000),
  })
  const items = Object.fromEntries((runs.data?.runs ?? []).map((r) => [r.id, `${shortUrl(r.url)} · ${r.id.slice(0, 15)}`]))
  const h = health.data

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border px-4">
        <Link to="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <Brain className="size-5 text-primary" />
          scan<span className="text-primary">my</span>web
        </Link>
        <Select value={id ?? null} onValueChange={(v) => v && nav(`/view/${v}`)} items={items}>
          <SelectTrigger size="sm" className="w-72">
            <SelectValue placeholder="Open a run…" />
          </SelectTrigger>
          <SelectContent>
            {(runs.data?.runs ?? []).map((r) => (
              <SelectItem key={r.id} value={r.id}>
                <span className="mono text-xs text-muted-foreground">{r.id.slice(0, 15)}</span>
                <span>{shortUrl(r.url)}</span>
                <Badge variant={r.status === 'done' ? 'secondary' : 'outline'} className="ml-auto">
                  {r.status}
                </Badge>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button variant="ghost" size="sm" render={<Link to="/" />}>
          <List /> All runs
        </Button>
        <div className="grow" />
        {h && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Tooltip>
              <TooltipTrigger render={<span className="flex items-center gap-1" />}>
                <Cpu className={h.llm.ok ? 'size-3.5 text-emerald-400' : 'size-3.5 text-red-400'} />
                {h.nav_model}
              </TooltipTrigger>
              <TooltipContent>LLM: {h.llm.detail}</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger render={<span className="flex items-center gap-1" />}>
                <Activity className={h.tribe_python_ok ? 'size-3.5 text-emerald-400' : 'size-3.5 text-red-400'} />
                TRIBE v2
              </TooltipTrigger>
              <TooltipContent>{h.processing ? `processing ${h.processing}` : 'idle'}</TooltipContent>
            </Tooltip>
            {h.processing && <Badge variant="outline">processing {h.processing.slice(0, 15)}</Badge>}
          </div>
        )}
      </header>
      <main className="min-h-0 flex-1">
        <Outlet />
      </main>
    </div>
  )
}
