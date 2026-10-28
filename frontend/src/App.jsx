import { useCallback, useEffect, useState } from 'react'
import { api, getToken, setToken } from './lib/api'
import { NAV, canSee, useRoute } from './lib/router'
import Login from './components/Login'
import Shell from './components/Shell'
import TraceDialog from './components/TraceDialog'
import { Empty, Loading, Panel } from './components/ui'
import Overview from './pages/Overview'
import Discovery from './pages/Discovery'
import Policies from './pages/Policies'
import Access from './pages/Access'
import Risk from './pages/Risk'
import Audit from './pages/Audit'
import Insurance from './pages/Insurance'
import Automation from './pages/Automation'
import SettingsPage from './pages/Settings'

const PAGES = { overview: Overview, discovery: Discovery, policies: Policies, access: Access, risk: Risk, audit: Audit, insurance: Insurance, automation: Automation, settings: SettingsPage }

export default function App() {
  const [me, setMe] = useState(null)
  const [booting, setBooting] = useState(Boolean(getToken()))
  const [route, go] = useRoute()
  const [traceId, setTraceId] = useState(null)
  const [version, setVersion] = useState(0) // bumped after actions so dependent pages refetch real data
  const bump = useCallback(() => setVersion((v) => v + 1), [])

  useEffect(() => {
    if (!getToken()) return
    api('/auth/me').then(setMe).catch(() => setToken(null)).finally(() => setBooting(false))
  }, [])
  useEffect(() => {
    const out = () => setMe(null)
    window.addEventListener('trustlayer:logout', out)
    return () => window.removeEventListener('trustlayer:logout', out)
  }, [])

  if (booting) return <main className="p-8"><Loading label="Restoring session" /></main>
  if (!me) return <Login onLogin={setMe} />

  const item = NAV.find((n) => n.id === route)
  const Page = PAGES[route]
  const allowed = item && canSee(item, me.role)

  return (
    <Shell me={me} route={route} go={go} onLogout={() => { setToken(null); setMe(null) }}>
      {!Page ? (
        <Panel><Empty title="Page not found" hint="Choose a section from the sidebar." /></Panel>
      ) : !allowed ? (
        <Panel><Empty title="Not available for your role" hint="This section is restricted. The server also rejects direct requests to its data." /></Panel>
      ) : (
        <Page me={me} version={version} bump={bump} go={go} onTrace={setTraceId} />
      )}
      <TraceDialog requestId={traceId} onClose={() => setTraceId(null)} />
    </Shell>
  )
}
