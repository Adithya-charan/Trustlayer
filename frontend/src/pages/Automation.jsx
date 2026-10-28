import { useState } from 'react'
import { ExternalLink } from 'lucide-react'
import { useApi } from '../lib/useApi'
import { Badge, Empty, ErrorState, Loading, Notice, PageHeader, Panel, PanelHeader, Table, Td, Th, fmtTime } from '../components/ui'

export default function Automation({ version }) {
  const wf = useApi('/automation/workflows', [version])
  const reports = useApi('/reports?limit=5', [version])
  const [open, setOpen] = useState(null)

  return (
    <>
      <PageHeader title="Automation" description="n8n orchestrates scheduled scans, security alerts and summary reports. It is not a security boundary: every call it makes is authenticated and authorized by this backend."
        actions={wf.data && <a href={wf.data.editor_url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 text-sm font-medium hover:bg-slate-50">Open n8n editor <ExternalLink className="h-4 w-4" aria-hidden /></a>} />
      <div className="space-y-5">
        <Panel>
          <PanelHeader title="Workflows" subtitle="Last run and counts come from run reports each workflow posts to TrustLayer." />
          {wf.loading && !wf.data && <Loading />}
          {wf.error && <ErrorState error={wf.error} onRetry={wf.reload} />}
          {wf.data && (
            <>
              <Table caption="n8n workflows">
                <thead><tr><Th>Workflow</Th><Th>Schedule</Th><Th>Last status</Th><Th>Last run</Th><Th>Succeeded</Th><Th>Failed</Th><Th>History</Th></tr></thead>
                <tbody>{wf.data.workflows.map((w) => (
                  <tr key={w.key}>
                    <Td><span className="font-medium">{w.name}</span><span className="block font-mono text-[11px] text-slate-400">{w.file}</span></Td>
                    <Td className="text-xs">{w.schedule}</Td>
                    <Td>{w.last_status ? <Badge tone={w.last_status}>{w.last_status}</Badge> : <span className="text-xs text-slate-500">no run reported</span>}</Td>
                    <Td className="text-xs">{fmtTime(w.last_run_at)}</Td><Td className="tabular-nums">{w.success_count}</Td><Td className="tabular-nums">{w.failure_count}</Td>
                    <Td><button className="text-xs text-navy-700 underline" aria-expanded={open === w.key} onClick={() => setOpen(open === w.key ? null : w.key)}>{open === w.key ? 'Hide' : 'Show'} runs</button></Td>
                  </tr>))}</tbody>
              </Table>
              {open && (
                <div className="border-t border-slate-100 bg-slate-50 px-5 py-4">
                  {wf.data.workflows.find((w) => w.key === open).recent_runs.length === 0 ? <Empty title="No runs reported for this workflow" hint="Execute it in n8n. Nothing is shown until a run report arrives." /> : (
                    <Table caption="Recent runs">
                      <thead><tr><Th>Status</Th><Th>Time</Th><Th>Attempt</Th><Th>Detail (redacted)</Th></tr></thead>
                      <tbody>{wf.data.workflows.find((w) => w.key === open).recent_runs.map((r) => <tr key={r.id}><Td><Badge tone={r.status}>{r.status}</Badge></Td><Td className="text-xs">{fmtTime(r.ts)}</Td><Td>{r.attempt}</Td><Td className="text-xs text-slate-600">{r.detail || '—'}</Td></tr>)}</tbody>
                    </Table>
                  )}
                </div>
              )}
              <p className="border-t border-slate-100 px-5 py-3 text-xs text-slate-500">{wf.data.source}</p>
            </>
          )}
        </Panel>

        <Panel>
          <PanelHeader title="Stored summary reports" subtitle="Produced by the Audit summary workflow (aggregate counts only)." />
          {reports.error && <ErrorState error={reports.error} onRetry={reports.reload} />}
          {reports.data?.length === 0 && <Empty title="No reports stored yet" hint="The report appears here after the Audit summary workflow runs." />}
          {reports.data?.length > 0 && (
            <Table caption="Stored reports">
              <thead><tr><Th>Period</Th><Th>Decisions</Th><Th>Security events</Th><Th>Scans</Th><Th>Stored</Th></tr></thead>
              <tbody>{reports.data.map((r) => <tr key={r.id}><Td className="text-xs">{fmtTime(r.period_start)} → {fmtTime(r.period_end)}</Td><Td className="text-xs">{Object.entries(r.report.decisions || {}).map(([k, v]) => `${k} ${v}`).join(' · ') || 'none'}</Td><Td className="text-xs">{Object.entries(r.report.security_events || {}).map(([k, v]) => `${k} ${v}`).join(' · ') || 'none'}</Td><Td className="text-xs">{Object.entries(r.report.scans || {}).map(([k, v]) => `${k} ${v}`).join(' · ') || 'none'}</Td><Td className="text-xs">{fmtTime(r.created_at)}</Td></tr>)}</tbody>
            </Table>
          )}
        </Panel>

        <Panel>
          <PanelHeader title="Running n8n locally" />
          <div className="space-y-2 p-5 text-sm text-slate-700">
            <p>1. Start n8n (for example <code>npx n8n</code>) and open the editor at the link above.</p>
            <p>2. Import the three files from <code>n8n/</code>, create the <em>TrustLayer Automation Key</em> header credential, and set <code>baseUrl</code> in each Config node.</p>
            <p>3. Execute a workflow once. Its run report appears in the table above.</p>
            <Notice tone="info">n8n Cloud cannot reach a backend on localhost. Use a local n8n, or tunnel the backend. Full steps: docs/N8N.md.</Notice>
          </div>
        </Panel>
      </div>
    </>
  )
}
