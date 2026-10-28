import { useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { ScanLine, X } from 'lucide-react'
import { api } from '../lib/api'
import { useApi } from '../lib/useApi'
import { AUDITORS } from '../lib/router'
import { Badge, Button, Empty, ErrorState, Loading, Notice, PageHeader, Panel, PanelHeader, Select, Table, Td, TextInput, Th, fmtTime, qs, strategyTone } from '../components/ui'

const CATEGORIES = ['DIRECT_IDENTIFIER', 'GOVERNMENT_ID', 'ACCOUNT_IDENTIFIER', 'CONTACT', 'FINANCIAL', 'DEMOGRAPHIC', 'NON_SENSITIVE']

function FieldSheet({ id, canReview, onClose, onChanged, onTrace }) {
  const { data, error, loading, reload } = useApi(id ? `/fields/${id}` : null, [id])
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState(null)

  async function review(category) {
    setSaving(true); setMsg(null)
    try {
      await api(`/fields/${id}`, { method: 'PATCH', body: { category } })
      await reload(); onChanged()
      setMsg({ tone: 'success', text: 'Classification saved and applied to policy evaluation.' })
    } catch (e) {
      setMsg({ tone: 'error', text: e.message })
    } finally { setSaving(false) }
  }

  return (
    <Dialog.Root open={Boolean(id)} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-slate-900/40" />
        <Dialog.Content className="fixed inset-y-0 right-0 z-50 w-full max-w-lg overflow-y-auto bg-white p-6 shadow-xl">
          <div className="flex items-start justify-between gap-3">
            <div>
              <Dialog.Title className="text-lg font-semibold text-slate-900">{data?.id === id ? `${data.table}.${data.column}` : 'Field detail'}</Dialog.Title>
              <Dialog.Description className="text-xs text-slate-500">Detection evidence, policy outcomes and related audit events. Sampled values are never shown.</Dialog.Description>
            </div>
            <Dialog.Close className="rounded-lg p-1 text-slate-500 hover:bg-slate-100" aria-label="Close"><X className="h-5 w-5" /></Dialog.Close>
          </div>
          {loading && !data && <Loading label="Loading field" />}
          {error && <ErrorState error={error} onRetry={reload} className="m-0 mt-4" />}
          {data && data.id === id && (
            <div className="mt-5 space-y-5 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <Badge>{data.category}</Badge><Badge tone={data.sensitivity}>{data.sensitivity}</Badge>
                <span className="text-slate-600">confidence {Math.round(data.confidence * 100)}% · {data.data_type}</span>
              </div>
              {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
              {canReview ? (
                <Select label="Classification (reviewer correction)" value={data.category} onChange={review} options={CATEGORIES} className={saving ? 'opacity-60' : ''} />
              ) : <p className="text-xs text-slate-500">Only security admins and compliance officers can correct classifications.</p>}
              {data.overridden && <p className="text-xs text-slate-600">Detected as {data.detected_category}; corrected by {data.reviewed_by}.</p>}

              <section>
                <h3 className="mb-1 font-medium text-slate-900">Detection evidence</h3>
                <ul className="list-disc space-y-1 pl-5 text-slate-700">{data.evidence.signals.map((s, i) => <li key={i}>{s}</li>)}</ul>
                <p className="mt-1 text-xs text-slate-500">{data.evidence.note}</p>
              </section>

              <section>
                <h3 className="mb-1 font-medium text-slate-900">Policy and masking decisions</h3>
                {data.policy_outcomes.length === 0 ? <p className="text-slate-500">No enabled policy applies.</p> : (
                  <Table caption="Policy outcomes for this field">
                    <thead><tr><Th>Role</Th><Th>Purpose</Th><Th>Result</Th></tr></thead>
                    <tbody>{data.policy_outcomes.map((o, i) => <tr key={i}><Td className="text-xs">{o.role}</Td><Td className="text-xs">{o.purpose}</Td><Td><Badge tone={strategyTone(o.strategy)}>{o.strategy}</Badge></Td></tr>)}</tbody>
                  </Table>
                )}
              </section>

              {data.scan && (
                <section>
                  <h3 className="mb-1 font-medium text-slate-900">Last scan</h3>
                  <p className="flex flex-wrap items-center gap-2"><Badge tone={data.scan.status}>{data.scan.status}</Badge>{fmtTime(data.scan.finished_at)} by {data.scan.triggered_by}
                    {data.scan.audit_request_id && <Button variant="ghost" size="sm" onClick={() => onTrace(data.scan.audit_request_id)}>View audit event</Button>}</p>
                </section>
              )}

              {AUDITORS.length > 0 && data.related_audit_events && (
                <section>
                  <h3 className="mb-1 font-medium text-slate-900">Related audit events</h3>
                  {data.related_audit_events.length === 0 ? <p className="text-slate-500">No requests have touched this field yet (or your role cannot view audit events).</p> : (
                    <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
                      {data.related_audit_events.map((e) => (
                        <li key={e.request_id}><button onClick={() => onTrace(e.request_id)} className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-slate-50"><Badge tone={e.decision}>{e.decision}</Badge><span className="text-xs">{e.actor} · {e.purpose}</span><span className="ml-auto text-xs text-slate-500">{fmtTime(e.ts)}</span></button></li>
                      ))}
                    </ul>
                  )}
                </section>
              )}
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

export default function Discovery({ me, version, bump, onTrace }) {
  const sources = useApi('/sources', [version])
  const scans = useApi('/scans?limit=8', [version])
  const [f, setF] = useState({ sensitivity: '', category: '', source: '', q: '' })
  const fields = useApi(`/fields${qs(f)}`, [version])
  const [scanState, setScanState] = useState({ running: false, result: null })
  const [open, setOpen] = useState(null)
  const canScan = me.role === 'security_admin'
  const canReview = AUDITORS.includes(me.role)
  const set = (k) => (v) => setF((x) => ({ ...x, [k]: v }))

  async function scan(source) {
    setScanState({ running: true, result: null })
    try {
      const s = await api('/scans', { method: 'POST', body: { source } })
      setScanState({ running: false, result: s.status === 'COMPLETED' ? { tone: 'success', text: `Scan #${s.id} completed: ${s.sensitive_found} of ${s.fields_scanned} fields are sensitive (${s.presidio_used ? 'Presidio + rules' : 'rules only'}).`, id: s.audit_request_id } : { tone: 'error', text: `Scan #${s.id} failed: ${s.error || 'unknown error'}` } })
    } catch (e) {
      setScanState({ running: false, result: { tone: 'error', text: e.message } })
    } finally { bump() }
  }

  return (
    <>
      <PageHeader title="Data discovery" description="Scan registered data sources, review detected sensitive fields, and see how policy treats each one. Scans run synchronously: the request waits for the backend and reports only what it returns." />
      <div className="space-y-5">
        <Panel>
          <PanelHeader title="Data sources" subtitle="Only allow-listed synthetic sources can be scanned." />
          {sources.loading && !sources.data && <Loading />}
          {sources.error && <ErrorState error={sources.error} onRetry={sources.reload} />}
          {sources.data?.map((s) => (
            <div key={s.id} className="flex flex-wrap items-center gap-4 px-5 py-4">
              <div className="min-w-0 flex-1">
                <p className="font-medium text-slate-900">{s.name}</p>
                <p className="text-xs text-slate-500">table <code>{s.table}</code> · {s.records} records · {s.columns} columns</p>
                <p className="mt-1 text-xs text-slate-600">{s.last_scan ? <>Last scan <Badge tone={s.last_scan.status}>{s.last_scan.status}</Badge> {fmtTime(s.last_scan.finished_at)}</> : 'Never scanned'}</p>
              </div>
              {canScan ? <Button onClick={() => scan(s.id)} loading={scanState.running}><ScanLine className="h-4 w-4" aria-hidden />{scanState.running ? 'Scanning (synchronous)…' : 'Scan now'}</Button> : <p className="text-xs text-slate-500">Scanning is limited to security admins.</p>}
            </div>
          ))}
          {scanState.result && (
            <div className="px-5 pb-4"><Notice tone={scanState.result.tone}>{scanState.result.text} {scanState.result.id && <button className="underline" onClick={() => onTrace(scanState.result.id)}>View audit event</button>}</Notice></div>
          )}
        </Panel>

        <Panel>
          <PanelHeader title="Discovered fields" subtitle="Select a row for evidence, policy outcomes and audit history." />
          <div className="flex flex-wrap items-end gap-3 border-b border-slate-100 px-5 py-3">
            <TextInput label="Search field" value={f.q} onChange={(e) => set('q')(e.target.value)} placeholder="e.g. income" className="w-44" />
            <Select label="Sensitivity" value={f.sensitivity} onChange={set('sensitivity')} options={[['', 'All'], 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW']} />
            <Select label="Classification" value={f.category} onChange={set('category')} options={[['', 'All'], ...CATEGORIES]} />
            <Select label="Source" value={f.source} onChange={set('source')} options={[['', 'All'], ...(sources.data || []).map((s) => s.id)]} />
          </div>
          {fields.loading && !fields.data && <Loading />}
          {fields.error && <ErrorState error={fields.error} onRetry={fields.reload} />}
          {fields.data?.length === 0 && <Empty title={Object.values(f).some(Boolean) ? 'No fields match these filters' : 'No fields discovered yet'} hint={Object.values(f).some(Boolean) ? 'Clear a filter to see more.' : 'A security admin needs to run a scan.'} />}
          {fields.data?.length > 0 && (
            <Table caption="Discovered fields">
              <thead><tr><Th>Field</Th><Th>Classification</Th><Th>Sensitivity</Th><Th>Confidence</Th><Th>Type</Th></tr></thead>
              <tbody>
                {fields.data.map((x) => (
                  <tr key={x.id} className="hover:bg-slate-50">
                    <Td><button className="font-mono text-xs font-medium text-navy-700 underline-offset-2 hover:underline" onClick={() => setOpen(x.id)}>{x.table}.{x.column}</button></Td>
                    <Td><Badge>{x.category}</Badge>{x.overridden && <span className="ml-1 text-xs text-slate-500">reviewed</span>}</Td>
                    <Td><Badge tone={x.sensitivity}>{x.sensitivity}</Badge></Td>
                    <Td className="tabular-nums">{Math.round(x.confidence * 100)}%</Td>
                    <Td className="text-xs text-slate-600">{x.data_type}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Panel>

        <Panel>
          <PanelHeader title="Scan history" />
          {scans.error && <ErrorState error={scans.error} onRetry={scans.reload} />}
          {scans.data?.length === 0 && <Empty title="No scans recorded" />}
          {scans.data?.length > 0 && (
            <Table caption="Scan history">
              <thead><tr><Th>#</Th><Th>Status</Th><Th>Source</Th><Th>Started</Th><Th>Result</Th><Th>Detector</Th><Th>By</Th><Th>Audit</Th></tr></thead>
              <tbody>{scans.data.map((s) => (
                <tr key={s.id}><Td>{s.id}</Td><Td><Badge tone={s.status}>{s.status}</Badge>{s.error && <span className="block text-xs text-red-700">{s.error}</span>}</Td><Td className="text-xs">{s.source}</Td><Td className="text-xs">{fmtTime(s.started_at)}</Td>
                  <Td>{s.sensitive_found}/{s.fields_scanned}</Td><Td className="text-xs">{s.presidio_used ? 'Presidio + rules' : 'rules only'}</Td><Td className="text-xs">{s.triggered_by}</Td>
                  <Td>{s.audit_request_id ? <Button variant="ghost" size="sm" onClick={() => onTrace(s.audit_request_id)}>Event</Button> : <span className="text-xs text-slate-400">—</span>}</Td></tr>))}</tbody>
            </Table>
          )}
        </Panel>
      </div>
      <FieldSheet id={open} canReview={canReview} onClose={() => setOpen(null)} onChanged={bump} onTrace={onTrace} />
    </>
  )
}
