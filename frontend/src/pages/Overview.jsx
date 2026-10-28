import { useState } from 'react'
import { useApi } from '../lib/useApi'
import { AUDITORS } from '../lib/router'
import { Badge, Button, Empty, ErrorState, Loading, Metric, MetricStrip, PageHeader, Panel, PanelHeader, Select, Table, Td, Th, fmtTime } from '../components/ui'
import { CHART_COLORS, Donut, HBars, TimeBars } from '../components/charts'

const CATEGORY_LABEL = { DIRECT_IDENTIFIER: 'Direct identifier', GOVERNMENT_ID: 'Government ID', ACCOUNT_IDENTIFIER: 'Account identifier', CONTACT: 'Contact', FINANCIAL: 'Financial', DEMOGRAPHIC: 'Demographic', NON_SENSITIVE: 'Non-sensitive' }

export default function Overview({ me, version, go, onTrace }) {
  const [days, setDays] = useState('14')
  const auditor = AUDITORS.includes(me.role)
  const m = useApi(`/metrics/overview?days=${days}`, [version])
  const scans = useApi('/scans?limit=5', [version])
  const recent = useApi(auditor ? '/audit?limit=6' : '/my-requests', [version, auditor])
  const flows = useApi(auditor ? '/automation/workflows' : null, [version, auditor])

  const d = m.data
  const events = auditor ? recent.data?.events : recent.data?.slice(0, 6)
  const period = d ? `Last ${d.range.days} days (UTC), ${d.scope}` : ''
  const t = d?.decisions.totals

  return (
    <>
      <PageHeader
        title="Security overview"
        description="Live metrics derived from persisted scans, policy decisions, risk events and workflow reports. Nothing on this page is sample or simulated data."
        actions={<Select label="Time range" value={days} onChange={setDays} options={[['7', 'Last 7 days'], ['14', 'Last 14 days'], ['30', 'Last 30 days']]} />}
      />
      {m.loading && !d && <Panel><Loading label="Loading metrics" /></Panel>}
      {m.error && <Panel><ErrorState error={m.error} onRetry={m.reload} /></Panel>}
      {d && (
        <div className="space-y-5">
          <MetricStrip>
            <Metric label="Sensitive fields" value={`${d.fields.sensitive} / ${d.fields.total}`} sub={d.fields.total ? `${d.fields.reviewed} corrected by a reviewer` : 'No scan has run yet'} />
            <Metric label="Scans in period" value={d.scans.completed + d.scans.failed} sub={`${d.scans.completed} completed · ${d.scans.failed} failed`} tone={d.scans.failed ? 'bad' : undefined} />
            <Metric label="Access decisions" value={d.decisions.events_counted} sub={`${t.ALLOW} allowed · ${t.PARTIAL} masked · ${t.DENY} denied`} />
            {d.risk.available
              ? <Metric label="Security events" value={d.risk.total} sub={`${d.risk.by_severity.HIGH || 0} high · ${d.risk.by_severity.MEDIUM || 0} medium`} tone={d.risk.by_severity.HIGH ? 'bad' : undefined} />
              : <Metric label="Data source" value={d.source.records} sub="synthetic demo records" />}
          </MetricStrip>
          <p className="-mt-3 text-xs text-slate-500">{period}. Decisions count query and insurance requests; scans and security events are counted by start time.</p>

          <div className="grid gap-5 lg:grid-cols-3">
            <Panel className="lg:col-span-2">
              <PanelHeader title="Access decisions over time" subtitle={`Requests per day, ${period.toLowerCase()}`} />
              <div className="p-5">
                <TimeBars series={d.decisions.series} keys={['ALLOW', 'PARTIAL', 'DENY']} labels={{ ALLOW: 'Allowed', PARTIAL: 'Masked', DENY: 'Denied' }}
                  emptyTitle="No access decisions in this period" emptyHint="Run a request in the Access Console or an insurance assessment and it will appear here." unit="decisions" />
              </div>
            </Panel>
            <Panel>
              <PanelHeader title="Sensitive-field classification" subtitle="Current classification of discovered fields" />
              <div className="p-5">
                <HBars data={Object.entries(d.fields.by_category).map(([k, v]) => ({ label: CATEGORY_LABEL[k] || k, value: v }))} emptyTitle="No fields discovered yet" />
                {d.fields.total === 0 && <Button variant="outline" size="sm" className="mx-auto mt-2" onClick={() => go('discovery')}>Go to Data Discovery</Button>}
              </div>
            </Panel>
          </div>

          <div className="grid gap-5 lg:grid-cols-3">
            <Panel>
              <PanelHeader title="Scan activity" subtitle="Completed and failed scans per day" />
              <div className="p-5"><TimeBars series={d.scans.series} keys={['COMPLETED', 'FAILED']} labels={{ COMPLETED: 'Completed', FAILED: 'Failed' }} height={110} emptyTitle="No scans in this period" unit="scans" /></div>
            </Panel>
            <Panel>
              <PanelHeader title="Masking strategies applied" subtitle="Across audited field decisions in period" />
              <div className="p-5"><HBars data={Object.entries(d.masking.strategies_applied).map(([k, v]) => ({ label: k, value: v }))} emptyTitle="No protected fields returned yet" /></div>
            </Panel>
            {d.risk.available ? (
              <Panel>
                <PanelHeader title="Risk severity" subtitle="Security events by severity" />
                <div className="p-5"><Donut data={Object.entries(d.risk.by_severity).map(([k, v]) => ({ label: k, value: v, color: CHART_COLORS[k] }))} emptyTitle="No security events in this period" /></div>
              </Panel>
            ) : (
              <Panel><PanelHeader title="Risk severity" /><Empty title="Restricted to auditors" hint="Security events are visible to security admins and compliance officers." /></Panel>
            )}
          </div>

          {d.automation.available && (
            <Panel>
              <PanelHeader title="Automation runs" subtitle="n8n workflow runs reported to TrustLayer" actions={<Button variant="ghost" size="sm" onClick={() => go('automation')}>Open Automation</Button>} />
              <div className="p-5"><TimeBars series={d.automation.series} keys={['SUCCESS', 'FAILED']} labels={{ SUCCESS: 'Succeeded', FAILED: 'Failed' }} height={90} emptyTitle="No workflow runs reported in this period" emptyHint="Workflows post a run report to TrustLayer when they execute in n8n." unit="runs" /></div>
            </Panel>
          )}

          <div className="grid gap-5 lg:grid-cols-2">
            <Panel>
              <PanelHeader title="Latest scans" />
              {scans.loading && !scans.data && <Loading />}
              {scans.error && <ErrorState error={scans.error} onRetry={scans.reload} />}
              {scans.data?.length === 0 && <Empty title="No scans yet" hint={me.role === 'security_admin' ? 'Start one from Data Discovery.' : 'A security admin runs the first scan.'} />}
              {scans.data?.length > 0 && (
                <Table caption="Latest scans">
                  <thead><tr><Th>Status</Th><Th>Finished</Th><Th>Sensitive</Th><Th>By</Th></tr></thead>
                  <tbody>{scans.data.map((s) => <tr key={s.id}><Td><Badge tone={s.status}>{s.status}</Badge></Td><Td className="text-xs">{fmtTime(s.finished_at)}</Td><Td>{s.sensitive_found}/{s.fields_scanned}</Td><Td className="text-xs">{s.triggered_by}</Td></tr>)}</tbody>
                </Table>
              )}
            </Panel>
            <Panel>
              <PanelHeader title={auditor ? 'Recent policy decisions' : 'Your recent requests'} actions={<Button variant="ghost" size="sm" onClick={() => go('audit')}>Audit Trail</Button>} />
              {recent.loading && !recent.data && <Loading />}
              {recent.error && <ErrorState error={recent.error} onRetry={recent.reload} />}
              {events?.length === 0 && <Empty title="No decisions recorded" hint="Requests you make appear here with their explanation." />}
              {events?.length > 0 && (
                <ul className="divide-y divide-slate-100">
                  {events.map((e) => (
                    <li key={e.request_id}>
                      <button onClick={() => onTrace(e.request_id)} className="flex w-full flex-wrap items-center gap-2 px-5 py-2.5 text-left text-sm hover:bg-slate-50">
                        <Badge tone={e.decision}>{e.decision}</Badge><span className="font-medium text-slate-800">{e.operation}</span><span className="text-slate-500">{auditor ? `${e.actor} · ` : ''}{e.purpose}</span>
                        <span className="ml-auto text-xs text-slate-500">{fmtTime(e.ts)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>

          {auditor && (
            <Panel>
              <PanelHeader title="Recent automation executions" subtitle="From run reports posted by n8n" />
              {flows.error && <ErrorState error={flows.error} onRetry={flows.reload} />}
              {flows.data && !flows.data.workflows.some((w) => w.recent_runs.length) && <Empty title="No workflow runs have been reported" hint="n8n has not executed a workflow against this backend yet, so there is nothing to show." />}
              {flows.data?.workflows?.some((w) => w.recent_runs.length) && (
                <Table caption="Recent workflow runs">
                  <thead><tr><Th>Workflow</Th><Th>Status</Th><Th>Time</Th><Th>Detail</Th></tr></thead>
                  <tbody>{flows.data.workflows.flatMap((w) => w.recent_runs.slice(0, 2).map((r) => ({ ...r, name: w.name }))).sort((a, b) => b.ts.localeCompare(a.ts)).slice(0, 6).map((r) => <tr key={`${r.name}-${r.id}`}><Td>{r.name}</Td><Td><Badge tone={r.status}>{r.status}</Badge></Td><Td className="text-xs">{fmtTime(r.ts)}</Td><Td className="text-xs text-slate-600">{r.detail}</Td></tr>)}</tbody>
                </Table>
              )}
            </Panel>
          )}
        </div>
      )}
    </>
  )
}
