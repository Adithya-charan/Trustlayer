import { useState } from 'react'
import { FlaskConical } from 'lucide-react'
import { api } from '../lib/api'
import { useApi } from '../lib/useApi'
import { Badge, Button, Empty, ErrorState, Loading, Metric, MetricStrip, Notice, PageHeader, Pager, Panel, PanelHeader, Select, Table, Td, Th, fmtTime, qs } from '../components/ui'

const PAGE = 10

export default function Risk({ me, version, bump, onTrace }) {
  const [sev, setSev] = useState('')
  const [evOffset, setEvOffset] = useState(0)
  const [rkOffset, setRkOffset] = useState(0)
  const events = useApi(`/risk/events${qs({ severity: sev, limit: PAGE, offset: evOffset })}`, [version])
  const evals = useApi(`/risk/evaluations${qs({ limit: PAGE, offset: rkOffset })}`, [version])
  const alerts = useApi('/alerts?limit=8', [version])
  const [running, setRunning] = useState(false)
  const [scenario, setScenario] = useState(null)
  const [scenarioErr, setScenarioErr] = useState(null)

  async function runScenario() {
    setRunning(true); setScenario(null); setScenarioErr(null)
    try { setScenario(await api('/risk/scenarios/reconstruction', { method: 'POST' })) }
    catch (e) { setScenarioErr(e) } finally { setRunning(false); bump() }
  }
  const sevs = events.data?.by_severity || {}

  return (
    <>
      <PageHeader title="Risk & security" description="Security events raised by explainable, deterministic rules, and every request whose risk score was above zero. Events are never invented to populate this page." />
      <div className="space-y-5">
        <MetricStrip>
          <Metric label="Security events" value={events.data ? Object.values(sevs).reduce((a, b) => a + b, 0) : '—'} sub="all time" />
          <Metric label="High severity" value={sevs.HIGH || 0} sub="requests blocked" tone={sevs.HIGH ? 'bad' : undefined} />
          <Metric label="Medium severity" value={sevs.MEDIUM || 0} sub="masking tightened" />
          <Metric label="Risk-scored requests" value={evals.data?.total ?? '—'} sub="risk score above 0" />
        </MetricStrip>

        <Panel>
          <PanelHeader title="Security events" subtitle="Rule, severity and response recorded when a risk threshold was crossed." actions={<Select label="Severity" value={sev} onChange={(v) => { setSev(v); setEvOffset(0) }} options={[['', 'All'], 'HIGH', 'MEDIUM']} />} />
          {events.loading && !events.data && <Loading />}
          {events.error && <ErrorState error={events.error} onRetry={events.reload} />}
          {events.data?.items.length === 0 && <Empty title="No security events" hint="Nothing has crossed a risk threshold. Use the scenario runner below to exercise the rules with synthetic requests." />}
          {events.data?.items.length > 0 && (
            <>
              <Table caption="Security events">
                <thead><tr><Th>Severity</Th><Th>Category</Th><Th>Time</Th><Th>Principal</Th><Th>Response</Th><Th>Reason</Th><Th>Audit</Th></tr></thead>
                <tbody>{events.data.items.map((e) => (
                  <tr key={e.id}><Td><Badge tone={e.severity}>{e.severity}</Badge></Td><Td className="text-xs font-medium">{e.rule}</Td><Td className="text-xs">{fmtTime(e.ts)}</Td><Td className="text-xs">{e.actor}</Td>
                    <Td className="text-xs">{e.response}</Td><Td className="max-w-xs text-xs text-slate-600">{e.detail}</Td><Td><Button variant="ghost" size="sm" onClick={() => onTrace(e.request_id)}>Trace</Button></Td></tr>))}</tbody>
              </Table>
              <Pager total={events.data.total} offset={evOffset} limit={PAGE} onChange={setEvOffset} />
            </>
          )}
        </Panel>

        <Panel>
          <PanelHeader title="Risk evaluations" subtitle="Requests that carried a non-zero risk score, with the signals that fired." />
          {evals.error && <ErrorState error={evals.error} onRetry={evals.reload} />}
          {evals.data?.items.length === 0 && <Empty title="No risk-scored requests" />}
          {evals.data?.items.length > 0 && (
            <>
              <Table caption="Risk evaluations">
                <thead><tr><Th>Time</Th><Th>Principal</Th><Th>Decision</Th><Th>Score</Th><Th>Response</Th><Th>Signals</Th><Th>Audit</Th></tr></thead>
                <tbody>{evals.data.items.map((e) => (
                  <tr key={e.request_id}><Td className="text-xs">{fmtTime(e.ts)}</Td><Td className="text-xs">{e.actor}<span className="block text-slate-400">{e.role}</span></Td><Td><Badge tone={e.decision}>{e.decision}</Badge></Td><Td className="tabular-nums">{e.risk_score}</Td>
                    <Td className="text-xs">{e.risk_response || '—'}</Td><Td className="text-xs text-slate-600">{e.risk_signals.map((s) => s.rule).join(', ')}</Td><Td><Button variant="ghost" size="sm" onClick={() => onTrace(e.request_id)}>Trace</Button></Td></tr>))}</tbody>
              </Table>
              <Pager total={evals.data.total} offset={rkOffset} limit={PAGE} onChange={setRkOffset} />
            </>
          )}
        </Panel>

        <div className="grid gap-5 lg:grid-cols-2">
          <Panel>
            <PanelHeader title="Risk scenario runner" subtitle="Real requests through the real rules, under a dedicated synthetic principal." />
            <div className="space-y-3 p-5 text-sm">
              <p className="text-slate-600">Sends six reconstruction-style probes for one synthetic customer (PAN, account number, email, phone…). Expect the first few to pass, then the rules to block. Results are genuine audit and security events, labelled with principal <code>scenario-{me.username}</code>; your own account is unaffected.</p>
              {me.role === 'security_admin' ? <Button onClick={runScenario} loading={running}><FlaskConical className="h-4 w-4" aria-hidden /> Run scenario</Button> : <p className="text-xs text-slate-500">Only security admins can run scenarios.</p>}
              {scenarioErr && <Notice tone="error">{scenarioErr.message}</Notice>}
              {scenario && (
                <Table caption="Scenario steps">
                  <thead><tr><Th>#</Th><Th>Requested</Th><Th>Outcome</Th><Th>Risk</Th></tr></thead>
                  <tbody>{scenario.steps.map((s, i) => (
                    <tr key={i}><Td>{i + 1}</Td><Td className="font-mono text-xs">{s.requested.join(', ')}</Td><Td><Badge tone={s.outcome === 'ALLOWED' ? 'ALLOW' : 'DENY'}>{s.outcome}</Badge></Td>
                      <Td className="text-xs">score {s.risk.score}{s.risk.response ? ` · ${s.risk.response}` : ''}{s.request_id && <button className="ml-1 underline" onClick={() => onTrace(s.request_id)}>trace</button>}</Td></tr>))}</tbody>
                </Table>
              )}
              {scenario && <p className="text-xs text-slate-500">{scenario.note}</p>}
            </div>
          </Panel>
          <Panel>
            <PanelHeader title="Alerts routed by n8n" subtitle="Development channel only" />
            {alerts.data && <p className="px-5 pt-3 text-xs text-slate-500">{alerts.data.channel_note}</p>}
            {alerts.error && <ErrorState error={alerts.error} onRetry={alerts.reload} />}
            {alerts.data?.items.length === 0 && <Empty title="No alerts routed" hint="The Security alerts workflow records one entry per high-severity event it processes." />}
            {alerts.data?.items.length > 0 && (
              <Table caption="Alert deliveries">
                <thead><tr><Th>Event</Th><Th>Rule</Th><Th>Severity</Th><Th>Channel</Th><Th>Recorded</Th></tr></thead>
                <tbody>{alerts.data.items.map((a) => <tr key={a.id}><Td>#{a.event_id}</Td><Td className="text-xs">{a.rule}</Td><Td><Badge tone={a.severity}>{a.severity}</Badge></Td><Td className="text-xs">{a.channel}</Td><Td className="text-xs">{fmtTime(a.ts)}</Td></tr>)}</tbody>
              </Table>
            )}
          </Panel>
        </div>
      </div>
    </>
  )
}
