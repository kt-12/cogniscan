import { useState } from 'react'
import { Image, Video } from 'lucide-react'
import { api, describeAction, type Slide } from '@/lib/api'
import type { Player } from '@/hooks/usePlayer'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'

export function FlowPanel({ runId, player, step }: { runId: string; player: Player; step: Slide | null }) {
  const [show, setShow] = useState<'video' | 'shot'>('video')
  const shot = step?.screenshot_after ?? step?.screenshot_before ?? null
  const bbox = step?.element?.bbox
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-9 shrink-0 items-center gap-2 border-b border-border px-3 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">Website flow</span>
        {step && (
          <span>
            step {step.i + 1} · {step.stats.t0}–{step.stats.t1} s
          </span>
        )}
        <div className="grow" />
        <ToggleGroup value={[show]} onValueChange={(v) => v[0] && setShow(v[0] as 'video' | 'shot')} size="sm" variant="outline">
          <ToggleGroupItem value="video" aria-label="video">
            <Video /> video
          </ToggleGroupItem>
          <ToggleGroupItem value="shot" aria-label="screenshot" disabled={!shot}>
            <Image /> screenshot
          </ToggleGroupItem>
        </ToggleGroup>
      </div>
      <div className="relative min-h-0 flex-1 bg-black">
        <video
          ref={player.videoRef}
          src={api.urls.video(runId)}
          className="h-full w-full object-contain"
          style={{ display: show === 'video' ? 'block' : 'none' }}
          preload="auto"
          playsInline
          muted
          onClick={player.toggle}
        />
        {show === 'shot' && shot && (
          <div className="relative flex h-full w-full items-center justify-center">
            <div className="relative max-h-full max-w-full">
              <img src={api.urls.step(runId, shot)} className="max-h-full max-w-full object-contain" alt="" />
              {bbox && step?.action.type === 'click' && (
                <ClickBadge bbox={bbox} shotName={shot} runId={runId} id={step.element?.id} />
              )}
            </div>
          </div>
        )}
        {step && (
          <div className="pointer-events-none absolute right-3 bottom-3 left-3 rounded-lg border border-border bg-background/85 px-3 py-2 text-sm backdrop-blur">
            <div className="font-medium">{step.label || step.title}</div>
            <div className="text-muted-foreground">{describeAction(step)}</div>
            <div className="mono truncate text-[11px] text-muted-foreground">{step.url}</div>
          </div>
        )}
      </div>
    </div>
  )
}

/** Draw the clicked element's box over the screenshot (assumes a 1:1 CSS px to image px capture). */
function ClickBadge({
  bbox,
  id,
}: {
  bbox: { x: number; y: number; w: number; h: number }
  shotName: string
  runId: string
  id?: number
}) {
  // screenshots are 1280 px wide captures of the viewport at device pixel ratio 1
  const W = 1280
  const H = 720
  const style = {
    left: `${(bbox.x / W) * 100}%`,
    top: `${(bbox.y / H) * 100}%`,
    width: `${(bbox.w / W) * 100}%`,
    height: `${(bbox.h / H) * 100}%`,
  }
  return (
    <div className="absolute rounded border-2 border-primary shadow-[0_0_0_2px_rgba(0,0,0,.5)]" style={style}>
      {id != null && (
        <span className="absolute -top-2 -left-2 rounded bg-primary px-1 text-[10px] font-bold text-primary-foreground">{id}</span>
      )}
    </div>
  )
}
