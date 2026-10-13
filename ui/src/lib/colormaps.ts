import type { Theme } from '@/hooks/useTheme'

type RGB = [number, number, number]

/** NiiVue colormap: control points at intensities I (0..255). */
export interface NvColormap {
  R: number[]
  G: number[]
  B: number[]
  A: number[]
  I: number[]
}

interface Palette {
  key: string
  label: string
  pos: RGB[] // weak → strong
  neg: RGB[] | null
}

// Weak = light, strong = dark and saturated, so strong responses stand out on the light cortex of both themes.
const PALETTES: Palette[] = [
  {
    key: 'warm-cool',
    label: 'orange / blue',
    pos: [[253, 196, 82], [249, 131, 36], [226, 62, 40], [158, 22, 52]],
    neg: [[103, 204, 245], [45, 140, 235], [43, 84, 205], [42, 38, 128]],
  },
  {
    key: 'red-blue',
    label: 'red / blue',
    pos: [[250, 160, 150], [233, 78, 70], [150, 22, 34]],
    neg: [[150, 196, 250], [62, 128, 240], [26, 52, 140]],
  },
  {
    key: 'magenta-teal',
    label: 'magenta / teal',
    pos: [[247, 160, 205], [224, 62, 150], [130, 16, 96]],
    neg: [[120, 216, 200], [20, 158, 150], [10, 86, 96]],
  },
  {
    key: 'plasma',
    label: 'plasma (positive only)',
    pos: [[13, 8, 135], [126, 3, 168], [204, 71, 120], [248, 149, 64], [240, 249, 33]],
    neg: null,
  },
]

export const COLORMAPS = PALETTES.map((p) => ({ key: p.key, label: p.label }))

const find = (key: string) => PALETTES.find((p) => p.key === key) ?? PALETTES[0]

function toNv(stops: RGB[]): NvColormap {
  const n = stops.length
  return {
    R: stops.map((s) => s[0]),
    G: stops.map((s) => s[1]),
    B: stops.map((s) => s[2]),
    A: stops.map(() => 255),
    I: stops.map((_, i) => Math.round((i / (n - 1)) * 255)),
  }
}

/** Every colormap the viewer uses, keyed by the name BrainView hands to NiiVue. */
export function nvColormaps(): Record<string, NvColormap> {
  const out: Record<string, NvColormap> = { [CORTEX.light.colormap]: toNv([[255, 255, 255], [204, 207, 214]]) }
  for (const p of PALETTES) {
    out[`cs-${p.key}-pos`] = toNv(p.pos)
    if (p.neg) out[`cs-${p.key}-neg`] = toNv(p.neg)
  }
  return out
}

export function nvNames(key: string): { pos: string; neg: string | null } {
  const p = find(key)
  return { pos: `cs-${p.key}-pos`, neg: p.neg ? `cs-${p.key}-neg` : null }
}

/** Canvas background and the sulcal-depth shading under the activation, per theme. */
export const CORTEX = {
  light: { back: [1, 1, 1, 1], mesh: [255, 255, 255, 255], colormap: 'cs-cortex-light', calMin: -1.2, calMax: 1.5, opacity: 1, css: '#dfe1e6' },
  dark: { back: [0.09, 0.1, 0.13, 1], mesh: [255, 255, 255, 255], colormap: 'gray', calMin: 0, calMax: 1, opacity: 0.7, css: '#3a3f4b' },
} as const

/** CSS gradient for the legend: strong negative … threshold gap … strong positive. */
export function legendGradient(key: string, theme: Theme): string {
  const p = find(key)
  const css = (c: RGB) => `rgb(${c.join(' ')})`
  const mid = CORTEX[theme].css
  const pos = p.pos
  const neg = p.neg ? [...p.neg].reverse() : []
  const at = (i: number, n: number, a: number, b: number) => `${(a + (n > 1 ? i / (n - 1) : 0) * (b - a)).toFixed(1)}%`
  return `linear-gradient(90deg, ${[
    ...neg.map((c, i) => `${css(c)} ${at(i, neg.length, 0, 44)}`),
    `${mid} 47%`,
    `${mid} 53%`,
    ...pos.map((c, i) => `${css(c)} ${at(i, pos.length, 56, 100)}`),
  ].join(', ')})`
}
