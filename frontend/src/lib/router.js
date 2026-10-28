import { useEffect, useState } from 'react'

// Tiny hash router: keeps the app a single page with shareable section URLs and no extra dependency.
const read = () => (window.location.hash.replace(/^#\/?/, '') || 'overview').split('?')[0]

export function useRoute() {
  const [route, setRoute] = useState(read)
  useEffect(() => {
    const on = () => setRoute(read())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return [route, (r) => { window.location.hash = `/${r}` }]
}

export const AUDITORS = ['security_admin', 'compliance_officer']

// UI visibility only. Every endpoint enforces the real permission on the server.
export const NAV = [
  { id: 'overview', label: 'Overview', roles: null },
  { id: 'discovery', label: 'Data Discovery', roles: null },
  { id: 'policies', label: 'Policies & Masking', roles: null },
  { id: 'access', label: 'Access Console', roles: null },
  { id: 'risk', label: 'Risk & Security', roles: AUDITORS },
  { id: 'audit', label: 'Audit Trail', roles: null },
  { id: 'insurance', label: 'Insurance Needs', roles: ['advisor'] },
  { id: 'automation', label: 'Automation', roles: AUDITORS },
  { id: 'settings', label: 'Settings', roles: null },
]
export const canSee = (item, role) => !item.roles || item.roles.includes(role)
