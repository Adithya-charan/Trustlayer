import { useEffect, useRef, useState } from 'react'
import { Play, RotateCcw, ShieldCheck } from 'lucide-react'
import { api } from '../lib/api'
import { useApi } from '../lib/useApi'
import { useBackends } from '../lib/target'
import { Badge, Button, Empty, ErrorState, Loading, Notice, PageHeader, Panel, PanelHeader, Select, Table, Td, Th, cn, fmtTime } from '../components/ui'
import { ADMINS, BackendGate, BackendPicker, HERO_SQL, BeforeAfter, ResultTable, STRATEGIES, SourceBadge, Strategy, TAG_TONE, personName, roleName } from '../components/b1'

const ROLES = ['Admin', 'Support', 'Analyst']
const describe = (e) => `${e.status === 403 ? 'Not allowed for your role: ' : e.status === 409 ? 'Scan required: ' : ''}${e.message}`

// "Same database. Same query. Different identity. Different exposure."
function SameQuery({ me, backends, autorun, version, focusRole }) {
  const isAdmin = ADMINS.includes(me.role)
  const [sql, setSql] = useState(HERO_SQL)
  const [cmp, setCmp] = useState(null)
  const [one, setOne] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const ran = useRef(false)

  async function run() {
    setBusy(true); setErr(null); setCmp(null); setOne(null)
    try {
      if (isAdmin) setCmp(await api('/b1/compare', { method: 'POST', body: { target: backends.target, sql } }))
      else setOne(await api('/b1/query', { method: 'POST', body: { target: backends.target, sql } }))
    } catch (e) { setErr(e) } finally { setBusy(false) }
  }
  useEffect(() => { if (autorun && backends.ready && !ran.current) { ran.current = true; run() } }, [autorun, backends.ready]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (ran.current && version) run() }, [version]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Panel id="demo">
      <PanelHeader title="Same query, different identity" subtitle={isAdmin ? 'One SELECT, run once against the database and shown to each role exactly as the server would return it.' : `One SELECT, run as ${roleName(me.role)}. The server decides what comes back.`} />
      <div className="space-y-3 p-4">
        <label className="block text-xs font-medium text-slate-600">SQL (a single SELECT on one table)
          <textarea value={sql} onChange={(e) => setSql(e.target.value)} rows={2} maxLength={600} spellCheck={false} className="mt-1 w-full rounded-lg border border-slate-300 p-3 font-mono text-xs text-slate-900" />
        </label>
        <div className="flex flex-wrap items-center gap-3">
          <Button size="sm" onClick={run} loading={busy}><Play className="h-4 w-4" aria-hidden /> {isAdmin ? 'Run for every identity' : `Run as ${roleName(me.role)}`}</Button>
          <Button size="sm" variant="ghost" onClick={() => setSql(HERO_SQL)}>Reset example</Button>
        </div>
        {err && <Notice tone="error">{describe(err)}</Notice>}
      </div>
      {cmp && (
        <div className="border-t border-slate-100 p-4">
          <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-slate-600">
            <Badge tone={cmp.integrity.unchanged ? 'SUCCESS' : 'FAILED'}>{cmp.integrity.unchanged ? `Database unchanged (${cmp.integrity.after.rows.toLocaleString()} rows, fingerprint ${cmp.integrity.after.sample_hash})` : 'Source CHANGED'}</Badge>
            <span>{cmp.row_count} rows · {cmp.dialect}</span>
          </div>
          <div className="grid gap-4 xl:grid-cols-3">
            {ROLES.map((r) => (
              <div key={r} className={cn('min-w-0 overflow-hidden rounded-xl border bg-white', focusRole === r ? 'border-navy-600 ring-2 ring-blue-100' : 'border-slate-200')}>
                <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50/70 px-3 py-2"><span className="text-sm font-semibold text-slate-900">{r}</span><Badge tone="info">{r === 'Admin' ? 'full access' : r === 'Support' ? 'partial masks' : 'redact / hash'}</Badge></div>
                <ResultTable columns={cmp.views[r].columns} rows={cmp.views[r].rows} withheld={cmp.views[r].withheld} who={`${r} role`} />
              </div>
            ))}
          </div>
        </div>
      )}
      {one && <div className="border-t border-slate-100"><div className="px-4 py-3 text-xs text-slate-600"><Badge tone="info">as {one.role}</Badge> {one.row_count} rows · <Badge tone="SUCCESS">Database unchanged (read-only)</Badge></div><ResultTable columns={one.columns} rows={one.rows} withheld={one.withheld} who={`${me.display_name || me.username} (${one.role})`} /></div>}
    </Panel>
  )
}

