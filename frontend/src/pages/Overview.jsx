import { Activity, ArrowRight, Ban, ClipboardList, EyeOff, FileEdit, Database, FileSearch, Lock, ScanSearch, ShieldCheck, SlidersHorizontal, Table2, Users } from 'lucide-react'
import { useApi } from '../lib/useApi'
import { useBackends } from '../lib/target'
import { Badge, Button, Empty, ErrorState, Loading, Notice, PageHeader, Panel, PanelHeader, cn, fmtTime } from '../components/ui'
import { MetricCard } from '../components/data'
import { ActivityList, BackendFacts, BackendPicker, ADMINS, TAG_TONE } from '../components/b1'

const FLOW = [
  ['Database', Database], ['Discovery', FileSearch], ['PII detection', ScanSearch], ['Classification', Table2],
  ['Role + policy check', SlidersHorizontal], ['Query-time masking', Lock], ['Result', ShieldCheck], ['Audit', ClipboardList],
]

export default function Overview({ me, go, version }) {
  const backends = useBackends()
  const { data, error, loading, reload } = useApi(backends.ready ? `/b1/overview?target=${backends.target}` : null, [backends.target, backends.ready, version])
  const isAdmin = ADMINS.includes(me.role)
  const recent = useApi(backends.ready ? (isAdmin ? '/b1/activity?limit=6' : '/b1/me/activity?limit=6') : null, [backends.target, backends.ready, version])
  const d = data
  const tags = d ? Object.entries(d.discovery.by_tag) : []
  const maxTag = Math.max(1, ...tags.map(([, n]) => n))

  return (
    <>
      <PageHeader title="Overview" description="TrustLayer discovers sensitive financial data, classifies it, applies identity-aware policies at query time, masks or redacts the result without modifying the underlying database, and records every important access decision." />
      <div className="space-y-5">
        <Panel>
          <PanelHeader title="Data protection flow" subtitle="Every request follows this path on the server. The browser, voice and the AI assistant never decide access." />
          <ol className="flex flex-wrap items-center gap-2 p-4" aria-label="Protection flow">
            {FLOW.map(([label, Icon], i) => (
              <li key={label} className="flex items-center gap-2">
                <span className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-800"><Icon className="h-4 w-4 text-navy-600" aria-hidden />{label}</span>
                {i < FLOW.length - 1 && <ArrowRight className="h-4 w-4 text-slate-400" aria-hidden />}
              </li>
            ))}
          </ol>
        </Panel>

        <Panel>
          <PanelHeader title="Database backends" subtitle="Live health checks from the server. Credentials never reach the browser." />
          <div className="space-y-3 p-4">
            <BackendPicker backends={backends} />
            {backends.current && <BackendFacts t={backends.current} />}
            {!backends.loading && !backends.ready && <Notice tone="error">{backends.current?.error || 'The selected backend is not connected.'} Nothing below is shown until a backend is reachable.</Notice>}
          </div>
        </Panel>

        {backends.ready && (loading && !d ? <Panel><Loading label="Loading live metrics" /></Panel> : error ? <Panel><ErrorState error={error} onRetry={reload} /></Panel> : d && (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
              <MetricCard label="Tables" value={d.dataset.tables} sub="in the connected schema" icon={Table2} accent="blue" />
              <MetricCard label="Records" value={d.dataset.records.toLocaleString('en-US')} sub="counted live" icon={Database} accent="cyan" delay={0.03} />
              <MetricCard label="Sensitive fields" value={d.discovery.scanned ? d.discovery.sensitive_fields : '-'} sub={d.discovery.scanned ? `of ${d.discovery.columns} columns` : 'not scanned yet'} icon={FileSearch} accent="violet" delay={0.06} />
              <MetricCard label="Protected fields" value={d.discovery.scanned ? d.protection.protected_fields : '-'} sub="masked for Support or Analyst" icon={Lock} accent="amber" delay={0.09} />
              <MetricCard label="Policy rules" value={d.protection.active_rules} sub={`${d.protection.custom_policies} edited by an Admin`} icon={SlidersHorizontal} accent="blue" delay={0.12} />
              <MetricCard label="Audit events" value={d.audit.events} sub={`${d.audit.masked} masked · ${d.audit.denied} denied queries`} icon={ClipboardList} accent="rose" delay={0.15} />
            </div>

            {isAdmin && (
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="Security activity, last 24 hours">
                <MetricCard label="Access events" value={d.audit.today.access_events} sub="queries in the last 24 h" icon={Activity} accent="blue" />
                <MetricCard label="Masked requests" value={d.audit.today.masked_requests} sub="returned with masking" icon={EyeOff} accent="amber" delay={0.03} />
                <MetricCard label="Blocked attempts" value={d.audit.today.blocked_attempts} sub="denied or withheld" icon={Ban} accent="rose" delay={0.06} />
                <MetricCard label="Policy changes" value={d.audit.today.policy_changes} sub="by an Admin, last 24 h" icon={FileEdit} accent="violet" delay={0.09} />
              </div>
            )}
            <Panel>
              <PanelHeader title={isAdmin ? 'Recent security activity' : 'Your recent activity'} subtitle="Read from the audit trail: who did what, which policy decided and why."
                actions={isAdmin && <Button size="sm" variant="outline" onClick={() => go('audit?view=activity')}>Open activity</Button>} />
              {recent.loading && !recent.data ? <Loading label="Loading activity" rows={2} /> : recent.error ? <ErrorState error={recent.error} onRetry={recent.reload} /> : <ActivityList events={recent.data?.events} />}
            </Panel>

            {!d.discovery.scanned ? (
              <Panel><Empty icon={ScanSearch} title="This database has not been scanned yet" hint={isAdmin ? 'Run discovery to classify every column. Queries stay locked until a table is scanned.' : 'An Admin must run discovery before queries are available.'}
                action={isAdmin && <Button size="sm" onClick={() => go('discovery')}>Open Data Discovery</Button>} /></Panel>
            ) : (
              <div className="grid gap-5 lg:grid-cols-2">
                <Panel>
                  <PanelHeader title="Sensitive fields by classification" subtitle={d.discovery.last_scan ? `Last scan ${fmtTime(d.discovery.last_scan)}` : undefined}
                    actions={<Button size="sm" variant="outline" onClick={() => go('discovery')}>Open discovery</Button>} />
                  <ul className="space-y-3 p-4">
                    {tags.map(([tag, n]) => (
                      <li key={tag}>
                        <div className="mb-1 flex items-center justify-between text-xs"><Badge tone={TAG_TONE[tag]}>{tag}</Badge><span className="tabular-nums text-slate-600">{n} fields</span></div>
                        <div className="h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-navy-600" style={{ width: `${(n / maxTag) * 100}%` }} /></div>
                      </li>
                    ))}
                    {d.discovery.embedded_pii_fields > 0 && <li className="pt-1 text-xs text-slate-600"><Badge tone="WARNING">{d.discovery.embedded_pii_fields} free-text field(s)</Badge> carry PII embedded inside text (for example support ticket text).</li>}
                    {d.discovery.needs_review > 0 && <li className="text-xs text-amber-800">{d.discovery.needs_review} uncertain classification(s) await review.</li>}
                  </ul>
                </Panel>
                <Panel>
                  <PanelHeader title="Tables" subtitle="Row counts from the database; open one in the Data Explorer." />
                  <ul className="divide-y divide-slate-100">
                    {d.dataset.per_table.map((t) => (
                      <li key={t.name}>
                        <button type="button" onClick={() => go(`explorer?table=${t.name}`)} className="flex min-h-11 w-full items-center justify-between px-4 text-left text-sm hover:bg-slate-50">
                          <span className="font-mono text-xs text-slate-900">{t.name}</span><span className="tabular-nums text-xs text-slate-600">{t.rows.toLocaleString('en-US')} rows</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </Panel>
              </div>
            )}

            <Panel>
              <PanelHeader title="See it work" subtitle="Same database. Same query. Different identity. Different exposure." />
              <div className="flex flex-wrap items-center gap-3 p-4">
                <Button size="sm" onClick={() => go('policies?demo=1')} disabled={!d.discovery.scanned}><ShieldCheck className="h-4 w-4" aria-hidden /> Run the masking demo</Button>
                {isAdmin && <Button size="sm" variant="outline" onClick={() => go('access')}><Users className="h-4 w-4" aria-hidden /> Users &amp; access</Button>}
                {isAdmin && <Button size="sm" variant="outline" onClick={() => go('audit')}><ClipboardList className="h-4 w-4" aria-hidden /> Audit Center</Button>}
                <span className={cn('text-xs text-slate-500')}>Last 24 h: {Object.entries(d.audit.last_24h).map(([k, v]) => `${v} ${k.toLowerCase()}`).join(' · ') || 'no queries yet'}</span>
              </div>
            </Panel>
          </>
        ))}
      </div>
    </>
  )
}
