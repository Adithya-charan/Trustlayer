import { useMemo, useState } from 'react'
import { Calculator, Search } from 'lucide-react'
import { api } from '../lib/api'
import { useApi } from '../lib/useApi'
import { Badge, Button, ErrorState, Loading, Notice, PageHeader, Panel, PanelHeader, Select, Table, Td, TextInput, Th, inr } from '../components/ui'

const DISCLAIMER = 'Illustrative estimate only. Not an approved insurance formula, financial advice, or an insurance quote.'
const LABELS = { income_replacement: 'Income replacement (income × years)', liabilities: 'Outstanding liabilities', education_goal: 'Education / future goals', dependents_buffer: 'Dependants buffer', less_existing_cover_and_assets: 'Less existing cover and offset assets' }
const FIELDS = [
  ['annual_income', 'Annual income (₹)', 0, 1e10], ['total_liabilities', 'Outstanding liabilities (₹)', 0, 1e11], ['dependents', 'Dependents', 0, 20, 1],
  ['age', 'Age', 18, 80, 1], ['existing_cover', 'Existing insurance cover (₹)', 0, 1e11], ['liquid_assets', 'Liquid assets (₹)', 0, 1e11], ['education_goal', 'Education / future goals (₹)', 0, 1e11],
]
const ASSUMPTION_LABEL = { replacement_years: 'Income replacement years', per_dependent_buffer: 'Buffer per dependent (₹)', asset_offset_ratio: 'Share of liquid assets used to offset (0–1)' }
const BLANK = { annual_income: '', total_liabilities: '', dependents: '', age: '', existing_cover: '', liquid_assets: '', education_goal: '' }

