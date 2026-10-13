import type { RoiStat } from '@/lib/api'
import { cn } from '@/lib/utils'

export interface RoiRow {
  key: string
  label: string
  about: string
  z: number
}

export function RoiBars({
  rows,
  selected,
  onSelect,
  title,
}: {
  rows: RoiRow[]
  selected: string | null
  onSelect: (k: string | null) => void
  title: string
}) {
  const sorted = [...rows].sort((a, b) => b.z - a.z)
  return (
    <div className="flex h-full flex-col text-xs">
      <div className="px-3 pt-2 pb-1 text-[11px] text-muted-foreground">{title}</div>
      <div className="min-h-0 flex-1 overflow-auto px-2 pb-2">
        {sorted.map((r) => {
          const w = Math.min(50, (Math.abs(r.z) / 3) * 50)
          const sel = selected === r.key
          return (
            <button
              key={r.key}
              title={r.about}
              onClick={() => onSelect(sel ? null : r.key)}
              className={cn(
                'grid w-full grid-cols-[1fr_84px_38px] items-center gap-2 rounded px-1 py-[3px] text-left hover:bg-accent',
                sel && 'bg-accent ring-1 ring-primary/60',
              )}
            >
              <span className="truncate text-muted-foreground">{r.label}</span>
              <span className="relative h-2 rounded bg-muted">
                <span className="absolute top-0 bottom-0 left-1/2 w-px bg-border" />
                <span
                  className={cn('absolute top-0 h-full rounded', r.z >= 0 ? 'bg-primary' : 'bg-sky-400')}
                  style={r.z >= 0 ? { left: '50%', width: `${w}%` } : { right: '50%', width: `${w}%` }}
                />
              </span>
              <span className="mono text-right">
                {r.z >= 0 ? '+' : ''}
                {r.z.toFixed(1)}σ
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

export function fromStats(rois: RoiStat[]): RoiRow[] {
  return rois.map((r) => ({ key: r.key, label: r.label, about: r.about, z: r.z }))
}
