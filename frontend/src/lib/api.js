const TOKEN_KEY = 'trustlayer.token'

// Where the API lives. Unset (local dev) -> same-origin `/api`, which the Vite dev server proxies to the backend.
// Set VITE_API_URL to the backend origin (e.g. https://trustlayer-87fn.onrender.com) when the frontend is hosted
// apart from the backend. Vite inlines it at build time, so changing it needs a rebuild/redeploy.
// A trailing slash or a trailing `/api` on the value is tolerated.
export const API_BASE = `${(import.meta.env.VITE_API_URL || '').trim().replace(/\/+$/, '').replace(/\/api$/i, '')}/api`

export const getToken = () => sessionStorage.getItem(TOKEN_KEY)
export const setToken = (t) => (t ? sessionStorage.setItem(TOKEN_KEY, t) : sessionStorage.removeItem(TOKEN_KEY))

export class ApiError extends Error {
  constructor(status, message, extra) {
    super(message)
    this.status = status
    this.extra = extra
  }
}

function messageFrom(detail, status) {
  if (!detail) return `Request failed (${status})`
  if (typeof detail === 'string') return detail
  if (detail.message) return detail.message
  return `Request failed (${status})`
}

// `raw` sends a Blob as-is (used for recorded audio); otherwise `body` is sent as JSON.
export async function api(path, { method = 'GET', body, raw } = {}) {
  const headers = {}
  if (raw) headers['Content-Type'] = raw.type
  else if (body) headers['Content-Type'] = 'application/json'
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  let res
  try {
    res = await fetch(`${API_BASE}${path}`, { method, headers, body: raw || (body ? JSON.stringify(body) : undefined) })
  } catch {
    throw new ApiError(0, 'Cannot reach the TrustLayer server. Check that the backend is running and allows this site (CORS), then retry.')
  }
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    if (res.status === 401 && token) {
      setToken(null)
      window.dispatchEvent(new Event('trustlayer:logout'))
    }
    throw new ApiError(res.status, messageFrom(data?.detail, res.status), data?.detail)
  }
  return data
}
