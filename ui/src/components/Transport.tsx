import { useEffect } from 'react'
import { ChevronLeft, ChevronRight, Pause, Play, Repeat, SkipBack, SkipForward } from 'lucide-react'
import type { Player } from '@/hooks/usePlayer'
import { fmtTime, type Slide } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Toggle } from '@/components/ui/toggle'
import { cn } from '@/lib/utils'

const SPEEDS = { '0.5': '0.5×', '1': '1×', '2': '2×' }

export function Transport({ player, slides }: { player: Player; slides: Slide[] }) {
  const { t, duration, playing, stepIdx } = player

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === 'INPUT' || (e.target as HTMLElement)?.tagName === 'TEXTAREA') return
      if (e.code === 'Space') {
        e.preventDefault()
        player.toggle()
      } else if (e.key === 'ArrowLeft') player.seek(t - (e.shiftKey ? 5 : 1), { keepMode: true })
      else if (e.key === 'ArrowRight') player.seek(t + (e.shiftKey ? 5 : 1), { keepMode: true })
      else if (e.key === '[') player.gotoStep(stepIdx - 1)
      else if (e.key === ']') player.gotoStep(stepIdx + 1)
      else if (e.key === 'Home') player.gotoStep(0)
      else if (e.key === 'End') player.gotoStep(slides.length - 1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [player, t, stepIdx, slides.length])

  const pct = duration > 0 ? (t / duration) * 100 : 0
  return (
    <div className="flex h-14 shrink-0 items-center gap-2 border-t border-border px-3">
      <Button size="icon-sm" variant="ghost" onClick={() => player.gotoStep(0)} title="First step (Home)">
        <SkipBack />
      </Button>
      <Button size="icon-sm" variant="ghost" onClick={() => player.gotoStep(stepIdx - 1)} title="Previous step ([)">
        <ChevronLeft />
      </Button>
      <Button size="icon" variant="default" onClick={player.toggle} title="Play / pause (space)">
        {playing ? <Pause /> : <Play />}
      </Button>
      <Button size="icon-sm" variant="ghost" onClick={() => player.gotoStep(stepIdx + 1)} title="Next step (])">
        <ChevronRight />
      </Button>
      <Button size="icon-sm" variant="ghost" onClick={() => player.gotoStep(slides.length - 1)} title="Last step (End)">
        <SkipForward />
      </Button>
      <Toggle size="sm" pressed={player.loopStep} onPressedChange={player.setLoopStep} title="Loop current step">
        <Repeat /> loop step
      </Toggle>
      <Select value={String(player.speed)} onValueChange={(v) => v && player.setSpeed(Number(v))} items={SPEEDS}>
        <SelectTrigger size="sm" className="w-20">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {Object.entries(SPEEDS).map(([k, l]) => (
            <SelectItem key={k} value={k}>
              {l}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* scrubber with step markers */}
      <div
        className="group relative mx-2 h-8 grow cursor-pointer"
        onPointerDown={(e) => {
          const r = e.currentTarget.getBoundingClientRect()
          const seekTo = (x: number) => player.seek(((x - r.left) / r.width) * duration, { keepMode: true })
          seekTo(e.clientX)
          const move = (ev: PointerEvent) => seekTo(ev.clientX)
          const up = () => {
            window.removeEventListener('pointermove', move)
            window.removeEventListener('pointerup', up)
          }
          window.addEventListener('pointermove', move)
          window.addEventListener('pointerup', up)
        }}
      >
        <div className="absolute top-1/2 right-0 left-0 h-1.5 -translate-y-1/2 rounded bg-muted" />
        <div className="absolute top-1/2 left-0 h-1.5 -translate-y-1/2 rounded bg-primary/70" style={{ width: `${pct}%` }} />
        {slides.map((s) => (
          <div
            key={s.i}
            title={`step ${s.i + 1}: ${s.label}`}
            className={cn(
              'absolute top-1/2 h-3 w-0.5 -translate-y-1/2 bg-foreground/40',
              s.i === stepIdx && 'bg-primary',
            )}
            style={{ left: `${(s.stats.t0 / duration) * 100}%` }}
          />
        ))}
        <div
          className="absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-background bg-primary shadow"
          style={{ left: `${pct}%` }}
        />
      </div>
      <div className="mono w-28 text-right text-xs text-muted-foreground">
        {fmtTime(t)} / {fmtTime(duration)}
      </div>
    </div>
  )
}
