import { motion } from 'framer-motion'
import { CheckCircle2, ClipboardList, Gauge, ShieldCheck, SlidersHorizontal, User, XCircle } from 'lucide-react'
import { Badge, cn, fmtTime, strategyTone } from './ui'

// Vertical flow for one audit event. It renders only metadata the audit record holds: names, categories,
// strategies, decision and risk. It never receives or shows field values.
const TONE = {
  ok: { dot: 'bg-emerald-500 ring-emerald-100', line: 'bg-emerald-200', icon: 'text-emerald-600' },
  mask: { dot: 'bg-electric ring-blue-100', line: 'bg-blue-200', icon: 'text-electric' },
  warn: { dot: 'bg-amber-500 ring-amber-100', line: 'bg-amber-200', icon: 'text-amber-600' },
  bad: { dot: 'bg-rose-500 ring-rose-100', line: 'bg-rose-200', icon: 'text-rose-600' },
  info: { dot: 'bg-violet-500 ring-violet-100', line: 'bg-violet-200', icon: 'text-violet-600' },
}

function Step({ i, tone, icon: Icon, title, children, last }) {
  const t = TONE[tone]
  return (
    <motion.li initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.07, duration: 0.25 }} className="relative flex gap-4 pb-6 last:pb-0">
      {!last && <span aria-hidden className={cn('absolute left-[15px] top-8 h-[calc(100%-1.5rem)] w-0.5', t.line)} />}
      <span className={cn('relative z-10 mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full ring-4', t.dot)}><Icon className="h-4 w-4 text-white" aria-hidden /></span>
      <div className="min-w-0 flex-1">
        <h3 className="text-sm font-semibold text-body">{title}</h3>
        <div className="mt-1 text-sm text-slate-600">{children}</div>
      </div>
    </motion.li>
  )
}

export default function DecisionTimeline({ data }) {
  const fields = Object.entries(data.fields || {})
  const denied = fields.filter(([, v]) => v.strategy === 'DENY')
  const protectedCount = fields.filter(([, v]) => v.strategy !== 'ALLOW' && v.strategy !== 'DENY').length
  const decisionTone = data.decision === 'DENY' ? 'bad' : data.decision === 'PARTIAL' ? 'mask' : 'ok'
  const riskTone = data.risk_response === 'BLOCK' ? 'bad' : data.risk_response ? 'warn' : 'ok'
  return (
    <ol aria-label="Decision timeline">
      <Step i={0} tone="info" icon={User} title="Request">
        <p><b className="text-body">{data.actor}</b> · {data.role} requested <b className="text-body">{data.operation}</b> at {fmtTime(data.ts)}.</p>
        <p className="mt-1">Resource: {fields.length ? <>{fields.length} field{fields.length > 1 ? 's' : ''}{data.subject_ref ? ` of ${data.subject_ref}` : ''}</> : data.subject_ref || 'no fields involved'}.</p>
      </Step>
      <Step i={1} tone="info" icon={SlidersHorizontal} title="Purpose and policy">
        <p>Declared purpose: <b className="text-body">{data.purpose}</b></p>
        <p className="mt-1">Policy evaluated: <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">{data.policy}</code></p>
      </Step>
      <Step i={2} tone={riskTone} icon={Gauge} title="Risk assessment">
        <p>Score <b className="tabular-nums text-body">{data.risk_score}</b>{data.risk_response ? <> · response <Badge tone={data.risk_response === 'BLOCK' ? 'DENY' : 'MEDIUM'}>{data.risk_response}</Badge></> : ' · no action needed'}</p>
        {data.risk_signals.length > 0 && <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs">{data.risk_signals.map((s, k) => <li key={k}><b>{s.rule}</b>: {s.detail}</li>)}</ul>}
      </Step>
      <Step i={3} tone={decisionTone} icon={data.decision === 'DENY' ? XCircle : ShieldCheck} title="Protection applied">
        <p className="flex flex-wrap items-center gap-2"><Badge tone={data.decision}>{data.decision === 'PARTIAL' ? 'MASKED' : data.decision}</Badge>{data.reason}</p>
        {fields.length > 0 && (
          <>
            <p className="mt-1 text-xs text-muted">{protectedCount} protected · {denied.length} withheld · {fields.length - protectedCount - denied.length} returned as allowed</p>
            <ul className="mt-2 divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200">
              {fields.map(([f, v]) => (
                <li key={f} className="flex flex-wrap items-center justify-between gap-2 bg-white px-3 py-2">
                  <code className="text-xs text-body">{f}</code>
                  <span className="flex items-center gap-1.5"><Badge>{v.category}</Badge><Badge tone={strategyTone(v.strategy)}>{v.strategy}</Badge></span>
                </li>
              ))}
            </ul>
          </>
        )}
      </Step>
      <Step i={4} tone="ok" icon={ClipboardList} title="Recorded in audit trail" last>
        <p className="flex items-center gap-1.5"><CheckCircle2 className="h-4 w-4 text-emerald-600" aria-hidden /> Event ID <code className="break-all rounded bg-slate-100 px-1.5 py-0.5 text-xs">{data.request_id}</code></p>
        <p className="mt-1 text-xs text-muted">The record holds field names and strategies, never values.</p>
      </Step>
    </ol>
  )
}
