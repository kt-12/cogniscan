// Per-second helpers over the TRIBE prediction matrix and the ROI time series.

export const N_HEMI = 10242
export const N_VERT = 2 * N_HEMI

export interface PredMatrix {
  nT: number
  /** nT × N_VERT float32 (a.u.), de-quantised from preds.i8 */
  data: Float32Array
}

export function dequantise(i8: Int8Array, scale: number): PredMatrix {
  const nT = Math.floor(i8.length / N_VERT)
  const data = new Float32Array(nT * N_VERT)
  const k = scale / 127
  for (let i = 0; i < nT * N_VERT; i++) data[i] = i8[i] * k
  return { nT, data }
}

/** Mean over the given rows for one hemisphere, written into `out` (N_HEMI). */
export function hemiWindowMean(m: PredMatrix, rows: number[], hemi: 0 | 1, out: Float32Array): Float32Array {
  out.fill(0)
  const valid = rows.filter((r) => r >= 0 && r < m.nT)
  if (!valid.length) return out
  const off = hemi * N_HEMI
  for (const r of valid) {
    const base = r * N_VERT + off
    for (let v = 0; v < N_HEMI; v++) out[v] += m.data[base + v]
  }
  const k = 1 / valid.length
  for (let v = 0; v < N_HEMI; v++) out[v] *= k
  return out
}

export interface RoiSeries {
  key: string
  label: string
  about: string
  mean: number
  std: number
  values: number[]
  z: number[]
}

export function roiSeries(
  roiMeans: Record<string, number[]>,
  groups: Record<string, { label: string; about: string }>,
): RoiSeries[] {
  return Object.entries(roiMeans).map(([key, values]) => {
    const mean = values.reduce((a, b) => a + b, 0) / Math.max(1, values.length)
    const std = Math.sqrt(values.reduce((a, b) => a + (b - mean) ** 2, 0) / Math.max(1, values.length))
    const z = values.map((v) => (std < 1e-6 ? 0 : (v - mean) / std))
    return { key, label: groups[key]?.label ?? key, about: groups[key]?.about ?? '', mean, std, values, z }
  })
}

export function clamp(x: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, x))
}
