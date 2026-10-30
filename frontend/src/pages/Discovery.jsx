import { useEffect, useMemo, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { ScanSearch } from 'lucide-react'
import { api } from '../lib/api'
import { useApi } from '../lib/useApi'
import { useBackends } from '../lib/target'
import { ApiError } from '../lib/api'
import { Badge, Button, Empty, ErrorState, Loading, MetricStrip, Metric, Notice, PageHeader, Panel, PanelHeader, Select, Table, Td, Th, TextInput } from '../components/ui'
import UploadPanel from '../components/UploadPanel'
import { ADMINS, BackendGate, BackendPicker, RISK_TONE, TAG_TONE } from '../components/b1'

const RISK = { PII_HIGH: 'High', PAYMENT_SENSITIVE: 'High', PII_MEDIUM: 'Medium', FINANCIAL_CONFIDENTIAL: 'Medium', NON_SENSITIVE: 'Low' }
const METHOD = { column_name: 'column name', value_pattern: 'value pattern', luhn: 'Luhn checksum', free_text_scan: 'free-text scan', ml_ner: 'ML model (uncertain)', manual_review: 'manual review' }
const TAG_OPTIONS = [['', 'All classifications'], ['SENSITIVE', 'All sensitive fields'], ['PII', 'PII (high + medium)'], ['PII_HIGH', 'PII_HIGH'], ['PII_MEDIUM', 'PII_MEDIUM'], ['FINANCIAL_CONFIDENTIAL', 'FINANCIAL_CONFIDENTIAL'], ['PAYMENT_SENSITIVE', 'PAYMENT_SENSITIVE'], ['NON_SENSITIVE', 'Not sensitive']]

export default function Discovery({ me, params, version, bump }) {
  const backends = useBackends()
  const isAdmin = ADMINS.includes(me.role)
  const policy = useApi('/b1/policy')
  const kinds = policy.data?.kinds.map((k) => k.kind) || []
  const { data, error, loading, reload } = useApi(backends.ready ? `/b1/fields?target=${backends.target}` : null, [backends.target, backends.ready, version])
  const [f, setF] = useState({ tag: '', table: '', status: '', risk: '', embedded: false, q: '' })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const sp = params.toString()
  useEffect(() => { // voice commands and links open a pre-filtered view
    setF({ tag: params.get('tag') || '', table: params.get('table') || '', status: params.get('status') || '', risk: params.get('risk') || '', embedded: params.get('embedded') === '1', q: '' })
  }, [sp]) // eslint-disable-line react-hooks/exhaustive-deps

  const all = useMemo(() => data?.fields || [], [data])
  const rows = useMemo(() => all.filter((x) => (
    (!f.tag || (f.tag === 'PII' ? x.tag === 'PII_HIGH' || x.tag === 'PII_MEDIUM' : f.tag === 'SENSITIVE' ? x.tag !== 'NON_SENSITIVE' : x.tag === f.tag)) && (!f.table || x.table === f.table) && (!f.status || x.status === f.status)
    && (!f.risk || RISK[x.tag] === f.risk) && (!f.embedded || x.kind === 'FREE_TEXT_PII') && (!f.q || `${x.table}.${x.column}`.toLowerCase().includes(f.q.toLowerCase())))), [all, f])
  const tables = useMemo(() => [...new Set(all.map((x) => x.table))], [all])
  const sensitive = all.filter((x) => x.tag !== 'NON_SENSITIVE')
  const embedded = all.filter((x) => x.kind === 'FREE_TEXT_PII')
  const set = (k) => (v) => setF((s) => ({ ...s, [k]: v }))

  async function scan() {
    setBusy(true); setMsg(null)
    try {
      const r = await api('/b1/scan', { method: 'POST', body: { target: backends.target } })
      setMsg({ tone: 'success', text: `Scanned ${r.tables} tables / ${r.columns} columns: ${r.confirmed} confirmed, ${r.uncertain} uncertain, ${r.untagged} not sensitive${r.kept_overrides ? `, ${r.kept_overrides} reviewed columns kept` : ''}.` })
      reload(); bump?.()
    } catch (e) { setMsg({ tone: 'error', text: e.message }) } finally { setBusy(false) }
  }
  // Classification changes. NON_SENSITIVE releases masking for every role, so it always goes through a confirmation dialog; the server enforces the
  // same rule (409 release_confirmation_required) even if this UI were bypassed.
  const [dlg, setDlg] = useState(null) // { mode: 'release' | 'clear', x, kind, busy, error, needsRelease }
  async function review(x, kind) {
    if (kind === 'NON_SENSITIVE') { setDlg({ mode: 'release', x, kind, busy: false, error: null }); return }
    try { await api('/b1/fields', { method: 'PATCH', body: { target: backends.target, table: x.table, column: x.column, kind } }); reload(); bump?.() } catch (e) { setMsg({ tone: 'error', text: e.message }) }
  }
  async function submitDialog(confirmRelease) {
    const d = dlg
    setDlg({ ...d, busy: true, error: null })
    try {
      if (d.mode === 'release') {
        await api('/b1/fields', { method: 'PATCH', body: { target: backends.target, table: d.x.table, column: d.x.column, kind: d.kind, confirm_masking_release: true } })
        setMsg({ tone: 'success', text: `${d.x.table}.${d.x.column} set to NON_SENSITIVE. Masking is removed for every role. The decision is recorded in the Audit Center.` })
      } else {
        const out = await api('/b1/fields/clear', { method: 'POST', body: { target: backends.target, table: d.x.table, column: d.x.column, confirm_masking_release: confirmRelease } })
        setMsg({ tone: 'success', text: `Cleared the manual decision on ${d.x.table}.${d.x.column}. Detection now classifies it as ${out.restored.kind} (${out.restored.status}).${out.released ? ' Masking is removed for every role.' : ''}` })
      }
      setDlg(null); reload(); bump?.()
    } catch (e) {
      const code = e instanceof ApiError ? e.extra?.code : undefined
      if (code === 'release_confirmation_required' && d.mode === 'clear') { setDlg({ ...d, busy: false, needsRelease: true, error: e.message }); return }
      setDlg({ ...d, busy: false, error: e.message })
    }
  }
  function openClear(x) { setDlg({ mode: 'clear', x, kind: x.kind, busy: false, error: null, needsRelease: false }) }

  return (
    <>
      <PageHeader title="Data Discovery" description="Hybrid detection: schema metadata, column names, sampled values, patterns (PAN, Aadhaar, SSN, e-mail, phone), a Luhn check for card numbers, and a free-text scan for PII embedded in text. Only the result is stored, never sampled values."
        actions={isAdmin && backends.ready && <Button onClick={scan} loading={busy}><ScanSearch className="h-4 w-4" aria-hidden /> Scan database</Button>} />
      <div className="space-y-5">
        {isAdmin && <UploadPanel />}
        <BackendPicker backends={backends} />
        {!backends.ready ? <BackendGate backends={backends} /> : (
          <>
            {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
            {loading && !data ? <Panel><Loading label="Loading classifications" /></Panel> : error ? <Panel><ErrorState error={error} onRetry={reload} /></Panel> : !all.length ? (
              <Panel><Empty icon={ScanSearch} title="Nothing has been scanned yet" hint={isAdmin ? 'Scan the database to classify every column. Queries stay locked until a table is scanned.' : 'An Admin must run a scan before queries are available.'} /></Panel>
            ) : (
              <>
                <MetricStrip>
                  <Metric label="Columns scanned" value={all.length} sub={`${tables.length} tables`} />
                  <Metric label="Sensitive fields" value={sensitive.length} sub={`${all.filter((x) => x.risk === 'High' || RISK[x.tag] === 'High').length} high risk`} />
                  <Metric label="Embedded PII" value={embedded.length} sub="inside free text" />
                  <Metric label="Needs review" value={all.filter((x) => x.status === 'uncertain' && !x.reviewed).length} sub="uncertain classification" />
                </MetricStrip>

                {embedded.length > 0 && (
                  <Panel>
                    <PanelHeader title="PII hidden inside free text" subtitle="Column names alone would call these harmless. Value scanning finds identifiers embedded in the text, and masking scrubs them at query time." />
                    <ul className="divide-y divide-slate-100">
                      {embedded.map((x) => (
                        <li key={`${x.table}.${x.column}`} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm">
                          <span className="font-mono text-xs">{x.table}.{x.column}</span>
                          <span className="flex flex-wrap gap-1">{x.methods.map((m) => <Badge key={m} tone="info">{METHOD[m] || m}</Badge>)}<Badge tone="HIGH">PII_HIGH</Badge></span>
                        </li>
                      ))}
                    </ul>
                  </Panel>
                )}

                <Panel>
                  <PanelHeader title="Detected fields" subtitle="Classification, confidence and how each field was detected." />
                  <div className="flex flex-wrap items-end gap-3 border-b border-slate-100 p-4">
                    <Select label="Classification" value={f.tag} onChange={set('tag')} options={TAG_OPTIONS} />
                    <Select label="Risk" value={f.risk} onChange={set('risk')} options={[['', 'Any risk'], 'High', 'Medium', 'Low']} />
                    <Select label="Table" value={f.table} onChange={set('table')} options={[['', 'All tables'], ...tables]} />
                    <Select label="Status" value={f.status} onChange={set('status')} options={[['', 'All'], ['confirmed', 'Confirmed'], ['uncertain', 'Uncertain (review)'], ['none', 'Not sensitive']]} />
                    <TextInput label="Find a column" value={f.q} onChange={(e) => set('q')(e.target.value)} placeholder="e.g. pan" className="w-40" />
                    {(f.tag || f.table || f.status || f.risk || f.embedded || f.q) && <Button size="sm" variant="ghost" onClick={() => setF({ tag: '', table: '', status: '', risk: '', embedded: false, q: '' })}>Clear filters</Button>}
                    <span className="ml-auto text-xs text-slate-500">{rows.length} of {all.length} fields</span>
                  </div>
                  {!rows.length ? <Empty title="No fields match these filters" /> : (
                    <Table caption="Detected fields">
                      <thead><tr><Th>Column</Th><Th>Type</Th><Th>Classification</Th><Th>Kind</Th><Th>Risk</Th><Th>Confidence</Th><Th>Detected by</Th><Th>Status</Th>{isAdmin && <Th>Review</Th>}</tr></thead>
                      <tbody>{rows.map((x) => (
                        <tr key={`${x.table}.${x.column}`}>
                          <Td><span className="font-mono text-xs">{x.table}.{x.column}</span></Td>
                          <Td className="text-xs text-slate-600">{x.data_type}</Td>
                          <Td><Badge tone={TAG_TONE[x.tag]}>{x.tag}</Badge></Td>
                          <Td className="text-xs">{x.kind}</Td>
                          <Td><Badge tone={RISK_TONE[RISK[x.tag]]}>{RISK[x.tag]}</Badge></Td>
                          <Td><span className="tabular-nums text-xs">{Math.round(x.confidence * 100)}%</span></Td>
                          <Td><span className="flex flex-wrap gap-1" title={x.rationale}>{x.methods.length ? x.methods.map((m) => <Badge key={m} tone="neutral">{METHOD[m] || m}</Badge>) : <span className="text-xs text-slate-400">-</span>}</span></Td>
                          <Td><Badge tone={x.status === 'confirmed' ? 'SUCCESS' : x.status === 'uncertain' ? 'WARNING' : 'neutral'}>{x.reviewed ? 'reviewed' : x.status}</Badge></Td>
                          {isAdmin && <Td><span className="flex flex-wrap items-center gap-1"><select aria-label={`Classification of ${x.column}`} value={x.kind} onChange={(e) => review(x, e.target.value)} className="min-h-8 rounded border border-slate-300 bg-white px-1 text-xs">
                            {kinds.map((k) => <option key={k} value={k}>{k}</option>)}</select>
                            {x.reviewed && <Button size="sm" variant="outline" onClick={() => openClear(x)} aria-label={`Clear the manual decision on ${x.column}`}>Clear decision</Button>}</span></Td>}
                        </tr>
                      ))}</tbody>
                    </Table>
                  )}
                </Panel>
                <p className="text-xs text-slate-500">Detection is rule-, pattern- and checksum-based and reviewed by an Admin; it is not a trained model, and uncertain results are flagged rather than guessed.</p>
              </>
            )}
          </>
        )}
      </div>
          <Dialog.Root open={Boolean(dlg)} onOpenChange={(open) => { if (!open && !dlg?.busy) setDlg(null) }}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-slate-900/40" />
          <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[min(92vw,28rem)] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-slate-200 bg-white p-5 shadow-xl">
            {dlg && dlg.mode === 'release' && (<>
              <Dialog.Title className="text-base font-semibold text-slate-900">Remove masking for {dlg.x.table}.{dlg.x.column}?</Dialog.Title>
              <Dialog.Description className="mt-2 text-sm text-slate-700">Setting this column to NON_SENSITIVE means every role, including Support and Analyst, will see its real values. This cannot be undone from here; a reviewer must set the classification again. The decision, your name and the time are recorded in the Audit Center without any values.</Dialog.Description>
            </>)}
            {dlg && dlg.mode === 'clear' && (<>
              <Dialog.Title className="text-base font-semibold text-slate-900">Clear the manual decision on {dlg.x.table}.{dlg.x.column}?</Dialog.Title>
              <Dialog.Description className="mt-2 text-sm text-slate-700">Detection will classify this column again from its values, as a scan does. The decision you replace is recorded in the Audit Center. Clearing does not make the column safe: if detection finds nothing sensitive, masking is removed for every role.</Dialog.Description>
              {dlg.needsRelease && <Notice tone="warn" className="mt-3">Detection would remove masking for every role. Confirm the release to continue.</Notice>}
            </>)}
            {dlg?.error && <Notice tone="error" className="mt-3">{dlg.error}</Notice>}
            <div className="mt-5 flex flex-wrap justify-end gap-2">
              <Dialog.Close asChild><Button variant="outline" disabled={dlg?.busy}>Cancel</Button></Dialog.Close>
              {dlg?.mode === 'release' && <Button variant="danger" loading={dlg.busy} onClick={() => submitDialog(true)}>Remove masking for every role</Button>}
              {dlg?.mode === 'clear' && !dlg.needsRelease && <Button variant="outline" loading={dlg.busy} onClick={() => submitDialog(false)}>Clear decision</Button>}
              {dlg?.mode === 'clear' && dlg.needsRelease && <Button variant="danger" loading={dlg.busy} onClick={() => submitDialog(true)}>Confirm masking release</Button>}
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  )
}
