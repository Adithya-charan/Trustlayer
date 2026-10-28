import { useState } from 'react'
import { Play, Search } from 'lucide-react'
import { api } from '../lib/api'
import { useApi } from '../lib/useApi'
import { Badge, Button, Empty, ErrorState, Loading, Notice, PageHeader, Panel, PanelHeader, Select, Table, Td, TextInput, Th, strategyTone } from '../components/ui'

const EXAMPLES = [
  'SELECT id, full_name, email, pan, annual_income FROM customers LIMIT 5',
  'SELECT id, city, dependents FROM customers ORDER BY id LIMIT 10',
  'SELECT id, account_number FROM customers WHERE id = 1',
]

function ResultView({ result, onTrace }) {
  const t = result.trace
  const cols = result.rows[0] ? Object.keys(result.rows[0]) : []
  return (
    <div className="space-y-4 border-t border-slate-100 p-5">
      <div className="grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <div><p className="text-xs uppercase text-slate-500">Outcome</p><Badge tone={t.decision === 'PARTIAL' ? 'MASK' : t.decision}>{t.decision === 'PARTIAL' ? 'MASK (protected)' : t.decision}</Badge></div>
        <div><p className="text-xs uppercase text-slate-500">Applied policy</p><code className="text-xs">{t.policy}</code></div>
        <div><p className="text-xs uppercase text-slate-500">Risk score</p><span className="tabular-nums">{t.risk.score}</span> {t.risk.response ? <Badge tone="MEDIUM">{t.risk.response}</Badge> : <span className="text-slate-500">no action</span>}</div>
        <div><p className="text-xs uppercase text-slate-500">Audit event</p><Button variant="ghost" size="sm" onClick={() => onTrace(t.request_id)}><Search className="h-3.5 w-3.5" aria-hidden /> <span className="font-mono text-[11px]">{t.request_id.slice(0, 8)}…</span></Button></div>
      </div>
      <p className="text-sm text-slate-700"><span className="font-medium">Why:</span> {t.reason}</p>
      {t.risk.signals.length > 0 && <Notice tone="warn">{t.risk.signals.map((s) => `${s.rule}: ${s.detail}`).join(' · ')}</Notice>}
      <Table caption="Field handling for this request">
        <thead><tr><Th>Field</Th><Th>Classification</Th><Th>Sensitivity</Th><Th>Applied strategy</Th></tr></thead>
        <tbody>{Object.entries(t.field_plan).map(([f, p]) => <tr key={f}><Td className="font-mono text-xs">{f}</Td><Td><Badge>{p.category}</Badge></Td><Td><Badge tone={p.sensitivity}>{p.sensitivity}</Badge></Td><Td><Badge tone={strategyTone(p.strategy)}>{p.strategy}</Badge></Td></tr>)}</tbody>
      </Table>
      {result.row_count === 0 ? <Empty title="No rows matched" /> : (
        <div>
          <p className="mb-1 text-xs font-medium uppercase text-slate-500">Returned data ({result.row_count} row{result.row_count > 1 ? 's' : ''}, protected)</p>
          <Table caption="Returned rows">
            <thead><tr>{cols.map((c) => <Th key={c}>{c}</Th>)}</tr></thead>
            <tbody>{result.rows.map((r, i) => <tr key={i}>{cols.map((c) => <Td key={c} className="font-mono text-xs">{String(r[c])}</Td>)}</tr>)}</tbody>
          </Table>
        </div>
      )}
    </div>
  )
}

