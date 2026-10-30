import { useCallback, useEffect, useState } from 'react'
import { api } from './api'

// The backend (Neon PostgreSQL / SQLite / MySQL) the data pages are looking at. Remembered for the tab only.
const KEY = 'trustlayer.target'
const read = () => { try { return sessionStorage.getItem(KEY) || 'postgres' } catch { return 'postgres' } }

export function useTarget() {
  const [target, set] = useState(read)
  useEffect(() => {
    const on = () => set(read())
    window.addEventListener('trustlayer:target', on)
    return () => window.removeEventListener('trustlayer:target', on)
  }, [])
  const choose = useCallback((n) => {
    try { sessionStorage.setItem(KEY, n) } catch { /* private mode: the choice just is not remembered */ }
    window.dispatchEvent(new Event('trustlayer:target'))
  }, [])
  return [target, choose]
}

// The last health check the server returned, shared by every page so moving between pages does not wait on the databases again.
// It is only a display cache: each page re-checks in the background, and "Check again" forces a fresh server-side check.
let last = null
window.addEventListener('trustlayer:logout', () => { last = null })

// Live backend list from the server plus the chosen one. `ready` is true only when the server reports a real connection and the schema.
export function useBackends() {
  const [target, choose] = useTarget()
  const [state, setState] = useState({ data: last, error: null, loading: !last })
  const load = useCallback(async (fresh = false) => {
    setState((s) => ({ ...s, loading: true, error: null }))
    try {
      last = await api(`/b1/targets${fresh ? '?fresh=1' : ''}`)
      setState({ data: last, error: null, loading: false })
    } catch (e) {
      setState({ data: null, error: e, loading: false })
    }
  }, [])
  useEffect(() => { load(false) }, [load])
  const targets = state.data?.targets || []
  const current = targets.find((t) => t.name === target)
  const ready = Boolean(current?.connected && current?.schema_found)
  return { ...state, reload: () => load(true), target, choose, targets, current, ready }
}