export default function Insurance({ bump, onTrace }) {
  const cfg = useApi('/insurance/config', [])
  const customers = useApi('/insurance/customers', [])
  const [mode, setMode] = useState('record')
  const [cid, setCid] = useState('')
  const [inputs, setInputs] = useState(BLANK)
  const [ass, setAss] = useState({})
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState(null)
  const [err, setErr] = useState(null)

  const bounds = cfg.data?.assumptions
  const assVal = (k) => ass[k] ?? bounds?.[k]?.default ?? ''
  const assErrors = useMemo(() => {
    const e = {}
    if (bounds) Object.entries(bounds).forEach(([k, b]) => {
      const v = Number(assVal(k))
      if (assVal(k) === '' || Number.isNaN(v) || v < b.min || v > b.max) e[k] = `Enter a value between ${b.min} and ${b.max}`
    })
    return e
  }, [ass, bounds]) // eslint-disable-line react-hooks/exhaustive-deps
  const inputErrors = useMemo(() => {
    const e = {}
    if (mode !== 'whatif') return e
    FIELDS.forEach(([k, , min, max]) => {
      const v = inputs[k]
      if (v === '') e[k] = 'Required'
      else if (Number.isNaN(Number(v)) || Number(v) < min || Number(v) > max) e[k] = `Must be between ${min} and ${max.toExponential ? inr(max) : max}`
    })
    return e
  }, [inputs, mode])
  const invalid = Object.keys(assErrors).length > 0 || Object.keys(inputErrors).length > 0 || (mode === 'record' && !cid)

  async function run(e) {
    e.preventDefault(); setBusy(true); setErr(null); setRes(null)
    const assumptions = Object.fromEntries(Object.keys(bounds).map((k) => [k, Number(assVal(k))]))
    try {
      setRes(mode === 'record'
        ? await api('/insurance/assess', { method: 'POST', body: { customer_id: Number(cid), assumptions } })
        : await api('/insurance/estimate', { method: 'POST', body: { inputs: Object.fromEntries(Object.entries(inputs).map(([k, v]) => [k, Number(v)])), assumptions } }))
    } catch (x) { setErr(x) } finally { setBusy(false); bump() }
  }

  const r = res?.result
  return (
    <>
      <PageHeader title="Insurance needs assessment" description="A needs-based, configurable calculation that runs on a minimal set of inputs. The formula and defaults are documented in docs/DESIGN.md." />
      <Notice tone="warn" className="mb-5"><strong>{DISCLAIMER}</strong></Notice>
      {(cfg.loading || customers.loading) && !cfg.data && <Panel><Loading /></Panel>}
      {cfg.error && <Panel><ErrorState error={cfg.error} onRetry={cfg.reload} /></Panel>}
      {cfg.data && (
        <form onSubmit={run} className="grid gap-5 lg:grid-cols-5">
          <div className="space-y-5 lg:col-span-3">
            <Panel>
              <PanelHeader title="1 · Inputs" subtitle="Choose where the seven inputs come from." actions={
                <div role="tablist" aria-label="Input source" className="flex rounded-lg border border-slate-200 p-0.5 text-xs">
                  {[['record', 'Synthetic customer'], ['whatif', 'What-if values']].map(([k, l]) => <button type="button" key={k} role="tab" aria-selected={mode === k} onClick={() => { setMode(k); setRes(null) }} className={`rounded-md px-3 py-1.5 font-medium ${mode === k ? 'bg-navy-700 text-white' : 'text-slate-600'}`}>{l}</button>)}
                </div>} />
              <div className="p-5">
                {mode === 'record' ? (
                  <div className="space-y-3">
                    {customers.error && <ErrorState error={customers.error} onRetry={customers.reload} className="m-0" />}
                    <Select label="Synthetic customer" value={cid} onChange={setCid} options={[['', 'Select a record…'], ...(customers.data || []).map((c) => [String(c.id), c.label])]} className="max-w-xs" />
                    <p className="text-xs text-slate-600">The backend loads only the seven needed columns for this record (age is derived from date of birth). Name, PAN, account number, email, phone, city and ID are never read. Exact values are not shown back to you.</p>
                  </div>
                ) : (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {FIELDS.map(([k, label, min, max, step]) => <TextInput key={k} label={label} type="number" inputMode="decimal" min={min} step={step || 'any'} value={inputs[k]} onChange={(e) => setInputs({ ...inputs, [k]: e.target.value })} error={inputErrors[k]} />)}
                    <p className="text-xs text-slate-500 sm:col-span-2">Values you type here are sent to the calculator only; no stored customer is read. The audit trail records the field names, not the numbers.</p>
                  </div>
                )}
              </div>
            </Panel>
            <Panel>
              <PanelHeader title="2 · Assumptions" subtitle="Configurable, bounded, and shown with every result." />
              <div className="grid gap-3 p-5 sm:grid-cols-3">
                {Object.entries(bounds).map(([k, b]) => <TextInput key={k} label={ASSUMPTION_LABEL[k] || k} type="number" step="any" min={b.min} max={b.max} value={assVal(k)} onChange={(e) => setAss({ ...ass, [k]: e.target.value })} error={assErrors[k]} hint={`Default ${b.default}`} />)}
              </div>
            </Panel>
            <Button type="submit" loading={busy} disabled={invalid}><Calculator className="h-4 w-4" aria-hidden /> Calculate illustrative estimate</Button>
            {err && <Notice tone="error">{err.message}{err.extra?.request_id && <button type="button" className="ml-2 underline" onClick={() => onTrace(err.extra.request_id)}>Why?</button>}</Notice>}
          </div>

          <div className="space-y-5 lg:col-span-2">
            <Panel>
              <PanelHeader title="3 · Result" subtitle="Itemised from the documented formula" />
              {!r ? <p className="p-5 text-sm text-slate-500">Complete the inputs and calculate to see an itemised estimate.</p> : (
                <div className="space-y-3 p-5">
                  <div>
                    <p className="text-xs uppercase text-slate-500">Estimated additional cover need</p>
                    {r.status === 'no_additional_cover_indicated'
                      ? <p className="text-lg font-semibold text-emerald-700">No additional cover indicated by these inputs</p>
                      : <p className="text-3xl font-semibold tabular-nums text-slate-900">₹{inr(r.recommended_additional_cover)}</p>}
                    <p className="text-xs text-slate-500">Figures rounded to ₹1,00,000.</p>
                  </div>
                  <Table caption="Itemised calculation">
                    <thead><tr><Th>Component</Th><Th className="text-right">Amount</Th></tr></thead>
                    <tbody>{Object.entries(r.components).map(([k, v]) => <tr key={k}><Td className="text-xs">{LABELS[k] || k}</Td><Td className="text-right font-mono text-xs">{v < 0 ? '−' : ''}₹{inr(Math.abs(v))}</Td></tr>)}</tbody>
                  </Table>
                  <p className="text-xs text-slate-600">Assumptions used: {Object.entries(r.assumptions).map(([k, v]) => `${ASSUMPTION_LABEL[k] || k} = ${v}`).join('; ')}</p>
                  <Button type="button" variant="ghost" size="sm" onClick={() => onTrace(res.request_id)}><Search className="h-3.5 w-3.5" aria-hidden /> Inspect decision</Button>
                  <p className="text-xs font-medium text-amber-800">{DISCLAIMER}</p>
                </div>
              )}
            </Panel>
            <Panel>
              <PanelHeader title="Data minimization" subtitle="What the calculator received" />
              <div className="space-y-3 p-5 text-sm">
                <div><p className="mb-1 text-xs font-medium uppercase text-slate-500">Inputs used</p>
                  <ul className="space-y-1">{(res?.minimization?.inputs_used || cfg.data.inputs).map((i) => <li key={i.input}><Badge tone="ALLOW">used</Badge> <span className="font-mono text-xs">{i.input}</span> <span className="text-xs text-slate-600">— {i.why}</span></li>)}</ul></div>
                {res?.minimization && <div><p className="mb-1 text-xs font-medium uppercase text-slate-500">Intentionally excluded</p><p className="flex flex-wrap gap-1">{res.minimization.attributes_excluded.map((a) => <Badge key={a} tone="DENY">{a}</Badge>)}</p></div>}
                {mode === 'whatif' && res && <p className="text-xs text-slate-600">What-if mode used only the values you typed.</p>}
              </div>
            </Panel>
          </div>
        </form>
      )}
    </>
  )
}
