// Typed client for the scanmyweb FastAPI server (same origin; `npm run dev` proxies /api and /surf).

export type RunStatus = 'recording' | 'recorded' | 'queued' | 'processing' | 'done' | 'failed'

export interface RunProgress {
  stage: string
  pct: number
}

export interface ExportState {
  status: 'queued' | 'running' | 'done' | 'failed'
  pct?: number
  stage?: string
  error?: string
  file?: string
  size?: number
}

export interface Run {
  id: string
  url: string
  mode: 'goal' | 'explore'
  goal: string
  nav_model: string
  interp_model: string
  status: RunStatus
  created: number
  updated?: number
  n_frames: number
  n_steps: number
  duration_s?: number
  finish_reason?: string
  progress?: RunProgress
  processing_s?: number
  error?: string | null
  export?: ExportState
}

export interface Health {
  ok: boolean
  nav_model: string
  interp_model: string
  llm: { ok: boolean; detail: string }
  tribe_python_ok: boolean
  mesh_ok: boolean
  processing: string | null
  queued: string[]
}

export interface RoiStat {
  key: string
  label: string
  about: string
  mean: number
  z: number
  run_mean: number
}

export interface ParcelStat {
  name: string
  mean: number
  z: number
}

export interface StepStats {
  rows: number[]
  t0: number
  t1: number
  n_seconds: number
  mean_abs: number
  mean_abs_z: number
  spatial_std: number
  peak_second: number
  rois: RoiStat[]
  top_parcels: ParcelStat[]
  bottom_parcels: ParcelStat[]
  sentence: string
}

export interface Interp {
  headline: string
  interpretation: string
  ux_note: string
  confidence: 'low' | 'medium' | 'high'
  model: string
  error?: string
}

export interface StepAction {
  type: string
  id?: number
  text?: string
  direction?: string
  url?: string
  key?: string
  reason?: string
  label?: string
}

export interface StepElement {
  id: number
  tag: string
  role: string
  text: string
  name?: string
  href?: string
  bbox?: { x: number; y: number; w: number; h: number }
}

export interface Slide {
  i: number
  t0: number
  t1: number
  action: StepAction
  url: string
  title: string
  label: string
  element: StepElement | null
  screenshot_before: string | null
  screenshot_after: string | null
  stats: StepStats
  interp: Interp
}

export interface RoiGroup {
  label: string
  parcels: string[]
  hemi: 'left' | 'right' | 'both'
  about: string
  n_vertices?: number
  parcelIds?: number[]
}

export interface Slides {
  run: Run
  interp_model: string
  tribe: {
    model: string
    license: string
    modalities: { trained_with: string[]; used: string[]; zeroed: string[] }
    TR_s: number
    n_seconds: number
    i8_scale: number
    caveats: string[]
    runtime: { total_s: number; gpu?: string }
    per_second_mean_abs: number[]
  }
  roi_groups: Record<string, RoiGroup>
  roi_means: Record<string, number[]>
  run_stats: { strongest_step: number; weakest_step: number; roi_peaks: Record<string, number> }
  summary: { summary: string; notable_steps: { step: number; why: string }[]; caveat: string; model: string }
  slides: Slide[]
}

export interface Parcels {
  nHemi: number
  parcelNames: string[]
  parcel: { lh: number[]; rh: number[] }
  roiGroups: Record<string, RoiGroup & { parcelIds: number[] }>
}

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  if (!r.ok) {
    let detail = r.statusText
    try {
      detail = (await r.json()).detail ?? detail
    } catch {
      /* ignore */
    }
    throw new Error(`${r.status} ${detail}`)
  }
  return r.json() as Promise<T>
}

export const api = {
  health: () => json<Health>('/api/health'),
  runs: () => json<{ runs: Run[]; processing: string | null; queued: string[] }>('/api/runs'),
  run: (id: string) => json<Run>(`/api/runs/${id}`),
  slides: (id: string) => json<Slides>(`/api/runs/${id}/slides.json`),
  parcels: () => json<Parcels>('/surf/parcels.json'),
  predsI8: async (id: string) => new Int8Array(await (await fetch(`/api/runs/${id}/preds.i8`)).arrayBuffer()),
  deleteRun: (id: string) => json<{ deleted: string }>(`/api/runs/${id}`, { method: 'DELETE' }),
  reprocess: (id: string, q: string) => json<Run>(`/api/runs/${id}/reprocess?${q}`, { method: 'POST' }),
  exportVideo: (id: string) => json<Run>(`/api/runs/${id}/export`, { method: 'POST' }),
  urls: {
    video: (id: string) => `/api/runs/${id}/video`,
    step: (id: string, name: string) => `/api/runs/${id}/steps/${name}`,
    surf: (name: string) => `/surf/${name}`,
    preds: (id: string, hemi: 'lh' | 'rh') => `/api/runs/${id}/preds/${hemi}.func.gii`,
    exportMp4: (id: string) => `/api/runs/${id}/export.mp4`,
  },
}

export const busyStatuses: RunStatus[] = ['recording', 'recorded', 'queued', 'processing']

export function shortUrl(u: string): string {
  try {
    const x = new URL(u)
    return x.host + (x.pathname.length > 1 ? x.pathname.slice(0, 24) : '')
  } catch {
    return u || ''
  }
}

export function describeAction(s: Slide): string {
  const a = s.action ?? {}
  const el = s.element ?? ({} as Partial<StepElement>)
  const label = (el.text || el.name || el.tag || '').slice(0, 60)
  switch (a.type) {
    case 'click':
      return `click ${el.tag || 'element'} “${label}”`
    case 'type':
      return `type “${(a.text || '').slice(0, 40)}” into ${el.tag || 'field'} “${label}”`
    case 'scroll':
      return `scroll ${a.direction || 'down'}`
    case 'navigate':
      return `navigate to ${a.url || ''}`
    case 'key':
      return `press ${a.key || ''}`
    case 'wait':
      return 'wait'
    case 'done':
      return `done: ${(a.reason || '').slice(0, 80)}`
    default:
      return a.type || ''
  }
}

export function fmtTime(t: number): string {
  const m = Math.floor(t / 60)
  const s = t - m * 60
  return m ? `${m}:${s.toFixed(1).padStart(4, '0')}` : `${s.toFixed(1)} s`
}
