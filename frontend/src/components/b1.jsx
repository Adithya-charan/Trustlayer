import { useState } from 'react'
import { ArrowRight, Database, HelpCircle, KeyRound, Lock, RefreshCw, ScanSearch, ShieldAlert, SlidersHorizontal, Table2, UserCheck, X } from 'lucide-react'
import { Badge, Button, Empty, Notice, Table, Td, Th, cn, fmtTime } from './ui'

export const ADMINS = ['Admin', 'security_admin']
export const roleName = (r) => (ADMINS.includes(r) ? 'Admin' : r === 'analyst' ? 'Analyst' : r)
// Some seeded accounts carry the role in their display name ("Kavya Hegde (Analyst)"); the role is shown separately, so drop that suffix.
export const personName = (u) => String(u?.display_name || u?.username || '').replace(/\s*\((admin|support|analyst|security[ _]admin|compliance[ _]officer)\)\s*$/i, '')

const STRAT_TONE = { ALLOW: 'ALLOW', PARTIAL: 'PARTIAL', REDACT: 'MASK', HASH: 'AI', DENY: 'DENY' }
const STRAT_TEXT = { ALLOW: 'Real value', PARTIAL: 'Partial mask', REDACT: 'Redacted', HASH: 'Hashed', DENY: 'Withheld' }
export const STRATEGIES = ['ALLOW', 'PARTIAL', 'REDACT', 'HASH', 'DENY']
export const TAG_TONE = { PII_HIGH: 'HIGH', PII_MEDIUM: 'MEDIUM', FINANCIAL_CONFIDENTIAL: 'WARNING', PAYMENT_SENSITIVE: 'HIGH', NON_SENSITIVE: 'neutral' }
export const RISK_TONE = { High: 'HIGH', Medium: 'MEDIUM', Low: 'neutral' }

export const Strategy = ({ s }) => <Badge tone={STRAT_TONE[s]}>{STRAT_TEXT[s] || s}</Badge>
export const SourceBadge = ({ source }) => (source && source !== 'default' ? <Badge tone="info">{source === 'user' ? 'custom (user)' : 'custom (role)'}</Badge> : null)

export function Fact({ label, children }) {
  return <div className="min-w-0"><dt className="text-[11px] font-medium uppercase tracking-wide text-slate-500">{label}</dt><dd className="mt-0.5 truncate text-sm text-slate-900">{children}</dd></div>
}

// One chip per backend, straight from the server's live health check. "Connected" only appears when the server reports a real connection.
export function BackendPicker({ backends, compact }) {
  const { targets, target, choose, loading, error, reload } = backends
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Database backend">
      <span className="text-xs font-medium text-slate-500"><Database className="mr-1 inline h-3.5 w-3.5" aria-hidden />Backend</span>
      {targets.map((t) => {
        const up = t.connected && t.schema_found
        return (
          <button key={t.name} type="button" disabled={!up} aria-pressed={target === t.name} onClick={() => choose(t.name)}
            title={up ? `${t.label}: connected${t.read_only ? ', read-only' : ''}` : t.error || 'Not connected'}
            className={cn('inline-flex min-h-9 items-center gap-2 rounded-lg border px-3 text-xs font-medium transition', target === t.name && up ? 'border-navy-600 bg-blue-50 text-navy-700' : 'border-slate-200 bg-white text-slate-700',
              !up && 'cursor-not-allowed opacity-60')}>
            <span aria-hidden className={cn('h-2 w-2 rounded-full', up ? 'bg-emerald-500' : t.configured === false ? 'bg-slate-400' : 'bg-red-500')} />
            {t.engine === 'PostgreSQL' && t.provider === 'Neon' ? 'Neon PostgreSQL' : t.engine}
            {!compact && <span className="font-normal text-slate-500">{up ? `${t.tables} tables${t.read_only ? ' · read-only' : ''}` : t.configured === false ? 'not configured' : 'disconnected'}</span>}
          </button>
        )
      })}
      <Button size="sm" variant="ghost" onClick={reload} loading={loading} aria-label="Check backends again"><RefreshCw className="h-3.5 w-3.5" aria-hidden /></Button>
      {error && <span className="text-xs text-red-700">{error.message}</span>}
    </div>
  )
}

