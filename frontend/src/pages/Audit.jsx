import { useState } from 'react'
import { useApi } from '../lib/useApi'
import { AUDITORS } from '../lib/router'
import { Badge, Button, Empty, ErrorState, Loading, PageHeader, Pager, Panel, PanelHeader, Select, Table, Td, TextInput, Th, fmtTime, qs } from '../components/ui'

const LIMIT = 15
const BLANK = { q: '', actor: '', decision: '', operation: '', purpose: '', role: '', since_days: '', min_risk: '' }

function Mine({ version, onTrace }) {
  const { data, error, loading, reload } = useApi('/my-requests', [version])
  return (
    <Panel>
      <PanelHeader title="Your recent requests" subtitle="Your role can see only its own requests. Security admins and compliance officers can see the full trail." />
      {loading && !data && <Loading />}
      {error && <ErrorState error={error} onRetry={reload} />}
      {data?.length === 0 && <Empty title="No requests yet" hint="Requests you make in the Access Console or Insurance Needs appear here." />}
      {data?.length > 0 && (
        <Table caption="Your requests">
          <thead><tr><Th>Time</Th><Th>Action</Th><Th>Purpose</Th><Th>Decision</Th><Th>Policy</Th><Th>Trace</Th></tr></thead>
          <tbody>{data.map((e) => <tr key={e.request_id}><Td className="text-xs">{fmtTime(e.ts)}</Td><Td>{e.operation}</Td><Td className="text-xs">{e.purpose}</Td><Td><Badge tone={e.decision}>{e.decision}</Badge></Td><Td className="text-xs">{e.policy}</Td><Td><Button variant="ghost" size="sm" onClick={() => onTrace(e.request_id)}>Why?</Button></Td></tr>)}</tbody>
        </Table>
      )}
    </Panel>
  )
}

export default function Audit({ me, version, onTrace }) {
  const [f, setF] = useState(BLANK)
  const [offset, setOffset] = useState(0)
  const auditor = AUDITORS.includes(me.role)
  const { data, error, loading, reload } = useApi(auditor ? `/audit${qs({ ...f, limit: LIMIT, offset })}` : null, [version, auditor, offset, ...Object.values(f)])
  const set = (k) => (v) => { setF((x) => ({ ...x, [k]: v })); setOffset(0) }
  const filtered = Object.values(f).some(Boolean)

  if (!auditor) return (<><PageHeader title="Audit trail" description="Structured, value-free records of every decision." /><Mine version={version} onTrace={onTrace} /></>)

  return (
    <>
      <PageHeader title="Audit trail" description="Every decision is recorded with safe metadata only: field names and strategies, never values. Filters and pagination run on the server." />
      <Panel>
        <div className="flex flex-wrap items-end gap-3 border-b border-slate-100 px-5 py-4">
          <TextInput label="Search" value={f.q} onChange={(e) => set('q')(e.target.value)} placeholder="request id, actor, policy, reason" className="w-60" />
          <TextInput label="Actor" value={f.actor} onChange={(e) => set('actor')(e.target.value)} className="w-32" />
          <Select label="Decision" value={f.decision} onChange={set('decision')} options={[['', 'All'], 'ALLOW', 'PARTIAL', 'DENY']} />
          <Select label="Action" value={f.operation} onChange={set('operation')} options={[['', 'All'], 'query', 'insurance_assess', 'insurance_estimate', 'scan', 'review_field', 'policy_change', 'risk_scenario']} />
          <Select label="Role" value={f.role} onChange={set('role')} options={[['', 'All'], 'security_admin', 'compliance_officer', 'advisor', 'analyst', 'automation']} />
          <Select label="Period" value={f.since_days} onChange={set('since_days')} options={[['', 'All time'], ['1', 'Last 24 h'], ['7', 'Last 7 days'], ['30', 'Last 30 days']]} />
          <Select label="Risk" value={f.min_risk} onChange={set('min_risk')} options={[['', 'Any'], ['1', 'Score ≥ 1'], ['2', 'Score ≥ 2'], ['4', 'Score ≥ 4']]} />
          {filtered && <Button variant="ghost" size="sm" onClick={() => { setF(BLANK); setOffset(0) }}>Clear filters</Button>}
        </div>
        {loading && !data && <Loading />}
        {error && <ErrorState error={error} onRetry={reload} />}
        {data?.events.length === 0 && <Empty title={filtered ? 'No audit events match these filters' : 'No audit events yet'} hint={filtered ? 'Widen or clear a filter.' : 'Events are recorded as soon as anyone scans, queries or runs an assessment.'} />}
        {data?.events.length > 0 && (
          <>
            <Table caption="Audit events">
              <thead><tr><Th>Event</Th><Th>Time</Th><Th>Actor</Th><Th>Action</Th><Th>Resource / fields</Th><Th>Decision</Th><Th>Policy</Th><Th>Risk</Th></tr></thead>
              <tbody>{data.events.map((e) => (
                <tr key={e.request_id} className="hover:bg-slate-50">
                  <Td><button onClick={() => onTrace(e.request_id)} className="font-mono text-xs text-navy-700 underline-offset-2 hover:underline" aria-label={`Inspect event ${e.request_id}`}>{e.request_id.slice(0, 8)}</button></Td>
                  <Td className="whitespace-nowrap text-xs">{fmtTime(e.ts)}</Td><Td className="text-xs">{e.actor}<span className="block text-slate-400">{e.role}</span></Td>
                  <Td className="text-xs">{e.operation}<span className="block text-slate-400">{e.purpose}</span></Td>
                  <Td className="max-w-[14rem] truncate font-mono text-[11px] text-slate-600" title={Object.keys(e.fields).join(', ')}>{Object.keys(e.fields).join(', ') || '—'}</Td>
                  <Td><Badge tone={e.decision}>{e.decision}</Badge></Td><Td className="text-xs">{e.policy}</Td>
                  <Td className="text-xs">{e.risk_response ? <Badge tone="MEDIUM">{e.risk_response}</Badge> : e.risk_score || '0'}</Td>
                </tr>))}</tbody>
            </Table>
            <Pager total={data.total} offset={offset} limit={LIMIT} onChange={setOffset} />
          </>
        )}
        {data && <p className="border-t border-slate-100 px-5 py-3 text-xs text-slate-500">Matching events: {data.total}{Object.keys(data.summary).length ? ` (${Object.entries(data.summary).map(([k, v]) => `${k} ${v}`).join(' · ')})` : ''}. Retention: kept until manually purged (prototype assumption).</p>}
      </Panel>
    </>
  )
}
