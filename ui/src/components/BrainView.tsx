import { useEffect, useRef, useState } from 'react'
import { Niivue, SLICE_TYPE } from '@niivue/niivue'

type NVMeshLayer = NonNullable<Parameters<Niivue['loadMeshes']>[0][number]['layers']>[number]
import { api, type Parcels } from '@/lib/api'
import { N_HEMI, hemiWindowMean, type PredMatrix } from '@/lib/preds'

export type ViewName = 'both' | 'left' | 'right' | 'left-medial' | 'right-medial' | 'top' | 'front' | 'back'

export const VIEWS: { key: ViewName; label: string }[] = [
  { key: 'both', label: 'both' },
  { key: 'left', label: 'left' },
  { key: 'right', label: 'right' },
  { key: 'left-medial', label: 'L medial' },
  { key: 'right-medial', label: 'R medial' },
  { key: 'top', label: 'top' },
  { key: 'front', label: 'front' },
  { key: 'back', label: 'back' },
]

// azimuth/elevation for NiiVue's render camera; `hide` = hemisphere to hide (0 lh, 1 rh)
// scale zooms the render so single-hemisphere views fill the canvas
const CAMERA: Record<ViewName, { az: number; el: number; hide?: 0 | 1; scale: number }> = {
  both: { az: 120, el: 25, scale: 1.05 },
  left: { az: 90, el: 0, scale: 1.3 },
  right: { az: 270, el: 0, scale: 1.3 },
  'left-medial': { az: 270, el: 0, hide: 1, scale: 1.3 },
  'right-medial': { az: 90, el: 0, hide: 0, scale: 1.3 },
  top: { az: 180, el: 90, scale: 1.05 },
  front: { az: 180, el: 0, scale: 1.2 },
  back: { az: 0, el: 0, scale: 1.2 },
}

export const COLORMAPS: { key: string; label: string; pos: string; neg: string }[] = [
  { key: 'warm-winter', label: 'orange / blue', pos: 'warm', neg: 'winter' },
  { key: 'hot-cool', label: 'hot / cool', pos: 'hot', neg: 'cool' },
  { key: 'red-blue', label: 'red / blue', pos: 'red', neg: 'blue' },
  { key: 'plasma', label: 'plasma (positive only)', pos: 'plasma', neg: '' },
]

export interface BrainViewProps {
  runId: string
  preds: PredMatrix | null
  parcels: Parcels | null
  frame: number
  windowRows: number[] | null // when set, show the mean over these rows instead of `frame`
  threshold: number // a.u.
  range: number // a.u., colormap saturation
  colormap: string
  view: ViewName
  roiKey: string | null
  onReady?: (ok: boolean, msg?: string) => void
}

const L_PRED = 1
const L_MASK = 2