// Shown instead of a page body when the chosen backend cannot be used. Never claims a connection that the server did not confirm.
export function BackendGate({ backends }) {
  const { current, loading, error } = backends
  if (loading && !current) return <Notice>Checking the database connection…</Notice>
  if (error) return <Notice tone="error">{error.message}</Notice>
  if (!current) return <Notice tone="warn">Unknown backend.</Notice>
  return (
    <Notice tone="error">
      <strong>{current.label} is not available.</strong>{' '}
      {current.configured === false ? current.error : current.schema_found === false ? current.error : `The server could not reach it${current.error ? ` (${current.error})` : ''}.`} Pick another backend above or fix the connection and check again.
    </Notice>
  )
}

export function BackendFacts({ t }) {
  if (!t) return null
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3 lg:grid-cols-6">
      <Fact label="Provider">{t.provider}</Fact>
      <Fact label="Engine">{t.engine}</Fact>
      <Fact label="Schema"><span className="font-mono text-xs">{t.schema || 'default'}</span></Fact>
      <Fact label="Tables">{t.connected && t.schema_found ? t.tables : '-'}</Fact>
      <Fact label="Access">{t.read_only === true ? <span className="inline-flex items-center gap-1"><Lock className="h-3 w-3" aria-hidden />Read-only</span> : t.read_only === false ? 'Read/write' : 'Unknown'}</Fact>
      <Fact label="Last check">{t.checked_at ? fmtTime(t.checked_at) : '-'}</Fact>
    </dl>
  )
}

// "Why was this masked / denied?": the exact policy path, who it applies to and the reason, read from the server's decision for THIS result. The database itself never changes.
export function WhyCard({ item, who, onClose }) {
  const w = item.why
  if (!w) return null
  const denied = w.strategy === 'DENY'
  return (
    <section aria-label={`Why ${item.name} was ${denied ? 'denied' : 'protected'}`} className="m-3 rounded-xl border border-slate-200 bg-white p-4 shadow-card">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-sm font-semibold text-slate-900">{denied ? 'Why was this denied?' : w.strategy === 'ALLOW' ? 'Why is this visible?' : 'Why is this protected?'}</h3>
        <button type="button" onClick={onClose} aria-label="Close explanation" className="rounded p-1 text-slate-500 hover:bg-slate-100"><X className="h-4 w-4" aria-hidden /></button>
      </div>
      <ol className="mt-3 flex flex-wrap items-center gap-1.5 text-[11px] font-medium text-slate-700" aria-label="Decision path">
        {['Request', 'Identity', 'Policy', 'Decision', denied ? 'Withheld' : 'Masking', 'Audit'].map((t, i, a) => <li key={t} className="flex items-center gap-1.5"><span className="rounded-md bg-slate-100 px-2 py-1">{t}</span>{i < a.length - 1 && <ArrowRight className="h-3 w-3 text-slate-400" aria-hidden />}</li>)}
      </ol>
      <dl className="mt-3 grid gap-x-6 gap-y-3 sm:grid-cols-2">
        <Fact label="Requested"><span className="font-mono text-xs">{item.name}</span> <span className="text-slate-500">· {w.kind}</span></Fact>
        <Fact label="User">{who || 'you'}</Fact>
        <Fact label="Policy"><span className="font-mono text-xs">{w.policy_path}</span></Fact>
        <Fact label="Applied from">{w.source_label}</Fact>
        <Fact label="Decision"><span className="inline-flex items-center gap-2"><Strategy s={w.strategy} /><span className="text-xs font-semibold text-slate-700">{w.result}</span></span></Fact>
        <Fact label="Database"><Badge tone="SUCCESS">Unchanged</Badge></Fact>
      </dl>
      <p className="mt-3 text-sm text-slate-800"><span className="font-semibold">Why: </span>{w.reason}</p>
      {denied && <p className="mt-1 text-xs text-slate-600">Access restricted by your current policy. The attempt was recorded in the audit trail.</p>}
    </section>
  )
}

