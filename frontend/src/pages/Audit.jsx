import { Fragment, useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, RefreshCw } from 'lucide-react'
import { useApi } from '../lib/useApi'
import { Badge, Button, Empty, ErrorState, Loading, Notice, PageHeader, Panel, PanelHeader, Select, Table, Td, Th, TextInput, fmtTime, qs } from '../components/ui'
import { ActivityList, BeforeAfter, Strategy, personName } from '../components/b1'

const OPS = [['', 'All operations'], ['query', 'Queries'], ['scan', 'Scans'], ['review', 'Classification reviews'], ['policy_change', 'Policy changes'], ['upload_analyze', 'Dataset uploads']]
const EMPTY = { user: '', role: '', decision: '', operation: '', resource: '', hours: '' }
const label = (op) => op.replace(/^b1_/, '').replace('_', ' ')

// The Audit Center: every important access decision, with field NAMES and strategies only; never values.
// Recent activity: the meaningful movements of every user (not UI noise), or one user's history including policy changes made to them.
function Activity({ version, initialUser }) {
  const [user, setUser] = useState(initialUser || '')
  useEffect(() => { setUser(initialUser || '') }, [initialUser])
  const users = useApi('/b1/users')
  const url = user ? `/b1/activity/users/${encodeURIComponent(user)}?limit=50` : '/b1/activity?limit=50'
  const { data, error, loading, reload } = useApi(url, [user, version])
  const who = (users.data?.users || []).find((u) => u.username === user)
  return (
    <Panel>
      <PanelHeader title={user ? `${personName(who || { username: user })}'s history` : 'Recent activity'} subtitle={user ? `${who ? `${who.role} · ` : ''}everything they did, and policy changes made to them (newest first)` : 'Queries, denied attempts, policy changes, classification reviews, scans and sign-ins (newest first)'}
        actions={<Button size="sm" variant="outline" onClick={reload} loading={loading}><RefreshCw className="h-4 w-4" aria-hidden /> Refresh</Button>} />
      <div className="flex flex-wrap items-end gap-3 border-b border-slate-100 p-4">
        <Select label="User" value={user} onChange={setUser} options={[['', 'Everyone'], ...(users.data?.users || []).map((u) => [u.username, `${personName(u)} (${u.role})`])]} className="min-w-56" />
        {user && <Button size="sm" variant="ghost" onClick={() => setUser('')}>Show everyone</Button>}
      </div>
      {loading && !data ? <Loading label="Loading activity" /> : error ? <ErrorState error={error} onRetry={reload} /> : <ActivityList events={data?.events} onUser={setUser} empty={user ? 'This user has no recorded activity yet' : undefined} />}
    </Panel>
  )
}

