import { useMemo } from 'react'
import type { Slide } from '@/lib/api'
import type { RoiSeries } from '@/lib/preds'

/** Per-second ROI z-scores (or global |pred|) with step bands and the playhead. Click/drag to seek. */
export function Timeline({
  series,
  global,
  slides,
  t,
  duration,
  stepIdx,
  highlight,
  onSeek,
}: {
  series: RoiSeries[]
  global: number[]
  slides: Slide[]
  t: number
  duration: number
  stepIdx: number
  highlight: string | null
  onSeek: (t: number) => void
}) {
  const W = 1000
  const H = 120
  const padB = 14
  const lines = useMemo(() => {
    const pick = highlight ? series.filter((s) => s.key === highlight) : series
    const zMax = 3
    const y = (z: number) => H - padB - ((Math.max(-zMax, Math.min(zMax, z)) + zMax) / (2 * zMax)) * (H - padB - 6)
    const x = (i: number) => ((i + 0.5) / Math.max(1, duration)) * W
    return pick.map((s) => ({
      key: s.key,
      label: s.label,
      d: s.z.map((z, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(z).toFixed(1)}`).join(' '),
    }))
  }, [series, highlight, duration])
  const gmax = Math.max(...global, 1e-6)
  const gd = global.map((v, i) => `${i ? 'L' : 'M'}${(((i + 0.5) / Math.max(1, duration)) * W).toFixed(1)},${(H - padB - (v / gmax) * (H - padB - 6)).toFixed(1)}`).join(' ')

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className="h-full w-full cursor-pointer select-none"
      onPointerDown={(e) => {
        const r = e.currentTarget.getBoundingClientRect()
        const seekTo = (cx: number) => onSeek(((cx - r.left) / r.width) * duration)
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
      {slides.map((s) => (
        <rect
          key={s.i}
          x={(s.stats.t0 / duration) * W}
          y={0}
          width={((s.stats.t1 - s.stats.t0) / duration) * W}
          height={H}
          className={s.i === stepIdx ? 'fill-primary/15' : s.i % 2 ? 'fill-foreground/[0.04]' : 'fill-transparent'}
        />
      ))}
      <line x1={0} x2={W} y1={H - padB - (H - padB - 6) / 2} y2={H - padB - (H - padB - 6) / 2} className="stroke-border" strokeDasharray="4 4" />
      {!highlight && <path d={gd} fill="none" className="stroke-foreground/35" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />}
      {lines.map((l) => (
        <path
          key={l.key}
          d={l.d}
          fill="none"
          className={highlight ? 'stroke-primary' : 'stroke-sky-400/30'}
          strokeWidth={highlight ? 2 : 1}
          vectorEffect="non-scaling-stroke"
        />
      ))}
      {slides.map((s) => (
        <text key={s.i} x={(s.stats.t0 / duration) * W + 3} y={H - 3} className="fill-muted-foreground text-[10px]" style={{ fontSize: 10 }}>
          {s.i + 1}
        </text>
      ))}
      <line x1={(t / duration) * W} x2={(t / duration) * W} y1={0} y2={H} className="stroke-primary" strokeWidth={2} vectorEffect="non-scaling-stroke" />
    </svg>
  )
}