export function ResultTable({ columns, rows, withheld, who }) {
  const [why, setWhy] = useState(null)
  const ask = (item) => setWhy((cur) => (cur?.name === item.name ? null : item))
  return (
    <>
      {withheld?.length > 0 && (
        <Notice tone="warn" className="m-3">
          <span className="font-medium">Access restricted by your current policy.</span> Withheld for this identity:{' '}
          {withheld.map((w) => <button key={w.column} type="button" onClick={() => ask({ name: w.column, why: w.why })} aria-pressed={why?.name === w.column} className="mr-1 inline-flex items-center gap-1 rounded-md border border-amber-300 bg-white px-1.5 py-0.5 font-mono text-xs text-amber-900 hover:bg-amber-50">{w.column}<HelpCircle className="h-3 w-3" aria-hidden /><span className="sr-only">Why was it withheld?</span></button>)}
        </Notice>
      )}
      {why && <WhyCard item={why} who={who} onClose={() => setWhy(null)} />}
      {!rows.length ? <Empty title="No rows" hint="The query matched nothing." /> : (
        <Table caption="Query result">
          <thead><tr>{columns.map((c) => (
            <Th key={c.name}>
              <span className="block">{c.name}</span>
              <span className="mt-1 flex items-center gap-1 normal-case"><Strategy s={c.strategy} />
                {c.why && <button type="button" onClick={() => ask({ name: c.name, why: c.why })} aria-pressed={why?.name === c.name} className="rounded p-0.5 text-slate-500 hover:bg-slate-100 hover:text-navy-700" title="Why this result?"><HelpCircle className="h-3.5 w-3.5" aria-hidden /><span className="sr-only">Why this result for {c.name}?</span></button>}
              </span>
            </Th>
          ))}</tr></thead>
          <tbody>{rows.map((r, i) => <tr key={i}>{columns.map((c) => <Td key={c.name}><span className="whitespace-pre-wrap break-words font-mono text-xs">{r[c.name] === null ? <em className="text-slate-400">null</em> : String(r[c.name])}</span></Td>)}</tr>)}</tbody>
        </Table>
      )}
    </>
  )
}

// HASH → PARTIAL
export function BeforeAfter({ old, next }) {
  return <span className="inline-flex items-center gap-1.5"><Strategy s={old} /><ArrowRight className="h-3.5 w-3.5 text-slate-400" aria-hidden /><Strategy s={next} /></span>
}

const ACTION_ICON = { Query: Table2, 'Access attempt': ShieldAlert, 'Policy change': SlidersHorizontal, 'Classification review': ScanSearch, Scan: ScanSearch, Login: KeyRound }
const DECISION_LABEL = { ALLOW: 'Allowed', MASK: 'Masked', DENY: 'Denied' }

// One line per meaningful event: who did what to which resource, the policy that decided and the reason. Built from the server's audit trail only.
export function ActivityList({ events, onUser, empty }) {
  if (!events?.length) return <Empty title={empty || 'No activity yet'} hint="Queries, policy changes and sign-ins appear here as they happen." />
  return (
    <ol className="divide-y divide-slate-100" aria-label="Recent activity">
      {events.map((e) => {
        const Icon = ACTION_ICON[e.action] || UserCheck
        const tone = e.operation === 'b1_access_denied' || e.decision === 'DENY' ? 'DENY' : e.decision
        return (
          <li key={e.id} className="flex gap-3 px-4 py-3">
            <span className={cn('mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg', tone === 'DENY' ? 'bg-red-50 text-red-700' : tone === 'MASK' ? 'bg-amber-50 text-amber-800' : 'bg-blue-50 text-navy-700')}><Icon className="h-4 w-4" aria-hidden /></span>
            <div className="min-w-0 flex-1 space-y-1">
              <p className="text-sm text-slate-900">
                {onUser ? <button type="button" className="font-semibold underline-offset-2 hover:underline" onClick={() => onUser(e.actor)}>{e.actor_name}</button> : <span className="font-semibold">{e.actor_name}</span>}
                <span className="text-slate-500"> ({e.role})</span> · {e.action}{e.resource && <> · <span className="font-mono text-xs">{e.resource}</span></>}
              </p>
              {e.change ? <p className="flex flex-wrap items-center gap-2 text-xs text-slate-700"><span>{e.change.subject} · {e.change.kind}</span><BeforeAfter old={e.change.old} next={e.change.new} />{e.change.verb === 'reset' && <Badge tone="neutral">reset to default</Badge>}</p>
                : <p className="text-xs text-slate-700">{e.result}</p>}
              {e.why?.[0] && <p className="text-xs text-slate-500"><span className="font-medium text-slate-600">Why: </span>{e.why[0]}</p>}
              <p className="font-mono text-[11px] text-slate-400">{fmtTime(e.ts)} · {e.policy}</p>
            </div>
            <Badge tone={tone}>{e.operation === 'b1_access_denied' ? 'Denied' : DECISION_LABEL[e.decision] || e.decision}</Badge>
          </li>
        )
      })}
    </ol>
  )
}

export const HERO_SQL = 'SELECT pan_no, aadhaar_no FROM kyc_records LIMIT 5'