function Matrix({ policy, focusRole }) {
  const { data, error, loading, reload } = policy
  if (loading && !data) return <Panel><Loading label="Loading policy" rows={2} /></Panel>
  if (error) return <Panel><ErrorState error={error} onRetry={reload} /></Panel>
  return (
    <Panel>
      <PanelHeader title="Masking policy by role" subtitle="What each role receives for each kind of data, enforced by the server on every query. Highlighted cells were changed by an Admin." />
      <Table caption="Masking policy by role">
        <thead><tr><Th>Kind of data</Th><Th>Classification</Th>{data.roles.map((r) => <Th key={r} className={focusRole === r ? 'text-navy-700' : ''}>{r}{r === data.your_role ? ' (you)' : ''}</Th>)}</tr></thead>
        <tbody>{data.kinds.filter((k) => k.kind !== 'NON_SENSITIVE').map((k) => (
          <tr key={k.kind}><Td className="text-xs">{k.kind}</Td><Td><Badge tone={TAG_TONE[k.tag]}>{k.tag}</Badge></Td>
            {data.roles.map((r) => (
              <Td key={r} className={cn(focusRole === r && 'bg-blue-50/40', data.matrix[r][k.kind] !== data.defaults[r][k.kind] && 'bg-amber-50/60')}>
                <Strategy s={data.matrix[r][k.kind]} />{data.matrix[r][k.kind] !== data.defaults[r][k.kind] && <span className="ml-1 text-[11px] text-slate-500">was {data.defaults[r][k.kind].toLowerCase()}</span>}
              </Td>
            ))}</tr>
        ))}</tbody>
      </Table>
      <ul className="grid gap-1 border-t border-slate-100 p-4 text-xs text-slate-600 sm:grid-cols-2">{Object.entries(data.strategies).map(([k, v]) => <li key={k}><Strategy s={k} /> <span className="ml-1">{v}</span></li>)}</ul>
    </Panel>
  )
}

// Admin-only. Every change is a real server-side policy write, audited with old -> new; the preview re-runs the SAME query as the chosen user.
function Editor({ backends, policy, overrides, params, onChanged }) {
  const users = useApi('/b1/users')
  const people = (users.data?.users || []).filter((u) => u.editable)
  const kinds = (policy.data?.kinds || []).filter((k) => k.kind !== 'NON_SENSITIVE').map((k) => k.kind)
  const [username, setUsername] = useState('')
  const [kind, setKind] = useState('PAN')
  const [strategy, setStrategy] = useState('')
  const [sql, setSql] = useState(HERO_SQL)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [out, setOut] = useState(null)
  const [err, setErr] = useState(null)
  const eff = useApi(username ? `/b1/policy/users/${encodeURIComponent(username)}` : null, [username, out?.done])
  const current = eff.data?.policy?.[kind]

  useEffect(() => { // default to the requested user (voice/links), else the first editable one
    if (!people.length) return
    const want = params.get('user')
    if (want && people.some((u) => u.username === want)) setUsername(want)
    else if (!username) setUsername((people.find((u) => u.username.includes('kavya')) || people[0]).username)
  }, [people.length, params.toString()]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (current) setStrategy(current.strategy === 'PARTIAL' ? 'REDACT' : 'PARTIAL') }, [username, kind, current?.strategy]) // eslint-disable-line react-hooks/exhaustive-deps

  const preview = () => api('/b1/preview', { method: 'POST', body: { target: backends.target, sql, username } })
  async function apply(reset) {
    setBusy(true); setErr(null); setOut(null)
    try {
      let before = null
      try { before = await preview() } catch { /* the preview is informative only; the policy change below does not depend on it */ }
      const body = { scope: 'user', subject: username, kind, strategy: reset ? '' : strategy, note: note.trim() }
      const r = reset ? await api('/b1/policy/overrides/reset', { method: 'POST', body }) : await api('/b1/policy/overrides', { method: 'PUT', body })
      let after = null
      try { after = await preview() } catch { /* same */ }
      setOut({ change: r, before, after, reset, done: Date.now() })
      onChanged()
    } catch (e) { setErr(e) } finally { setBusy(false) }
  }

  const person = people.find((u) => u.username === username)
  return (
    <Panel id="editor">
      <PanelHeader title="Edit a user's policy" subtitle="A real policy change: saved on the server, applied to that user's very next query, and recorded in the audit trail." />
      {users.loading && !users.data ? <Loading rows={2} /> : users.error ? <ErrorState error={users.error} onRetry={users.reload} /> : (
        <div className="space-y-4 p-4">
          <div className="flex flex-wrap items-end gap-3">
            <Select label="User" value={username} onChange={setUsername} options={people.map((u) => [u.username, `${personName(u)} (${roleName(u.role)})`])} className="min-w-56" />
            <Select label="Kind of data" value={kind} onChange={setKind} options={kinds} />
            <div className="flex flex-col gap-1 text-xs font-medium text-slate-600">Current policy<span className="flex min-h-9 items-center gap-2">{current ? <><Strategy s={current.strategy} /><SourceBadge source={current.source} /></> : '-'}</span></div>
            <Select label="Change to" value={strategy} onChange={setStrategy} options={STRATEGIES.map((s) => [s, s])} />
            <Button size="sm" onClick={() => apply(false)} loading={busy} disabled={!username || !strategy || strategy === current?.strategy}><ShieldCheck className="h-4 w-4" aria-hidden /> Apply policy change</Button>
            <Button size="sm" variant="outline" onClick={() => apply(true)} disabled={busy || current?.source !== 'user'}><RotateCcw className="h-4 w-4" aria-hidden /> Reset to default</Button>
          </div>
          <label className="block text-xs font-medium text-slate-600">Reason for the change (optional, recorded in the audit trail)
            <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={120} placeholder="e.g. Reduced PAN exposure for Analyst role" className="mt-1 min-h-9 w-full rounded-lg border border-slate-300 px-3 text-sm text-slate-900" />
          </label>
          <label className="block text-xs font-medium text-slate-600">Query to re-run as {person ? personName(person) : 'the user'}
            <input value={sql} onChange={(e) => setSql(e.target.value)} maxLength={600} spellCheck={false} className="mt-1 min-h-9 w-full rounded-lg border border-slate-300 px-3 font-mono text-xs text-slate-900" />
          </label>
          {err && <Notice tone="error">{describe(err)}</Notice>}
          {out && (
            <div className="space-y-3">
              <Notice tone="success">{out.reset ? 'Reset: ' : 'Policy saved: '}<strong>{personName({ display_name: out.change.display_name, username: out.change.subject })}</strong> · {out.change.kind}: <strong>{out.change.old}</strong> → <strong>{out.change.new}</strong>. Recorded in the Audit Center.</Notice>
              <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm"><span className="font-medium text-slate-700">{out.change.kind}</span><BeforeAfter old={out.change.old} next={out.change.new} /><span className="text-xs text-slate-500">Database unchanged · applies to {personName(person)}'s next query</span></div>
              <div className="grid gap-4 xl:grid-cols-2">
                {[['Before', out.before], ['After', out.after]].map(([label, r]) => (
                  <div key={label} className="min-w-0 overflow-hidden rounded-xl border border-slate-200">
                    <div className="border-b border-slate-100 bg-slate-50/70 px-3 py-2 text-sm font-semibold text-slate-900">{label} <span className="font-normal text-slate-500">· as {personName(person)}</span></div>
                    {r ? <ResultTable columns={r.columns} rows={r.rows} withheld={r.withheld} who={`${personName(person)} (${r.role})`} /> : <Empty title="Preview unavailable" hint="The table may not be scanned yet." />}
                  </div>
                ))}
              </div>
            </div>
          )}
          <p className="text-xs text-slate-500">Admin accounts cannot be restricted and always see real values. Only Support and Analyst users have editable policies.</p>
        </div>
      )}
      <Custom overrides={overrides} onChanged={onChanged} />
    </Panel>
  )
}

