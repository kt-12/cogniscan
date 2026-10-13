import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Film, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { api, describeAction, fmtTime, type Slides } from '@/lib/api'
import { dequantise, roiSeries, type PredMatrix } from '@/lib/preds'
import { usePlayer } from '@/hooks/usePlayer'
import { BrainView, COLORMAPS, VIEWS, type ViewName } from '@/components/BrainView'
import { FlowPanel } from '@/components/FlowPanel'
import { Transport } from '@/components/Transport'
import { RoiBars, fromStats } from '@/components/RoiBars'
import { Timeline } from '@/components/Timeline'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

export function ViewerPage() {
  const { id = '' } = useParams()
  const slides = useQuery({ queryKey: ['slides', id], queryFn: () => api.slides(id), enabled: !!id })
  if (slides.isLoading) return <Centered>Loading run…</Centered>
  if (slides.isError || !slides.data) return <Centered>Could not load this run: {String(slides.error)}</Centered>
  return <Viewer id={id} data={slides.data} />
}

function Centered({ children }: { children: React.ReactNode }) {
  return <div className="flex h-full items-center justify-center text-sm text-muted-foreground">{children}</div>
}

function Viewer({ id, data }: { id: string; data: Slides }) {
  const qc = useQueryClient()
  const duration = data.tribe.n_seconds
  const player = usePlayer(data.slides, duration)
  const [preds, setPreds] = useState<PredMatrix | null>(null)
  const parcels = useQuery({ queryKey: ['parcels'], queryFn: api.parcels, staleTime: Infinity })
  const run = useQuery({ queryKey: ['run', id], queryFn: () => api.run(id), refetchInterval: (q) => (q.state.data?.export && ['queued', 'running'].includes(q.state.data.export.status) ? 2000 : false) })
  const [view, setView] = useState<ViewName>('both')
  const [colormap, setColormap] = useState(COLORMAPS[0].key)
  const [threshold, setThreshold] = useState(0.08)
  const [range, setRange] = useState(Math.min(0.6, data.tribe.i8_scale))
  const [roiKey, setRoiKey] = useState<string | null>(null)
  const [brainErr, setBrainErr] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    api.predsI8(id).then((i8) => alive && setPreds(dequantise(i8, data.tribe.i8_scale))).catch((e) => toast.error(`preds: ${e}`))
    return () => {
      alive = false
    }
  }, [id, data.tribe.i8_scale])

  const series = useMemo(() => roiSeries(data.roi_means, data.roi_groups), [data])
  const step = player.step
  const windowRows = player.mode === 'window' && step ? step.stats.rows : null
  const roiRows = useMemo(() => {
    if (player.mode === 'window' && step) return fromStats(step.stats.rois)
    const s = Math.min(duration - 1, Math.max(0, player.second))
    return series.map((r) => ({ key: r.key, label: r.label, about: r.about, z: r.z[s] ?? 0 }))
  }, [player.mode, player.second, step, series, duration])

  const exp = useMutation({
    mutationFn: () => api.exportVideo(id),
    onSuccess: () => {
      toast.info('Video export queued; the download appears here when it is done')
      qc.invalidateQueries({ queryKey: ['run', id] })
    },
    onError: (e) => toast.error(String(e)),
  })
  const ex = run.data?.export

  return (
    <div className="flex h-full flex-col">
      <ResizablePanelGroup orientation="vertical" className="min-h-0 flex-1">
        <ResizablePanel defaultSize={68} minSize={40}>
          <ResizablePanelGroup orientation="horizontal">
            <ResizablePanel defaultSize={50} minSize={25}>
              <FlowPanel runId={id} player={player} step={step} />
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel defaultSize={50} minSize={30}>
              <div className="flex h-full flex-col">
                <div className="flex h-9 shrink-0 items-center gap-2 border-b border-border px-3 text-xs text-muted-foreground">
                  <span className="font-medium text-foreground">Predicted brain activity</span>
                  <span>fsaverage5 · TRIBE v2 · video only</span>
                  <div className="grow" />
                  <ToggleGroup
                    value={[player.mode]}
                    onValueChange={(v) => v[0] && player.setMode(v[0] as 'second' | 'window')}
                    size="sm"
                    variant="outline"
                  >
                    <ToggleGroupItem value="second">per second</ToggleGroupItem>
                    <ToggleGroupItem value="window">step mean</ToggleGroupItem>
                  </ToggleGroup>
                </div>
                <div className="flex min-h-0 flex-1">
                  <div className="relative min-w-0 flex-1 overflow-hidden">
                    <BrainView
                      runId={id}
                      preds={preds}
                      parcels={parcels.data ?? null}
                      frame={player.second}
                      windowRows={windowRows}
                      threshold={threshold}
                      range={range}
                      colormap={colormap}
                      view={view}
                      roiKey={roiKey}
                      onReady={(ok, msg) => setBrainErr(ok ? null : msg ?? 'failed')}
                    />
                    {brainErr && (
                      <div className="absolute inset-0 flex items-center justify-center bg-background/80 p-4 text-center text-sm text-red-300">
                        Brain viewer failed: {brainErr}. Run <code className="mx-1">scanmyweb export-mesh</code> and reload.
                      </div>
                    )}
                    <div className="absolute top-2 left-2 flex flex-wrap items-center gap-1">
                      <ToggleGroup value={[view]} onValueChange={(v) => v[0] && setView(v[0] as ViewName)} size="sm" variant="outline" className="flex-wrap bg-background/70 backdrop-blur">
                        {VIEWS.map((v) => (
                          <ToggleGroupItem key={v.key} value={v.key}>
                            {v.label}
                          </ToggleGroupItem>
                        ))}
                      </ToggleGroup>
                    </div>
                    <div className="absolute right-2 bottom-2 left-2 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg bg-background/70 px-2 py-1 text-[11px] text-muted-foreground backdrop-blur">
                      <Select value={colormap} onValueChange={(v) => v && setColormap(v)} items={Object.fromEntries(COLORMAPS.map((c) => [c.key, c.label]))}>
                        <SelectTrigger size="sm" className="h-6 w-40 text-[11px]">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {COLORMAPS.map((c) => (
                            <SelectItem key={c.key} value={c.key}>
                              {c.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <span className="whitespace-nowrap">threshold</span>
                      <Slider className="w-24" min={0} max={0.4} step={0.01} value={threshold} onValueChange={(v) => setThreshold(Array.isArray(v) ? v[0] : v)} />
                      <span className="whitespace-nowrap">range</span>
                      <Slider className="w-24" min={0.1} max={1.2} step={0.05} value={range} onValueChange={(v) => setRange(Array.isArray(v) ? v[0] : v)} />
                      <div className="grow" />
                      <span>−{range.toFixed(2)}</span>
                      <span className="legend-bar h-2.5 w-28 rounded" />
                      <span>+{range.toFixed(2)} a.u.</span>
                    </div>
                  </div>
                  <div className="w-56 shrink-0 border-l border-border bg-card/40">
                    <RoiBars
                      rows={roiRows}
                      selected={roiKey}
                      onSelect={setRoiKey}
                      title={player.mode === 'window' && step ? `ROI groups · step ${step.i + 1} mean vs run` : `ROI groups · second ${player.second} vs run`}
                    />
                  </div>
                </div>
              </div>
            </ResizablePanel>
          </ResizablePanelGroup>
        </ResizablePanel>
        <ResizableHandle withHandle />
        <ResizablePanel defaultSize={32} minSize={18}>
          <Tabs defaultValue="tribe" className="flex h-full flex-col gap-0">
            <div className="flex h-9 shrink-0 items-center gap-2 border-b border-border px-3">
              <TabsList className="h-7">
                <TabsTrigger value="tribe">TRIBE says</TabsTrigger>
                <TabsTrigger value="interp">Interpretation</TabsTrigger>
                <TabsTrigger value="summary">Run summary</TabsTrigger>
                <TabsTrigger value="steps">Steps</TabsTrigger>
              </TabsList>
              <div className="grow" />
              <span className="text-xs text-muted-foreground">
                {data.slides.length} steps · {fmtTime(duration)} · TRIBE {data.tribe.runtime.total_s}s on {data.tribe.runtime.gpu ?? 'GPU'} · interp {data.interp_model}
              </span>
              {ex?.status === 'done' ? (
                <Button size="sm" variant="outline" render={<a href={api.urls.exportMp4(id)} download />}>
                  <Download /> video
                </Button>
              ) : ex && ex.status !== 'failed' ? (
                <Badge variant="outline">
                  <Loader2 className="size-3 animate-spin" /> export {ex.stage ?? ex.status} {ex.pct != null && `${Math.round(ex.pct)}%`}
                </Badge>
              ) : (
                <Tooltip>
                  <TooltipTrigger render={<Button size="sm" variant="outline" onClick={() => exp.mutate()} disabled={exp.isPending} />}>
                    <Film /> Export video
                  </TooltipTrigger>
                  <TooltipContent>Render a side-by-side MP4: website flow | brain, with step captions</TooltipContent>
                </Tooltip>
              )}
            </div>
            <TabsContent value="tribe" className="min-h-0 flex-1">
              <div className="grid h-full grid-cols-[1fr_1.2fr] gap-3 p-3">
                <div className="min-h-0 overflow-auto text-sm leading-relaxed">
                  {step ? (
                    <>
                      <p>{step.stats.sentence}</p>
                      <p className="mono mt-2 text-[11px] text-muted-foreground">
                        top: {step.stats.top_parcels.slice(0, 6).map((p) => `${p.name} ${p.z >= 0 ? '+' : ''}${p.z.toFixed(1)}σ`).join(' · ')}
                      </p>
                      <p className="mono text-[11px] text-muted-foreground">
                        bottom: {step.stats.bottom_parcels.slice(0, 3).map((p) => `${p.name} ${p.z.toFixed(1)}σ`).join(' · ')} · peak at {step.stats.peak_second} s
                      </p>
                    </>
                  ) : null}
                </div>
                <div className="flex min-h-0 flex-col">
                  <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                    <span>{roiKey ? `${data.roi_groups[roiKey]?.label} z per second` : 'all ROI groups z per second (grey: mean |predicted BOLD|)'}</span>
                    {roiKey && (
                      <button className="underline" onClick={() => setRoiKey(null)}>
                        show all
                      </button>
                    )}
                  </div>
                  <div className="min-h-0 flex-1">
                    <Timeline
                      series={series}
                      global={data.tribe.per_second_mean_abs}
                      slides={data.slides}
                      t={player.t}
                      duration={duration}
                      stepIdx={player.stepIdx}
                      highlight={roiKey}
                      onSeek={(tt) => player.seek(tt, { keepMode: true })}
                    />
                  </div>
                </div>
              </div>
            </TabsContent>
            <TabsContent value="interp" className="min-h-0 flex-1 overflow-auto p-3 text-sm leading-relaxed">
              {step && (
                <>
                  <div className="mb-1 flex items-center gap-2">
                    <h3 className="font-semibold">{step.interp.headline}</h3>
                    <Badge variant="outline">{step.interp.confidence} confidence</Badge>
                    <span className="text-xs text-muted-foreground">{step.interp.model}</span>
                  </div>
                  <p>{step.interp.interpretation}</p>
                  {step.interp.ux_note && <p className="mt-2 text-primary">UX note: {step.interp.ux_note}</p>}
                </>
              )}
            </TabsContent>
            <TabsContent value="summary" className="min-h-0 flex-1 overflow-auto p-3 text-sm leading-relaxed">
              <p>{data.summary.summary}</p>
              <ul className="mt-2 list-disc pl-5 text-muted-foreground">
                {data.summary.notable_steps.map((n) => (
                  <li key={n.step}>
                    <button className="text-foreground hover:underline" onClick={() => player.gotoStep(n.step - 1)}>
                      step {n.step}
                    </button>
                    : {n.why}
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-muted-foreground">{data.summary.caveat}</p>
              <p className="mt-2 text-xs text-muted-foreground">{data.tribe.caveats.join(' ')}</p>
            </TabsContent>
            <TabsContent value="steps" className="min-h-0 flex-1 overflow-auto">
              <table className="w-full text-xs">
                <tbody>
                  {data.slides.map((s) => (
                    <tr
                      key={s.i}
                      onClick={() => player.gotoStep(s.i)}
                      className={`cursor-pointer border-b border-border hover:bg-accent ${s.i === player.stepIdx ? 'bg-accent' : ''}`}
                    >
                      <td className="mono px-3 py-1 text-muted-foreground">{s.i + 1}</td>
                      <td className="mono px-2 py-1 text-muted-foreground">
                        {s.stats.t0}–{s.stats.t1} s
                      </td>
                      <td className="px-2 py-1">{s.label}</td>
                      <td className="px-2 py-1 text-muted-foreground">{describeAction(s)}</td>
                      <td className="px-2 py-1">{s.interp.headline}</td>
                      <td className="mono px-2 py-1 text-right text-muted-foreground">
                        {s.stats.mean_abs_z >= 0 ? '+' : ''}
                        {s.stats.mean_abs_z.toFixed(2)}σ
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TabsContent>
          </Tabs>
        </ResizablePanel>
      </ResizablePanelGroup>
      <Transport player={player} slides={data.slides} />
    </div>
  )
}
