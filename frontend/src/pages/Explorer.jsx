import { useEffect, useState } from 'react'
import { Lock } from 'lucide-react'
import { api } from '../lib/api'
import { useApi } from '../lib/useApi'
import { useBackends } from '../lib/target'
import { Badge, Empty, ErrorState, Loading, Notice, PageHeader, Panel, PanelHeader, Table, Td, Th, cn } from '../components/ui'
import { BackendGate, BackendPicker, ResultTable, RISK_TONE, Strategy, TAG_TONE, roleName } from '../components/b1'

const METHOD = { column_name: 'column name', value_pattern: 'value pattern', luhn: 'Luhn checksum', free_text_scan: 'free-text scan', ml_ner: 'ML model (uncertain)', manual_review: 'manual review' }

export default function Explorer({ me, params, go, version }) {
  const backends = useBackends()
  const { data, error, loading, reload } = useApi(backends.ready ? `/b1/schema?target=${backends.target}` : null, [backends.target, backends.ready, version])
  const [sel, setSel] = useState(null)
  const [sample, setSample] = useState({ loading: false, data: null, error: null })
  const tables = data?.tables || []
  const want = params.get('table')
  useEffect(() => { // pick the requested table (voice/links), else the first one
    if (!tables.length) return
    const hit = tables.find((t) => t.name === want) || tables.find((t) => t.name === sel) || tables[0]
    if (hit.name !== sel) setSel(hit.name)
  }, [tables, want]) // eslint-disable-line react-hooks/exhaustive-deps
  const table = tables.find((t) => t.name === sel)

  useEffect(() => {
    if (!table || !data?.scanned) { setSample({ loading: false, data: null, error: null }); return undefined }
    let live = true
    setSample({ loading: true, data: null, error: null })
    api('/b1/query', { method: 'POST', body: { target: backends.target, table: table.name, columns: ['*'], limit: 5 } })
      .then((r) => live && setSample({ loading: false, data: r, error: null })).catch((e) => live && setSample({ loading: false, data: null, error: e }))
    return () => { live = false }
  }, [table?.name, data?.scanned, backends.target, version]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <PageHeader title="Data Explorer" description={`Browse the connected database as ${roleName(me.role)}: every column with its type, classification, risk and the masking your policy applies. Sample rows come back through the same masking engine and are audited.`} />
      <div className="space-y-5">
        <BackendPicker backends={backends} />
        {!backends.ready ? <BackendGate backends={backends} /> : loading && !data ? <Panel><Loading label="Loading schema" /></Panel> : error ? <Panel><ErrorState error={error} onRetry={reload} /></Panel> : (
          <div className="grid gap-5 lg:grid-cols-[17rem_1fr]">
            <Panel>
              <PanelHeader title="Tables" subtitle={`${tables.length} in the schema`} />
              <ul className="max-h-[32rem] divide-y divide-slate-100 overflow-y-auto">
                {tables.map((t) => (
                  <li key={t.name}>
                    <button type="button" onClick={() => { setSel(t.name); go(`explorer?table=${t.name}`) }} aria-current={sel === t.name}
                      className={cn('flex min-h-12 w-full flex-col items-start justify-center px-4 py-2 text-left hover:bg-slate-50', sel === t.name && 'bg-blue-50')}>
                      <span className="flex w-full items-center justify-between gap-2"><span className="font-mono text-xs font-medium text-slate-900">{t.name}</span>{t.risk && <Badge tone={RISK_TONE[t.risk]}>{t.risk}</Badge>}</span>
                      <span className="text-[11px] text-slate-500">{t.rows.toLocaleString('en-US')} rows · {t.columns.length} columns{data.scanned ? ` · ${t.sensitive_columns} sensitive` : ''}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </Panel>

            {table && (
              <div className="min-w-0 space-y-5">
                {!data.scanned && <Notice tone="warn">This database has not been scanned yet, so columns are unclassified and sample rows are locked. An Admin can scan it from Data Discovery.</Notice>}
                <Panel>
                  <PanelHeader title={<span className="font-mono">{table.name}</span>} subtitle={`${table.rows.toLocaleString('en-US')} rows · ${table.columns.length} columns · viewed as ${data.your_role}`} />
                  <Table caption={`Columns of ${table.name}`}>
                    <thead><tr><Th>Column</Th><Th>Type</Th><Th>Classification</Th><Th>Risk</Th><Th>Detected by</Th><Th>Masking for you</Th></tr></thead>
                    <tbody>{table.columns.map((c) => (
                      <tr key={c.name}>
                        <Td><span className="font-mono text-xs">{c.name}</span>{c.primary_key && <Badge tone="neutral" className="ml-2">key</Badge>}</Td>
                        <Td className="text-xs text-slate-600">{c.type}</Td>
                        <Td>{c.tag ? <><Badge tone={TAG_TONE[c.tag]}>{c.tag}</Badge>{c.kind !== c.tag && <span className="ml-2 text-xs text-slate-500">{c.kind}</span>}</> : <span className="text-xs text-slate-400">not scanned</span>}</Td>
                        <Td>{c.risk ? <Badge tone={RISK_TONE[c.risk]}>{c.risk}</Badge> : '-'}</Td>
                        <Td><span className="flex flex-wrap gap-1">{c.methods?.length ? c.methods.map((m) => <Badge key={m} tone="neutral">{METHOD[m] || m}</Badge>) : <span className="text-xs text-slate-400">-</span>}</span></Td>
                        <Td>{c.strategy ? <Strategy s={c.strategy} /> : '-'}</Td>
                      </tr>
                    ))}</tbody>
                  </Table>
                </Panel>

                <Panel>
                  <PanelHeader title="Sample rows" subtitle={`First 5 rows as ${data.your_role} sees them. The stored data is never changed.`}
                    actions={<Badge tone="info"><Lock className="mr-1 inline h-3 w-3" aria-hidden />Read-only</Badge>} />
                  {!data.scanned ? <Empty title="Samples are locked until the table is scanned" /> : sample.loading ? <Loading label="Loading sample rows" rows={2} /> : sample.error ? (
                    <Notice tone="error" className="m-4">{sample.error.message}</Notice>
                  ) : sample.data && <ResultTable columns={sample.data.columns} rows={sample.data.rows} withheld={sample.data.withheld} who={`${me.display_name || me.username} (${roleName(me.role)})`} />}
                </Panel>
              </div>
            )}
          </div>
        )}
      </div>
    </>
  )
}
