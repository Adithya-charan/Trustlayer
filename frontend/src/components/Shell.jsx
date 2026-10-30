import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { AudioLines, ClipboardList, Cpu, Database, FileSearch, Gauge, KeyRound, LogOut, Menu, Settings, SlidersHorizontal, X } from 'lucide-react'
import { NAV, canSee } from '../lib/router'
import { Logo } from './brand'
import { Badge, cn } from './ui'
import AssistantDock from '../assistant/AssistantDock'
import { AssistantContext } from '../assistant/AssistantContext'
import { useAssistant } from '../assistant/useAssistant'
import { useLiveVoice } from '../assistant/useLiveVoice'
import VoiceCommand from '../voice/VoiceCommand'

const ICONS = { overview: Gauge, discovery: FileSearch, explorer: Database, policies: SlidersHorizontal, access: KeyRound, audit: ClipboardList, voice: AudioLines, automation: Cpu, settings: Settings }
// Soft colored icon containers; active item uses a light blue background with an accent bar.
const TINT = {
  blue: 'bg-blue-50 text-blue-600', violet: 'bg-violet-50 text-violet-600', rose: 'bg-rose-50 text-rose-600', teal: 'bg-teal-50 text-teal-600',
  amber: 'bg-amber-50 text-amber-600', green: 'bg-green-50 text-green-600', slate: 'bg-slate-100 text-slate-600',
}
const ROLE_LABEL = { security_admin: 'Security admin', compliance_officer: 'Compliance officer', advisor: 'Financial advisor', analyst: 'Data analyst', Admin: 'Admin', Support: 'Support', Analyst: 'Analyst' }

function Sidebar({ me, route, onNavigate, onLogout }) {
  const items = NAV.filter((n) => canSee(n, me.role))
  const groups = [...new Set(items.map((n) => n.group))]
  return (
    <nav aria-label="Primary" className="flex h-full flex-col border-r border-slate-200 bg-white">
      <a href="#/" className="flex items-center px-5 py-5" aria-label="TrustLayer home"><Logo id="side-logo" /></a>
      <div className="flex-1 space-y-5 overflow-y-auto px-3 pb-4">
        {groups.map((g) => (
          <div key={g}>
            <p className="px-3 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">{g}</p>
            <ul className="space-y-0.5">
              {items.filter((n) => n.group === g).map((n) => {
                const Icon = ICONS[n.id]
                const active = route === n.id
                return (
                  <li key={n.id}>
                    <a href={`#/${n.id}`} aria-current={active ? 'page' : undefined} onClick={onNavigate}
                      className={cn('group relative flex min-h-10 items-center gap-3 rounded-xl px-3 text-sm font-medium transition-colors', active ? 'bg-blue-50 text-navy-700' : 'text-slate-600 hover:bg-slate-50 hover:text-body')}>
                      {active && <motion.span layoutId="nav-active" className="absolute inset-y-2 left-0 w-1 rounded-r-full bg-navy-600" />}
                      <span className={cn('flex h-7 w-7 items-center justify-center rounded-lg', TINT[n.color])}><Icon className="h-4 w-4" aria-hidden /></span>
                      {n.label}
                    </a>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </div>
      <div className="m-3 rounded-2xl border border-slate-200 bg-mist p-3">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-navy-600 to-violet-600 text-xs font-semibold uppercase text-white">{me.username.slice(0, 2)}</span>
          <div className="min-w-0 text-xs leading-tight"><p className="truncate font-semibold text-body">{me.username}</p><p className="truncate text-muted">{ROLE_LABEL[me.role]}</p></div>
        </div>
        <button onClick={onLogout} className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-50 active:scale-[0.98]"><LogOut className="h-3.5 w-3.5" aria-hidden /> Sign out</button>
        <p className="mt-2 text-[10px] leading-snug text-slate-500">Synthetic demo data. Prototype, not a compliance certification.</p>
      </div>
    </nav>
  )
}

export default function Shell({ me, route, go, bump, onLogout, children }) {
  const [open, setOpen] = useState(false)
  const assistant = useAssistant({ route, go, role: me.role })
  const live = useLiveVoice({ receive: assistant.receive, setLiveActive: assistant.setLiveActive })
  const current = NAV.find((n) => n.id === route)
  useEffect(() => { document.title = `${current?.label || 'TrustLayer'} · TrustLayer` }, [current])
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <AssistantContext.Provider value={{ assistant, live }}>
    <div className="min-h-screen bg-mist">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:p-2">Skip to content</a>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 lg:block"><Sidebar me={me} route={route} onLogout={onLogout} /></aside>
      <AnimatePresence>
        {open && (
          <>
            <motion.div className="fixed inset-0 z-40 bg-slate-200/70 backdrop-blur-sm lg:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setOpen(false)} />
            <motion.aside className="fixed inset-y-0 left-0 z-50 w-72 max-w-[85vw] shadow-2xl lg:hidden" initial={{ x: -300 }} animate={{ x: 0 }} exit={{ x: -300 }} transition={{ duration: 0.2 }}>
              <button className="absolute right-2 top-4 z-10 rounded-lg p-1.5 text-slate-500 hover:bg-slate-100" onClick={() => setOpen(false)} aria-label="Close navigation"><X className="h-5 w-5" /></button>
              <Sidebar me={me} route={route} onNavigate={() => setOpen(false)} onLogout={onLogout} />
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      <div className="lg:pl-64">
        <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-slate-200 bg-white/90 px-4 py-2.5 backdrop-blur sm:px-6">
          <button className="rounded-xl p-2 text-slate-700 hover:bg-slate-100 lg:hidden" onClick={() => setOpen(true)} aria-label="Open navigation"><Menu className="h-5 w-5" /></button>
          <nav aria-label="Breadcrumb" className="min-w-0 text-sm">
            <ol className="flex items-center gap-1.5 text-muted">
              <li className="hidden sm:block">TrustLayer</li><li aria-hidden className="hidden sm:block">/</li>
              {current && <><li className="hidden sm:block">{current.group}</li><li aria-hidden className="hidden sm:block">/</li></>}
              <li className="truncate font-semibold text-body" aria-current="page">{current?.label || 'Not found'}</li>
            </ol>
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <VoiceCommand go={go} bump={bump} />
            <Badge tone="info" className="hidden lg:inline-flex">Synthetic demo data</Badge>
            <a href="#/" className="hidden rounded-lg px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-100 md:block">Product page</a>
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-navy-600 to-violet-600 text-xs font-semibold uppercase text-white lg:hidden" aria-hidden>{me.username.slice(0, 2)}</span>
          </div>
        </header>
        <main id="main" className="mx-auto max-w-[88rem] px-4 py-6 sm:px-6 lg:px-8">{children}</main>
      </div>
      <AssistantDock assistant={assistant} role={me.role} />
    </div>
    </AssistantContext.Provider>
  )
}