function Custom({ overrides, onChanged }) {
  const rows = overrides.data?.overrides || []
  const [err, setErr] = useState(null)
  async function reset(o) {
    setErr(null)
    try { await api('/b1/policy/overrides/reset', { method: 'POST', body: { scope: o.scope, subject: o.subject, kind: o.kind } }); onChanged() } catch (e) { setErr(e) }
  }
  return (
    <div className="border-t border-slate-100">
      <div className="px-5 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Policies edited by an Admin ({rows.length})</div>
      {err && <Notice tone="error" className="mx-4 mb-3">{err.message}</Notice>}
      {!rows.length ? <p className="px-5 pb-4 text-xs text-slate-500">None. Every role currently follows the built-in policy.</p> : (
        <Table caption="Edited policies">
          <thead><tr><Th>Applies to</Th><Th>Kind</Th><Th>Strategy</Th><Th>Changed by</Th><Th>When</Th><Th>Action</Th></tr></thead>
          <tbody>{rows.map((o) => (
            <tr key={`${o.scope}.${o.subject}.${o.kind}`}><Td className="text-xs">{personName({ display_name: o.display_name, username: o.subject })} <span className="text-slate-500">({o.scope})</span></Td><Td className="text-xs">{o.kind}</Td><Td><Strategy s={o.strategy} /></Td>
              <Td className="text-xs">{o.updated_by}</Td><Td className="text-xs">{fmtTime(o.updated_at)}</Td><Td><Button size="sm" variant="outline" onClick={() => reset(o)}>Reset</Button></Td></tr>
          ))}</tbody>
        </Table>
      )}
    </div>
  )
}

export default function Policies({ me, params, version, bump }) {
  const backends = useBackends()
  const isAdmin = ADMINS.includes(me.role)
  const [stamp, setStamp] = useState(0)
  const policy = useApi('/b1/policy', [stamp, version])
  const overrides = useApi(isAdmin ? '/b1/policy/overrides' : null, [stamp, version])
  const changed = () => { setStamp((s) => s + 1); bump?.() }
  const focusRole = params.get('role')
  return (
    <>
      <PageHeader title="Access Policies" description="Identity-aware masking. The server resolves the signed-in identity, evaluates its policy and masks each value on the way out; the database itself is never modified." />
      <div className="space-y-5">
        <BackendPicker backends={backends} />
        {!backends.ready ? <BackendGate backends={backends} /> : <SameQuery me={me} backends={backends} autorun={params.get('demo') === '1'} version={stamp} focusRole={focusRole} />}
        <Matrix policy={policy} focusRole={focusRole} />
        {isAdmin && backends.ready && <Editor backends={backends} policy={policy} overrides={overrides} params={params} onChanged={changed} />}
      </div>
    </>
  )
}
