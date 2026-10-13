import { useSyncExternalStore } from 'react'

export type Theme = 'light' | 'dark'

// index.html applies the stored theme before first paint; the `dark` class on <html> is the source of truth
const KEY = 'cogniscan-theme'
const listeners = new Set<() => void>()

const read = (): Theme => (document.documentElement.classList.contains('dark') ? 'dark' : 'light')

export function setTheme(t: Theme) {
  document.documentElement.classList.toggle('dark', t === 'dark')
  try {
    localStorage.setItem(KEY, t)
  } catch {
    // storage blocked: the choice just lasts for this page load
  }
  listeners.forEach((l) => l())
}

function subscribe(l: () => void) {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, read)
  return { theme, setTheme, toggle: () => setTheme(theme === 'dark' ? 'light' : 'dark') }
}
