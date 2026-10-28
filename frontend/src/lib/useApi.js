import { useCallback, useEffect, useState } from 'react'
import { api } from './api'

// Real loading / error / retry states; no artificial delays. Pass null to skip the request.
export function useApi(path, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: Boolean(path) })
  const load = useCallback(async () => {
    if (!path) { setState({ data: null, error: null, loading: false }); return } // null path = not applicable for this role; no request is made
    setState((s) => ({ ...s, loading: true, error: null }))
    try {
      setState({ data: await api(path), error: null, loading: false })
    } catch (e) {
      setState({ data: null, error: e, loading: false })
    }
  }, [path])
  useEffect(() => { load() }, [load, ...deps]) // eslint-disable-line react-hooks/exhaustive-deps
  return { ...state, reload: load }
}