export default function Access({ me, bump, onTrace }) {
  const schema = useApi('/access/schema', [])
  const [mode, setMode] = useState('structured')
  const [purpose, setPurpose] = useState('')
  const [picked, setPicked] = useState(['id', 'full_name', 'pan', 'annual_income'])
  const [customer, setCustomer] = useState('')
  const [limit, setLimit] = useState('5')
  const [sql, setSql] = useState(EXAMPLES[0])
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const purposes = schema.data?.purposes || []
  const active = purpose || purposes[0] || ''
  const toggle = (f) => setPicked((p) => (p.includes(f) ? p.filter((x) => x !== f) : [...p, f]))

  async function submit(e) {
    e.preventDefault(); setBusy(true); setError(null); setResult(null)
    try {
      const body = mode === 'structured'
        ? { purpose: active, fields: picked, customer_id: customer ? Number(customer) : null, limit: Number(limit) || 5 }
        : { purpose: active, sql }
      setResult(await api(mode === 'structured' ? '/access/evaluate' : '/query', { method: 'POST', body }))
    } catch (x) { setError(x) } finally { setBusy(false); bump() }
  }

  return (
    <>
      <PageHeader title="Access console" description="Submit an access request and see the real decision. Your role always comes from your signed-in session, so it cannot be changed in the request." />
      <Panel>
        <PanelHeader title="New request" subtitle={`Requesting as ${me.username} (${me.role})`} actions={
          <div role="tablist" aria-label="Request type" className="flex rounded-lg border border-slate-200 p-0.5 text-xs">
            {[['structured', 'Structured'], ['sql', 'SQL gateway']].map(([k, l]) => <button key={k} role="tab" aria-selected={mode === k} onClick={() => setMode(k)} className={`rounded-md px-3 py-1.5 font-medium ${mode === k ? 'bg-navy-700 text-white' : 'text-slate-600'}`}>{l}</button>)}
          </div>} />
        {schema.loading && !schema.data && <Loading />}
        {schema.error && <ErrorState error={schema.error} onRetry={schema.reload} />}
        {schema.data && purposes.length === 0 && <Empty title="No purposes available for your role" hint="No enabled policy grants your role access to data." />}
        {schema.data && purposes.length > 0 && (
          <form onSubmit={submit} className="space-y-4 p-5">
            <Select label="Declared business purpose" value={active} onChange={setPurpose} options={purposes} className="max-w-xs" />
            {mode === 'structured' ? (
              <>
                <fieldset>
                  <legend className="mb-2 text-xs font-medium text-slate-600">Requested fields</legend>
                  <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
                    {schema.data.fields.map((f) => (
                      <label key={f.name} className="flex cursor-pointer items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm has-[:checked]:border-navy-600 has-[:checked]:bg-slate-50">
                        <input type="checkbox" checked={picked.includes(f.name)} onChange={() => toggle(f.name)} className="h-4 w-4 accent-navy-700" />
                        <span className="font-mono text-xs">{f.name}</span>
                        {f.sensitivity ? <Badge tone={f.sensitivity} className="ml-auto">{f.sensitivity}</Badge> : <span className="ml-auto text-[11px] text-slate-400">unclassified</span>}
                      </label>
                    ))}
                  </div>
                </fieldset>
                <div className="flex flex-wrap gap-3">
                  <TextInput label="Customer ID (optional)" type="number" min="1" value={customer} onChange={(e) => setCustomer(e.target.value)} hint="Restrict to one synthetic record" className="w-48" />
                  <TextInput label="Max rows" type="number" min="1" max="50" value={limit} onChange={(e) => setLimit(e.target.value)} className="w-28" />
                </div>
              </>
            ) : (
              <div>
                <label htmlFor="sql" className="mb-1 block text-xs font-medium text-slate-600">Query</label>
                <textarea id="sql" rows={3} value={sql} maxLength={500} onChange={(e) => setSql(e.target.value)} className="w-full rounded-lg border border-slate-300 p-3 font-mono text-xs" />
                <p className="mt-1 text-xs text-slate-500">Supported: <code>SELECT cols FROM customers [WHERE col op literal AND …] [ORDER BY col] [LIMIT ≤ 50]</code>. Everything else is rejected, never guessed.</p>
                <div className="mt-2 flex flex-wrap gap-2">{EXAMPLES.map((ex) => <button type="button" key={ex} onClick={() => setSql(ex)} className="rounded-lg bg-slate-100 px-2 py-1 text-xs text-navy-700 hover:bg-slate-200">{ex.slice(7, 42)}…</button>)}</div>
              </div>
            )}
            <Button type="submit" loading={busy} disabled={mode === 'structured' && picked.length === 0}><Play className="h-4 w-4" aria-hidden /> Evaluate request</Button>
          </form>
        )}
        {error && <div className="px-5 pb-5"><Notice tone="error">{error.message}{error.extra?.supported && <span className="block text-xs">{error.extra.supported}</span>}{error.extra?.request_id && <button className="ml-1 underline" onClick={() => onTrace(error.extra.request_id)}>Why was this refused?</button>}</Notice></div>}
        {result && <ResultView result={result} onTrace={onTrace} />}
      </Panel>
    </>
  )
}