export function BrainView(p: BrainViewProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const nvRef = useRef<Niivue | null>(null)
  const [ready, setReady] = useState(false)
  const nTRef = useRef(0)
  const scratch = useRef<Float32Array[]>([new Float32Array(N_HEMI), new Float32Array(N_HEMI)])

  // create + load meshes once per run
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    let cancelled = false
    const nv = new Niivue({
      backColor: [0.09, 0.1, 0.13, 1],
      show3Dcrosshair: false,
      isOrientCube: false,
      isColorbar: false,
      meshThicknessOn2D: Infinity,
      dragMode: 1, // contrast-free: left drag rotates the render
    })
    nvRef.current = nv
    setReady(false)
    ;(async () => {
      try {
        await nv.attachToCanvas(canvas)
        nv.setSliceType(SLICE_TYPE.RENDER)
        const cm = COLORMAPS.find((c) => c.key === p.colormap) ?? COLORMAPS[0]
        const layers = (hemi: 'lh' | 'rh'): NVMeshLayer[] => [
          { url: api.urls.surf(`${hemi}.sulc.curv`), colormap: 'gray', opacity: 0.7, cal_min: 0, cal_max: 1 },
          {
            url: api.urls.preds(p.runId, hemi),
            colormap: cm.pos,
            colormapNegative: cm.neg || 'winter',
            useNegativeCmap: !!cm.neg,
            cal_min: p.threshold,
            cal_max: p.range,
            opacity: 1,
          },
          { url: api.urls.surf(`${hemi}.sulc.curv`), colormap: 'green', opacity: 0, cal_min: 0.5, cal_max: 1 },
        ] as unknown as NVMeshLayer[]
        await nv.loadMeshes([
          { url: api.urls.surf('lh.inflated.surf.gii'), layers: layers('lh') },
          { url: api.urls.surf('rh.inflated.surf.gii'), layers: layers('rh') },
        ])
        if (cancelled) return
        // append one scratch frame per hemisphere for window means
        for (const m of nv.meshes) {
          const L = m.layers[L_PRED]
          const nT = L.nFrame4D
          const ext = new Float32Array((nT + 1) * N_HEMI)
          ext.set(L.values as Float32Array)
          L.values = ext
          L.nFrame4D = nT + 1
          nTRef.current = nT
        }
        nv.setRenderAzimuthElevation(CAMERA[p.view].az, CAMERA[p.view].el)
        nv.setScale(CAMERA[p.view].scale)
        setReady(true)
        p.onReady?.(true)
      } catch (e) {
        console.error('BrainView', e)
        p.onReady?.(false, String(e))
      }
    })()
    return () => {
      cancelled = true
      nvRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.runId])

  // frame / window mean
  useEffect(() => {
    const nv = nvRef.current
    if (!nv || !ready) return
    const nT = nTRef.current
    if (p.windowRows && p.preds) {
      nv.meshes.forEach((m, h) => {
        const L = m.layers[L_PRED]
        const mean = hemiWindowMean(p.preds!, p.windowRows!, h as 0 | 1, scratch.current[h])
        ;(L.values as Float32Array).set(mean, nT * N_HEMI)
        L.frame4D = nT
        m.updateMesh(nv.gl)
      })
      nv.drawScene()
    } else {
      const f = Math.max(0, Math.min(nT - 1, p.frame))
      nv.meshes.forEach((m) => {
        m.layers[L_PRED].frame4D = f
        m.updateMesh(nv.gl)
      })
      nv.drawScene()
    }
  }, [ready, p.frame, p.windowRows, p.preds])

  // colormap / threshold / range
  useEffect(() => {
    const nv = nvRef.current
    if (!nv || !ready) return
    const cm = COLORMAPS.find((c) => c.key === p.colormap) ?? COLORMAPS[0]
    nv.meshes.forEach((m) => {
      const L = m.layers[L_PRED]
      L.colormap = cm.pos
      L.colormapNegative = cm.neg || 'winter'
      L.useNegativeCmap = !!cm.neg
      L.cal_min = p.threshold
      L.cal_max = Math.max(p.threshold + 0.01, p.range)
      m.updateMesh(nv.gl)
    })
    nv.drawScene()
  }, [ready, p.colormap, p.threshold, p.range])

  // camera / hemisphere visibility
  useEffect(() => {
    const nv = nvRef.current
    if (!nv || !ready) return
    const c = CAMERA[p.view]
    nv.meshes.forEach((m, h) => {
      m.visible = c.hide !== h
    })
    nv.setRenderAzimuthElevation(c.az, c.el)
    nv.setScale(c.scale)
    nv.drawScene()
  }, [ready, p.view])

  // ROI highlight mask
  useEffect(() => {
    const nv = nvRef.current
    if (!nv || !ready) return
    const g = p.roiKey && p.parcels ? p.parcels.roiGroups[p.roiKey] : null
    nv.meshes.forEach((m, h) => {
      const L = m.layers[L_MASK]
      if (g && p.parcels) {
        const ids = new Set(g.parcelIds)
        const src = h === 0 ? p.parcels.parcel.lh : p.parcels.parcel.rh
        const mask = new Float32Array(N_HEMI)
        for (let v = 0; v < N_HEMI; v++) mask[v] = ids.has(src[v]) ? 1 : 0
        L.values = mask
        L.nFrame4D = 1
        L.frame4D = 0
        L.cal_min = 0.5
        L.cal_max = 1
        L.opacity = 0.45
      } else {
        L.opacity = 0
      }
      m.updateMesh(nv.gl)
    })
    nv.drawScene()
  }, [ready, p.roiKey, p.parcels])

  return <canvas ref={canvasRef} className="brain-canvas" />
}
