import { useEffect, useRef, useState } from 'react'
import { UploadCloud } from 'lucide-react'
import { api } from '../lib/api'
import { Badge, Button, Metric, MetricStrip, Notice, Panel, PanelHeader, Table, Td, Th } from './ui'

const RISK_TONE = { Critical: 'HIGH', High: 'HIGH', Medium: 'MEDIUM', Low: 'neutral', Unclassified: 'neutral' }
const SOURCE = { rule: 'rule', ml: 'ML model', column_name: 'column name' }
const STATUS = { detected: ['Detected', 'success'], suspected: ['Suspected', 'MEDIUM'], unclassified: ['Unclassified', 'neutral'] }

// Upload a CSV and run the same hybrid engine the backend uses. The file is analysed in memory on the server and discarded; only counts, categories and risk come back.
export default function UploadPanel() {
  const input = useRef(null)
  const [mlInfo, setMlInfo] = useState(null)
  const [state, setState] = useState({ busy: false, error: null, result: null })
  useEffect(() => { api('/b1/detection/status').then(setMlInfo).catch(() => setMlInfo(null)) }, [])

  async function send(file) {
    if (!file) return
    setState({ busy: true, error: null, result: null })
    try {
      const r = await api(`/b1/upload/analyze?filename=${encodeURIComponent(file.name)}`, { method: 'POST', raw: file.type ? file : new Blob([file], { type: 'text/csv' }) })
      setState({ busy: false, error: null, result: r })
      api('/b1/detection/status').then(setMlInfo).catch(() => {})
    } catch (e) { setState({ busy: false, error: e, result: null }) }
    if (input.current) input.current.value = ''
  }
  const { busy, error, result } = state
  const sm = result?.summary

  return (
    <Panel>
      <PanelHeader title="Analyse a CSV dataset" subtitle={`Detects PII with rules plus a pretrained ML model. The file is processed in memory and not stored${mlInfo ? `; limit ${mlInfo.upload_max_mb} MB / ${mlInfo.upload_max_rows.toLocaleString('en-US')} rows` : ''}.`}
        actions={<>
          <input ref={input} type="file" accept=".csv,text/csv" className="sr-only" id="csv-upload" onChange={(e) => send(e.target.files?.[0])} />
          <Button onClick={() => input.current?.click()} loading={busy}><UploadCloud className="h-4 w-4" aria-hidden /> {result ? 'Analyse another dataset' : 'Choose CSV'}</Button>
        </>} />
      <div className="space-y-4 p-4">
        {mlInfo && (
          <p className="text-xs text-slate-600">
            ML model <span className="font-mono">{mlInfo.model}</span>: {mlInfo.enabled ? (mlInfo.state === 'failed' ? <Badge tone="MEDIUM">unavailable, rules-only fallback</Badge> : mlInfo.state === 'ready' ? <Badge tone="success">loaded</Badge> : <Badge tone="neutral">loads on first analysis</Badge>) : <Badge tone="neutral">disabled, rules-only</Badge>}
            {mlInfo.error && <span className="ml-2 text-slate-500">{mlInfo.error}</span>}
          </p>
        )}
        {busy && <Notice>Analysing. The first run loads the ML model, which can take a minute.</Notice>}
        {error && <Notice tone="error">{error.message}</Notice>}
        {!result && !busy && !error && <p className="text-sm text-slate-500">No dataset analysed yet. Choose a CSV to see detected columns, PII categories, detection methods, risk and recommended protection.</p>}
        {result && (
          <>
            <Notice tone={result.ml.mode === 'hybrid' ? 'success' : 'warn'}>
              {result.ml.mode === 'hybrid' ? 'Hybrid detection: rules and the ML model both ran.' : `Rules only: the ML model was not used${result.ml.error ? ` (${result.ml.error})` : ''}. Names, places and organisations are not detected in this mode.`}
            </Notice>
            <MetricStrip>
              <Metric label="Rows x columns" value={`${sm.rows.toLocaleString('en-US')} x ${sm.columns}`} sub={result.name} />
              <Metric label="Detected sensitive" value={sm.sensitive_columns} sub="columns confirmed by values" />
              <Metric label="Suspected" value={sm.suspected_columns} sub="need human review" />
              <Metric label="Highest risk" value={sm.highest_risk || '-'} sub={`${sm.unclassified_columns} unclassified`} />
            </MetricStrip>
            {result.input.malformed_rows > 0 && <Notice tone="warn">{result.input.malformed_rows} malformed row(s) had the wrong number of fields; missing fields were treated as empty.</Notice>}
            <Table caption="Detection results by column">
              <thead><tr><Th>Column</Th><Th>Category</Th><Th>Status</Th><Th>Matches</Th><Th>Detected by</Th><Th>Risk</Th><Th>Recommended protection</Th></tr></thead>
              <tbody>{result.columns.map((c) => {
                const [label, tone] = STATUS[c.status]
                return (
                  <tr key={c.column}>
                    <Td className="font-mono text-xs">{c.column}</Td>
                    <Td className="text-xs">{c.category || '-'}</Td>
                    <Td><Badge tone={tone}>{label}</Badge>{c.needs_review && <span className="ml-1 text-[11px] text-amber-700">review</span>}</Td>
                    <Td className="text-xs tabular-nums" title={c.evidence}>{c.match_count.toLocaleString('en-US')} / {c.values_inspected.toLocaleString('en-US')}{!c.exact && ' (est.)'}</Td>
                    <Td><span className="flex flex-wrap gap-1">{c.sources.length ? c.sources.map((s) => <Badge key={s} tone="neutral">{SOURCE[s] || s}</Badge>) : <span className="text-xs text-slate-400">none</span>}</span></Td>
                    <Td><Badge tone={RISK_TONE[c.risk]} >{c.risk}</Badge></Td>
                    <Td className="text-xs text-slate-700" title={c.risk_explanation}>{c.recommended_protection ? `${c.recommended_protection}: ${c.protection_note}` : 'Review manually'}</Td>
                  </tr>
                )
              })}</tbody>
            </Table>
            <p className="text-xs text-slate-500">Counts are values (cells) containing the category. Hover a row for the evidence or the risk explanation. ML scores are model scores, not calibrated probabilities, and do not set the risk level. A column with no match is "unclassified", not proven safe.</p>
          </>
        )}
      </div>
    </Panel>
  )
}
