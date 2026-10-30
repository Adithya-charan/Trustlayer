import { useEffect, useState } from 'react'

// Tiny hash router: a single-page app with shareable URLs and no extra dependency.
// '' (empty hash) is the public landing page, 'signin' the sign-in screen, everything else is the dashboard.
// A route may carry a query (`audit?decision=DENY`); pages read it as `params`, so voice commands and links can open a filtered view.
const read = () => window.location.hash.replace(/^#\/?/, '') || ''
const split = (raw) => { const [path, query = ''] = raw.split('?'); return [path, new URLSearchParams(query)] }

export function useRoute() {
  const [raw, setRaw] = useState(read)
  useEffect(() => {
    const on = () => { setRaw(read()); window.scrollTo(0, 0) }
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  const [route, params] = split(raw)
  return [route, (r) => { window.location.hash = `/${r}` }, params, raw]
}

export const AUDITORS = ['security_admin', 'compliance_officer']
export const B1_ADMIN = ['Admin', 'security_admin']
export const B1_ALL = ['Admin', 'Support', 'Analyst', 'security_admin', 'analyst']

// UI visibility only. Every endpoint enforces the real permission on the server.
export const NAV = [
  { id: 'overview', label: 'Overview', roles: B1_ALL, group: 'Protect', color: 'blue' },
  { id: 'discovery', label: 'Data Discovery', roles: B1_ALL, group: 'Protect', color: 'violet' },
  { id: 'explorer', label: 'Data Explorer', roles: B1_ALL, group: 'Protect', color: 'teal' },
  { id: 'policies', label: 'Access Policies', roles: B1_ALL, group: 'Govern', color: 'amber' },
  { id: 'access', label: 'Users & Access', roles: B1_ADMIN, group: 'Govern', color: 'blue' },
  { id: 'audit', label: 'Audit Center', roles: B1_ADMIN, group: 'Govern', color: 'rose' },
  { id: 'voice', label: 'Voice Assistant', roles: null, group: 'Operate', color: 'violet' },
  { id: 'automation', label: 'Automation', roles: AUDITORS, group: 'Operate', color: 'violet' },
  { id: 'settings', label: 'Settings', roles: null, group: 'Operate', color: 'slate' },
]
// Accounts from the organizer's sample users (Admin / Support / Analyst) are the data-protection roles.
export const B1_ROLES = ['Admin', 'Support', 'Analyst']
export const canSee = (item, role) => !item.roles || item.roles.includes(role)
export const homeFor = () => 'overview'
