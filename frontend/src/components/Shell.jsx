import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Bell, ChevronDown, ClipboardList, Cpu, FileSearch, Gauge, KeyRound, LogOut, Menu, Settings, ShieldAlert, ShieldCheck, SlidersHorizontal, X, Calculator } from 'lucide-react'
import { useApi } from '../lib/useApi'
import { AUDITORS, NAV, canSee } from '../lib/router'
import { Badge, cn } from './ui'

const ICONS = { overview: Gauge, discovery: FileSearch, policies: SlidersHorizontal, access: KeyRound, risk: ShieldAlert, audit: ClipboardList, insurance: Calculator, automation: Cpu, settings: Settings }
const ROLE_LABEL = { security_admin: 'Security admin', compliance_officer: 'Compliance officer', advisor: 'Financial advisor', analyst: 'Data analyst' }

function Sidebar({ me, route, go, onNavigate }) {
  return (
    <nav aria-label="Primary" className="flex h-full flex-col bg-navy-900 text-slate-300">
      <div className="flex items-center gap-2 px-5 py-5 text-white">
        <ShieldCheck className="h-6 w-6 text-teal-400" aria-hidden />
        <span className="text-lg font-semibold tracking-tight">TrustLayer</span>
      </div>
      <ul className="flex-1 space-y-0.5 px-3">
        {NAV.filter((n) => canSee(n, me.role)).map((n) => {
          const Icon = ICONS[n.id]
          const active = route === n.id
          return (
            <li key={n.id}>
              <a
                href={`#/${n.id}`}
                aria-current={active ? 'page' : undefined}
                onClick={() => { go(n.id); onNavigate?.() }}
                className={cn('flex min-h-10 items-center gap-3 rounded-lg px-3 text-sm font-medium transition-colors', active ? 'bg-white/10 text-white' : 'hover:bg-white/5 hover:text-white')}
              >
                <Icon className={cn('h-4 w-4', active ? 'text-teal-400' : 'text-slate-400')} aria-hidden />
                {n.label}
              </a>
            </li>
          )
        })}
      </ul>
      <p className="px-5 py-4 text-[11px] leading-snug text-slate-400">Prototype on synthetic data. Not a compliance certification.</p>
    </nav>
  )
}

function Bell24({ role, goTo }) {
  const auditor = AUDITORS.includes(role)
  const { data } = useApi(auditor ? '/risk/events?severity=HIGH&limit=1' : null, [role])
  if (!auditor) return null
  const high = data?.total || 0
  return (
    <button onClick={() => goTo('risk')} className="relative rounded-lg p-2 text-slate-600 hover:bg-slate-100" aria-label={`Security notifications: ${high} high-severity events recorded`}>
      <Bell className="h-5 w-5" aria-hidden />
      {high > 0 && <span className="absolute right-0.5 top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-semibold text-white">{high}</span>}
    </button>
  )
}

export default function Shell({ me, route, go, onLogout, children }) {
  const [open, setOpen] = useState(false)
  const [menu, setMenu] = useState(false)
  const current = NAV.find((n) => n.id === route)
  useEffect(() => { document.title = `${current?.label || 'TrustLayer'} · TrustLayer` }, [current])
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && (setOpen(false), setMenu(false))
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="min-h-screen bg-slate-50">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:p-2">Skip to content</a>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 lg:block"><Sidebar me={me} route={route} go={go} /></aside>
      <AnimatePresence>
        {open && (
          <>
            <motion.div className="fixed inset-0 z-40 bg-slate-900/50 lg:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setOpen(false)} />
            <motion.aside className="fixed inset-y-0 left-0 z-50 w-64 lg:hidden" initial={{ x: -260 }} animate={{ x: 0 }} exit={{ x: -260 }} transition={{ duration: 0.2 }}>
              <button className="absolute right-2 top-3 z-10 rounded p-1 text-slate-300" onClick={() => setOpen(false)} aria-label="Close navigation"><X className="h-5 w-5" /></button>
              <Sidebar me={me} route={route} go={go} onNavigate={() => setOpen(false)} />
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      <div className="lg:pl-60">
        <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-slate-200 bg-white/95 px-4 py-2.5 backdrop-blur">
          <button className="rounded-lg p-2 text-slate-700 hover:bg-slate-100 lg:hidden" onClick={() => setOpen(true)} aria-label="Open navigation"><Menu className="h-5 w-5" /></button>
          <nav aria-label="Breadcrumb" className="min-w-0 text-sm">
            <ol className="flex items-center gap-1.5 text-slate-500">
              <li>TrustLayer</li><li aria-hidden>/</li>
              <li className="truncate font-medium text-slate-900" aria-current="page">{current?.label || 'Not found'}</li>
            </ol>
          </nav>
          <div className="ml-auto flex items-center gap-1">
            <Badge tone="info" className="hidden sm:inline-flex">Synthetic demo data</Badge>
            <Bell24 role={me.role} goTo={go} />
            <div className="relative">
              <button onClick={() => setMenu((m) => !m)} aria-expanded={menu} aria-haspopup="menu" className="flex min-h-10 items-center gap-2 rounded-lg px-2 hover:bg-slate-100">
                <span className="flex h-8 w-8 items-center justify-center rounded-full bg-navy-700 text-xs font-semibold uppercase text-white">{me.username.slice(0, 2)}</span>
                <span className="hidden text-left text-xs leading-tight sm:block"><span className="block font-medium text-slate-900">{me.username}</span><span className="text-slate-500">{ROLE_LABEL[me.role]}</span></span>
                <ChevronDown className="h-4 w-4 text-slate-500" aria-hidden />
              </button>
              {menu && (
                <div role="menu" className="absolute right-0 mt-1 w-56 rounded-xl border border-slate-200 bg-white p-1 shadow-lg">
                  <p className="px-3 py-2 text-xs text-slate-500">Signed in as <span className="font-medium text-slate-800">{me.username}</span><br />Role: {ROLE_LABEL[me.role]}</p>
                  <button role="menuitem" onClick={onLogout} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-800 hover:bg-slate-100"><LogOut className="h-4 w-4" aria-hidden /> Sign out</button>
                </div>
              )}
            </div>
          </div>
        </header>
        <main id="main" className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
          <motion.div key={route} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.15 }}>{children}</motion.div>
        </main>
      </div>
    </div>
  )
}
