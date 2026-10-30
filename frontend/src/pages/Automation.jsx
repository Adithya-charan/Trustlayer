import { useState } from 'react'
import { motion } from 'framer-motion'
import { ExternalLink, FileSearch, ScrollText, ShieldAlert } from 'lucide-react'
import { useApi } from '../lib/useApi'
import { workflowState } from '../lib/workflows'
import { StatusIndicator } from '../components/brand'
import { Badge, Empty, ErrorState, Loading, Notice, PageHeader, Panel, PanelHeader, Table, Td, Th, cn, fmtTime } from '../components/ui'

const ICON = { 'scheduled-scan': FileSearch, 'security-alerts': ShieldAlert, 'summary-report': ScrollText }
const BAR = { ok: 'from-emerald-500 to-teal-400', bad: 'from-rose-500 to-orange-400', warn: 'from-amber-500 to-amber-300', idle: 'from-slate-300 to-slate-200' }

export default function Automation({ version }) {
  const wf = useApi('/automation/workflows', [version])
  const reports = useApi('/reports?limit=5', [version])
  const [open, setOpen] = useState(null)
  const selected = wf.data?.workflows.find((w) => w.key === open)

  return (
    <>
      <PageHeader title="Automation" description="n8n orchestrates scheduled scans, security alerts and summary reports. It is not a security boundary: every call it makes is authenticated and authorized by this backend."
        actions={wf.data && <a href={wf.data.editor_url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 text-sm font-medium transition hover:bg-slate-50 active:scale-[0.98]">Open n8n editor <ExternalLink className="h-4 w-4" aria-hidden /></a>} />
      <div className="space-y-6">
        {wf.loading && !wf.data && <Panel><Loading /></Panel>}
        {wf.error && <Panel><ErrorState error={wf.error} onRetry={wf.reload} /></Panel>}
        {wf.data && (
          <>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {wf.data.workflows.map((w, i) => {
                const s = workflowState(w)
                const Icon = ICON[w.key] || FileSearch
                return (
                  <motion.article key={w.key} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06, duration: 0.3 }} whileHover={{ y: -2 }}
                    className="relative overflow-hidden rounded-2xl border border-slate-200/80 bg-white p-5 shadow-card transition-shadow hover:shadow-lift">
                    <span aria-hidden className={cn('absolute inset-x-0 top-0 h-1 bg-gradient-to-r', BAR[s.tone])} />
                    <div className="flex items-start justify-between gap-3">
                      <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-navy-100 text-navy-700"><Icon className="h-5 w-5" aria-hidden /></span>
                      <StatusIndicator tone={s.tone} label={s.label} />
                    </div>
                    <h2 className="mt-3 text-base font-semibold text-body">{w.name}</h2>
                    <p className="text-xs text-muted">{w.schedule} · <span className="font-mono">{w.file}</span></p>
                    <p className="mt-3 text-xs text-slate-600">{s.hint}</p>
                    <dl className="mt-4 grid grid-cols-2 gap-2 text-center">
                      {[['Succeeded', w.success_count], ['Failed', w.failure_count]].map(([k, v]) => (
                        <div key={k} className="rounded-xl bg-slate-50 px-2 py-2"><dt className="text-[10px] uppercase tracking-wider text-muted">{k}</dt><dd className="mt-0.5 text-sm font-semibold tabular-nums text-body">{v}</dd></div>
                      ))}
                    </dl>
                    <p className="mt-3 text-xs text-muted">Last run: <span className="font-medium text-body">{w.last_run_at ? fmtTime(w.last_run_at) : 'none reported'}</span></p>
                    <button className="mt-4 text-xs font-semibold text-navy-700 underline-offset-2 hover:underline" aria-expanded={open === w.key} onClick={() => setOpen(open === w.key ? null : w.key)}>{open === w.key ? 'Hide' : 'Show'} run history</button>
                  </motion.article>
                )
              })}
            </div>

            {selected && (
              <Panel>
                <PanelHeader title={`${selected.name}: run history`} subtitle="Failure details are scrubbed and never include secrets" />
                {selected.recent_runs.length === 0 ? <Empty title="No runs reported for this workflow" hint="Execute it in n8n. Nothing is shown until a run report arrives." /> : (
                  <Table caption="Recent runs">
                    <thead><tr><Th>Status</Th><Th>Time</Th><Th>Attempt</Th><Th>Detail</Th></tr></thead>
                    <tbody>{selected.recent_runs.map((r) => <tr key={r.id}><Td><Badge tone={r.status}>{r.status}</Badge></Td><Td className="text-xs">{fmtTime(r.ts)}</Td><Td>{r.attempt}</Td><Td className="text-xs text-slate-600">{r.detail || '—'}</Td></tr>)}</tbody>
                  </Table>
                )}
              </Panel>
            )}

            <Panel>
              <PanelHeader title="How to read these states" />
              <dl className="grid gap-3 p-5 text-xs sm:grid-cols-2 lg:grid-cols-4">
                {[['ok', 'Last run succeeded', 'Latest report succeeded and is recent.'], ['bad', 'Last run failed', 'Latest report is a failure.'], ['warn', 'Unknown', 'Last success is much older than the schedule implies.'], ['idle', 'No run reported', 'Not configured in n8n, or never ran. A workflow file alone does not mean it is active.']].map(([t, l, h]) => (
                  <div key={l}><dt><StatusIndicator tone={t} label={l} /></dt><dd className="mt-1 text-muted">{h}</dd></div>
                ))}
              </dl>
              <p className="border-t border-slate-100 px-5 py-3 text-xs text-muted">{wf.data.source} A &ldquo;running&rdquo; state is not shown because workflows report when they finish.</p>
            </Panel>
          </>
        )}

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
            <p>2. Import the three files from <code>n8n/</code>, create the <em>TrustLayer Automation Key</em> header credential, and check <code>baseUrl</code> (<code>http://127.0.0.1:8000</code>) in each Config node.</p>
            <p>3. Execute a workflow once. Its run report appears above.</p>
            <Notice tone="info">Alerts are recorded in TrustLayer only. No email, SMS or chat message is sent, so a recorded alert is not proof of delivery. n8n Cloud cannot reach a backend on localhost. Full steps: docs/N8N.md.</Notice>
          </div>
        </Panel>
      </div>
    </>
  )
}
