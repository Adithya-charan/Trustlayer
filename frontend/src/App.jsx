import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react'
import { api, getToken, setToken } from './lib/api'
import { NAV, canSee, homeFor, useRoute } from './lib/router'
import Login from './components/Login'
import Shell from './components/Shell'
import TraceDialog from './components/TraceDialog'
import { Empty, Loading, Panel } from './components/ui'
import { PageTransition } from './components/brand'

// The public page is loaded on demand so the dashboard bundle stays lean.
const Landing = lazy(() => import('./landing/Landing'))
const page = (name) => lazy(() => import(`./pages/${name}.jsx`))
const Overview = page('Overview'), Discovery = page('Discovery'), Explorer = page('Explorer'), Policies = page('Policies'), Access = page('Access')
const Audit = page('Audit'), Automation = page('Automation'), SettingsPage = page('Settings'), Voice = page('VoiceAssistant')
const PAGES = { overview: Overview, discovery: Discovery, explorer: Explorer, policies: Policies, access: Access, audit: Audit, voice: Voice, automation: Automation, settings: SettingsPage }

export default function App() {
  const [me, setMe] = useState(null)
  const [booting, setBooting] = useState(Boolean(getToken()))
  const [route, go, params] = useRoute()
  const [traceId, setTraceId] = useState(null)
  const [version, setVersion] = useState(0) // bumped after actions so dependent pages refetch real data
  const [next, setNext] = useState(null) // page the visitor asked for before signing in
  const leaving = useRef(false) // set while signing out so the guard does not bounce the visitor to the sign-in screen
  const bump = useCallback(() => setVersion((v) => v + 1), [])

  useEffect(() => {
    if (!getToken()) return
    api('/auth/me').then(setMe).catch(() => setToken(null)).finally(() => setBooting(false))
  }, [])
  useEffect(() => {
    const out = () => { setMe(null); go('signin') }
    window.addEventListener('trustlayer:logout', out)
    return () => window.removeEventListener('trustlayer:logout', out)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const isApp = Boolean(PAGES[route]) || (route !== '' && route !== 'signin')
  // Dashboard routes require a session: remember the target and send the visitor to sign in.
  useEffect(() => {
    if (route === '') leaving.current = false
    if (!booting && !me && isApp && !leaving.current) { setNext(route); go('signin') }
  }, [booting, me, isApp, route]) // eslint-disable-line react-hooks/exhaustive-deps
  // A section the signed-in role cannot see (old bookmark, wrong role): send them to the Overview instead of a dead end.
  useEffect(() => {
    const item = NAV.find((n) => n.id === route)
    if (me && route !== '' && route !== 'signin' && (!item || !canSee(item, me.role))) go(homeFor(me.role))
  }, [me, route]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (me && route === 'signin') go(next && PAGES[next] ? next : homeFor(me.role)) }, [me, route]) // eslint-disable-line react-hooks/exhaustive-deps

  if (route === '') {
    return <Suspense fallback={<div className="min-h-screen bg-mist" />}><Landing /></Suspense>
  }
  if (booting) return <main className="p-8"><Loading label="Restoring session" /></main>
  if (!me) return <Login onLogin={setMe} />

  const item = NAV.find((n) => n.id === route)
  const Page = PAGES[route]
  const allowed = item && canSee(item, me.role)

  return (
    <Shell me={me} route={route} go={go} bump={bump} onLogout={() => { leaving.current = true; setToken(null); setMe(null); go('') }}>
      <PageTransition pageKey={route}>
        {!Page ? (
          <Panel><Empty title="Page not found" hint="Choose a section from the sidebar." /></Panel>
        ) : !allowed ? (
          <Panel><Empty title="Not available for your role" hint="This section is restricted. The server also rejects direct requests to its data." /></Panel>
        ) : (
          <Suspense fallback={<Panel><Loading label="Loading page" /></Panel>}><Page me={me} version={version} bump={bump} go={go} params={params} onTrace={setTraceId} /></Suspense>
        )}
      </PageTransition>
      <TraceDialog requestId={traceId} onClose={() => setTraceId(null)} />
    </Shell>
  )
}
