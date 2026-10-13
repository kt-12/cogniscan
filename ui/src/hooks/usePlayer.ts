import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Slide } from '@/lib/api'
import { clamp } from '@/lib/preds'

export type ViewMode = 'second' | 'window'

export interface Player {
  t: number
  second: number
  playing: boolean
  speed: number
  loopStep: boolean
  mode: ViewMode
  stepIdx: number
  step: Slide | null
  duration: number
  videoRef: React.RefObject<HTMLVideoElement | null>
  seek: (t: number, opts?: { keepMode?: boolean }) => void
  gotoStep: (i: number, play?: boolean) => void
  toggle: () => void
  setSpeed: (s: number) => void
  setLoopStep: (b: boolean) => void
  setMode: (m: ViewMode) => void
}

/** Single source of truth for playback. The <video> element drives time while playing. */
export function usePlayer(slides: Slide[], duration: number): Player {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [t, setT] = useState(slides[0]?.stats.t0 ?? 0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeedState] = useState(1)
  const [loopStep, setLoopStep] = useState(false)
  const [mode, setModeState] = useState<ViewMode>('window')
  const [stepIdx, setStepIdx] = useState(0)
  const loopRef = useRef(loopStep)
  useEffect(() => {
    loopRef.current = loopStep
  }, [loopStep])

  const stepFor = useCallback(
    (time: number) => {
      let best = -1
      for (let i = 0; i < slides.length; i++) {
        const s = slides[i].stats
        if (time >= s.t0 && time < s.t1) return i
        if (time >= s.t0) best = i
      }
      return Math.max(0, best)
    },
    [slides],
  )

  // follow the video clock
  useEffect(() => {
    let raf = 0
    const tick = () => {
      const v = videoRef.current
      if (v && !v.paused && !v.ended) {
        let now = v.currentTime
        if (loopRef.current) {
          const s = slides[stepIdx]?.stats
          if (s && now >= s.t1 - 0.05) {
            v.currentTime = s.t0
            now = s.t0
          }
        }
        setT(now)
        const i = stepFor(now)
        setStepIdx((cur) => (i !== cur ? i : cur))
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [slides, stepFor, stepIdx])

  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    const onPlay = () => setPlaying(true)
    const onPause = () => setPlaying(false)
    v.addEventListener('play', onPlay)
    v.addEventListener('pause', onPause)
    v.addEventListener('ended', onPause)
    return () => {
      v.removeEventListener('play', onPlay)
      v.removeEventListener('pause', onPause)
      v.removeEventListener('ended', onPause)
    }
  }, [])

  const seek = useCallback(
    (time: number, opts?: { keepMode?: boolean }) => {
      const tt = clamp(time, 0, Math.max(0, duration - 0.05))
      setT(tt)
      setStepIdx(stepFor(tt))
      if (!opts?.keepMode) setModeState('second')
      const v = videoRef.current
      if (v) {
        if (v.readyState >= 1) v.currentTime = tt
        else v.addEventListener('loadedmetadata', () => (v.currentTime = tt), { once: true })
      }
    },
    [duration, stepFor],
  )

  const gotoStep = useCallback(
    (i: number, play = false) => {
      const s = slides[clamp(i, 0, slides.length - 1)]
      if (!s) return
      setStepIdx(s.i)
      const tt = clamp(s.stats.t0, 0, Math.max(0, duration - 0.05))
      setT(tt)
      const v = videoRef.current
      if (v) {
        v.currentTime = tt
        if (play) void v.play()
        else v.pause()
      }
      if (!play) setModeState('window')
    },
    [slides, duration],
  )

  const toggle = useCallback(() => {
    const v = videoRef.current
    if (!v) return
    if (v.paused) {
      setModeState('second')
      void v.play()
    } else v.pause()
  }, [])

  const setSpeed = useCallback((s: number) => {
    setSpeedState(s)
    if (videoRef.current) videoRef.current.playbackRate = s
  }, [])

  const setMode = useCallback((m: ViewMode) => {
    setModeState(m)
    if (m === 'window') videoRef.current?.pause()
  }, [])

  const step = slides[stepIdx] ?? null
  return useMemo(
    () => ({
      t,
      second: Math.floor(t),
      playing,
      speed,
      loopStep,
      mode,
      stepIdx,
      step,
      duration,
      videoRef,
      seek,
      gotoStep,
      toggle,
      setSpeed,
      setLoopStep,
      setMode,
    }),
    [t, playing, speed, loopStep, mode, stepIdx, step, duration, seek, gotoStep, toggle, setSpeed, setMode],
  )
}