export default function Audit({ params, version }) {
  const [tab, setTab] = useState(params.get('view') === 'activity' ? 'activity' : 'events')
  useEffect(() => { if (params.get('view') === 'activity') setTab('activity'); else if (params.get('operation') || params.get('decision') || params.get('role')) setTab('events') }, [params.toString()]) // eslint-disable-line react-hooks/exhaustive-deps
  const [f, setF] = useState(EMPTY)
  const [open, setOpen] = useState(null)
  const sp = params.toString()
  useEffect(() => { // voice commands and links open a pre-filtered view
    setF({ user: params.get('user') || '', role: params.get('role') || '', decision: params.get('decision') || '', operation: params.get('operation') || '', resource: params.get('resource') || '', hours: params.get('hours') || '' })
  }, [sp]) // eslint-disable-line react-hooks/exhaustive-deps
  const { data, error, loading, reload } = useApi(`/b1/audit${qs({ ...f, limit: 100 })}`, [version])
  const set = (k) => (v) => setF((s) => ({ ...s, [k]: v }))
  const events = useMemo(() => data?.events || [], [data])
  const counts = useMemo(() => events.reduce((a, e) => ({ ...a, [e.decision]: (a[e.decision] || 0) + 1 }), {}), [events])
  const filtered = Object.values(f).some(Boolean)

  return (
    <>
      <PageHeader title="Audit Center" description="Every scan, query, classification review and policy change: who did it, under which policy, which sensitive fields were touched and what the decision was. Recorded server-side; field names and strategies only, never data values."
        actions={<Button variant="outline" onClick={reload} loading={loading}><RefreshCw className="h-4 w-4" aria-hidden /> Refresh</Button>} />
      <div role="tablist" aria-label="Audit views" className="mb-4 inline-flex rounded-xl border border-slate-200 bg-white p-1 text-sm">
        {[['events', 'Audit events'], ['activity', 'Recent activity']].map(([k, t]) => (
          <button key={k} role="tab" type="button" aria-selected={tab === k} onClick={() => setTab(k)} className={`min-h-9 rounded-lg px-4 font-medium ${tab === k ? 'bg-navy-600 text-white' : 'text-slate-700 hover:bg-slate-50'}`}>{t}</button>
        ))}
      </div>
      {tab === 'activity' ? <Activity version={version} initialUser={params.get('user') || ''} /> : <Panel>
        <PanelHeader title="Events" subtitle={`${events.length} shown (newest first)${filtered ? ', filtered' : ''}`}
          actions={<span className="flex gap-1.5 text-xs"><Badge tone="ALLOW">{counts.ALLOW || 0} allowed</Badge><Badge tone="MASK">{counts.MASK || 0} masked</Badge><Badge tone="DENY">{counts.DENY || 0} denied</Badge></span>} />
        <div className="flex flex-wrap items-end gap-3 border-b border-slate-100 p-4">
          <TextInput label="User" value={f.user} onChange={(e) => set('user')(e.target.value)} placeholder="e.g. analyst_kavya" className="w-44" />
          <Select label="Role" value={f.role} onChange={set('role')} options={[['', 'Any role'], 'Admin', 'Support', 'Analyst']} />
          <Select label="Decision" value={f.decision} onChange={set('decision')} options={[['', 'Any decision'], ['ALLOW', 'Allowed'], ['MASK', 'Masked'], ['DENY', 'Denied']]} />
          <Select label="Operation" value={f.operation} onChange={set('operation')} options={OPS} />
          <TextInput label="Table" value={f.resource} onChange={(e) => set('resource')(e.target.value)} placeholder="e.g. cards" className="w-36" />
          <Select label="Period" value={f.hours} onChange={set('hours')} options={[['', 'All time'], ['1', 'Last hour'], ['24', 'Last 24 hours'], ['168', 'Last 7 days']]} />
          {filtered && <Button size="sm" variant="ghost" onClick={() => setF(EMPTY)}>Clear filters</Button>}
        </div>
        {loading && !data ? <Loading label="Loading audit events" /> : error ? <ErrorState error={error} onRetry={reload} /> : !events.length ? (
          <Empty title={filtered ? 'No events match these filters' : 'No events recorded yet'} hint={filtered ? 'Clear a filter or widen the period.' : 'Run a query or scan and it will appear here immediately.'} />
        ) : (
          <Table caption="Audit events">
            <thead><tr><Th>Time</Th><Th>User</Th><Th>Role</Th><Th>Resource</Th><Th>Operation</Th><Th>Sensitive fields</Th><Th>Policy applied</Th><Th>Decision</Th><Th>Query ref</Th></tr></thead>
            <tbody>{events.map((e) => {
              const names = Object.entries(e.fields || {})
              const isOpen = open === e.request_id
              return (
                <Fragment key={e.request_id}>
                  <tr className="cursor-pointer" onClick={() => setOpen(isOpen ? null : e.request_id)}>
                    <Td className="whitespace-nowrap text-xs">{fmtTime(e.ts)}</Td>
                    <Td className="text-xs">{e.actor}</Td><Td className="text-xs">{e.role}</Td>
                    <Td className="font-mono text-xs">{e.resource || '-'}</Td>
                    <Td className="whitespace-nowrap text-xs"><button type="button" aria-expanded={isOpen} className="inline-flex items-center gap-1">{isOpen ? <ChevronDown className="h-3.5 w-3.5" aria-hidden /> : <ChevronRight className="h-3.5 w-3.5" aria-hidden />}{label(e.operation)}</button></Td>
                    <Td className="text-xs text-slate-700">{names.length ? <span title={names.map(([n, v]) => `${n}: ${v.strategy}`).join('\n')}>{names.slice(0, 3).map(([n]) => n).join(', ')}{names.length > 3 ? ` +${names.length - 3}` : ''}</span> : '-'}</Td>
                    <Td className="font-mono text-[11px] text-slate-600">{e.policy}</Td>
                    <Td><Badge tone={e.decision}>{e.decision}</Badge></Td>
                    <Td className="font-mono text-[11px] text-slate-500">{e.request_id.slice(0, 8)}</Td>
                  </tr>
                  {isOpen && (
                    <tr><td colSpan={9} className="border-t border-slate-100 bg-slate-50/60 px-5 py-4">
                      <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-3" aria-label="Who, what, why">
                        <div><dt className="text-[11px] font-medium uppercase tracking-wide text-slate-500">Who</dt><dd className="text-sm text-slate-900">{e.actor_name} <span className="text-slate-500">({e.role})</span></dd></div>
                        <div><dt className="text-[11px] font-medium uppercase tracking-wide text-slate-500">What</dt><dd className="text-sm text-slate-900">{e.action}{e.resource ? ` · ${e.resource}` : ''}</dd></div>
                        <div><dt className="text-[11px] font-medium uppercase tracking-wide text-slate-500">Policy applied</dt><dd className="font-mono text-xs text-slate-900">{e.policy}</dd></div>
                        <div><dt className="text-[11px] font-medium uppercase tracking-wide text-slate-500">Decision</dt><dd><Badge tone={e.decision}>{e.decision}</Badge></dd></div>
                        <div className="sm:col-span-2"><dt className="text-[11px] font-medium uppercase tracking-wide text-slate-500">Result</dt><dd className="text-sm text-slate-900">{e.change ? <span className="inline-flex flex-wrap items-center gap-2">{e.change.subject} · {e.change.kind} <BeforeAfter old={e.change.old} next={e.change.new} /></span> : e.result}</dd></div>
                      </dl>
                      {e.why?.length > 0 && <ul className="mt-3 space-y-1 text-sm text-slate-800" aria-label="Why">{e.why.map((w, i) => <li key={i}><span className="font-semibold">Why: </span>{w}</li>)}</ul>}
                      <p className="mt-3 text-xs text-slate-500">{e.reason}</p>
                      {names.length > 0 && (
                        <ul className="mt-3 flex flex-wrap gap-2" aria-label="Masking result per field">{names.map(([n, v]) => <li key={n} className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs"><span className="font-mono">{n}</span><span className="text-slate-400">{v.category}</span><Strategy s={v.strategy} /></li>)}</ul>
                      )}
                      <p className="mt-3 font-mono text-[11px] text-slate-500">query ref {e.request_id}</p>
                    </td></tr>
                  )}
                </Fragment>
              )
            })}</tbody>
          </Table>
        )}
      </Panel>}
      <Notice tone="info" className="mt-4">The audit trail stores which fields were touched and how each was protected, never the values themselves.</Notice>
    </>
  )
}
