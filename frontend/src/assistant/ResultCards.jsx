import { useEffect, useState } from 'react'
import { ExternalLink, Loader2 } from 'lucide-react'
import { Badge, fmtTime } from '../components/ui'
import { api } from '../lib/api'

// Structured cards. Every value rendered here comes from the backend response; nothing is composed from model text.
const Card = ({ title, meta, children }) => (
  <div className="mt-2 overflow-hidden rounded-xl border border-slate-200 bg-white text-xs shadow-card">
    <div className="flex items-center justify-between gap-2 border-b border-slate-100 bg-slate-50/70 px-3 py-2">
      <p className="font-semibold text-slate-800">{title}</p>
      {meta && <p className="text-slate-500">{meta}</p>}
    </div>
    {children}
  </div>
)
const Row = ({ children }) => <li className="space-y-1 border-t border-slate-100 px-3 py-2 first:border-t-0">{children}</li>
const None = ({ children }) => <p className="px-3 py-4 text-center text-slate-500">{children}</p>

function SecurityEvents({ r }) {
  return (
    <Card title={`Security events${r.severity ? ` · ${r.severity}` : ''}`} meta={`${r.items.length} of ${r.total}`}>
      {r.items.length === 0 ? <None>No security events match.</None> : (
        <ul>{r.items.map((e) => (
          <Row key={e.id}>
            <div className="flex flex-wrap items-center gap-1.5"><Badge tone={e.severity}>{e.severity}</Badge><span className="font-medium text-slate-800">{e.rule}</span></div>
            <p className="text-slate-600">{e.actor} · {fmtTime(e.ts)} · response: {e.response}</p>
          </Row>
        ))}</ul>
      )}
    </Card>
  )
}

function Scans({ r }) {
  return (
    <Card title="Recent scans" meta={`${r.items.length} shown`}>
      {r.items.length === 0 ? <None>No scans have been run yet.</None> : (
        <ul>{r.items.map((s) => (
          <Row key={s.id}>
            <div className="flex flex-wrap items-center gap-1.5"><Badge tone={s.status}>{s.status}</Badge><span className="text-slate-800">{s.sensitive_found}/{s.fields_scanned} sensitive fields</span></div>
            <p className="text-slate-600">{s.source} · {s.triggered_by} · {fmtTime(s.finished_at || s.started_at)}</p>
          </Row>
        ))}</ul>
      )}
    </Card>
  )
}

function ScanStarted({ r }) {
  const s = r.scan
  return (
    <Card title="Scan result (reported by the server)">
      <div className="space-y-1 px-3 py-2">
        <div className="flex flex-wrap items-center gap-1.5"><Badge tone={s.status}>{s.status}</Badge><span className="text-slate-800">{s.sensitive_found}/{s.fields_scanned} sensitive fields</span></div>
        <p className="text-slate-600">{s.source} · {fmtTime(s.finished_at || s.started_at)}</p>
        {s.audit_request_id && <p className="font-mono text-[11px] text-slate-500">audit {s.audit_request_id.slice(0, 8)}…</p>}
        {s.error && <p className="text-red-700">{s.error}</p>}
      </div>
    </Card>
  )
}

function Automation({ r }) {
  return (
    <Card title="Automation workflows" meta="from stored run reports">
      <ul>{r.workflows.map((w) => (
        <Row key={w.key}>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-medium text-slate-800">{w.name}</span>
            {w.last_status ? <Badge tone={w.last_status}>{w.last_status}</Badge> : <Badge tone="UNKNOWN">No run reported</Badge>}
          </div>
          <p className="text-slate-600">{w.schedule} · last run {fmtTime(w.last_run_at)} · {w.success_count} ok / {w.failure_count} failed</p>
        </Row>
      ))}</ul>
      <p className="border-t border-slate-100 px-3 py-2 text-slate-500">
        Status only. The assistant cannot start these workflows. <a className="inline-flex items-center gap-1 font-medium text-navy-700 underline" href={r.editor_url} target="_blank" rel="noreferrer">Open n8n <ExternalLink className="h-3 w-3" aria-hidden /></a>
      </p>
    </Card>
  )
}

// Policy changes, access history, denied attempts: every row is an audit-trail event the server read for this question.
function AuditAnswer({ r }) {
  return (
    <Card title="From the audit trail" meta={`${r.items.length} shown`}>
      {r.items.length === 0 ? <None>Nothing matches.</None> : (
        <ul>{r.items.map((e, i) => (
          <Row key={e.id ?? i}>
            <div className="flex flex-wrap items-center gap-1.5"><Badge tone={e.operation === 'b1_access_denied' ? 'DENY' : e.decision}>{e.operation === 'b1_access_denied' ? 'DENIED' : e.decision}</Badge><span className="font-medium text-slate-800">{e.actor_name} ({e.role}) · {e.action}</span></div>
            <p className="text-slate-700">{e.change ? `${e.change.subject} · ${e.change.kind}: ${e.change.old} → ${e.change.new}` : e.result}</p>
            {e.why?.[0] && <p className="text-slate-500">Why: {e.why[0]}</p>}
            <p className="font-mono text-[11px] text-slate-400">{fmtTime(e.ts)} · {e.policy}</p>
          </Row>
        ))}</ul>
      )}
    </Card>
  )
}

const PageHelp = ({ r }) => <Card title="About this page"><p className="px-3 py-2 text-slate-700">{r.text}</p></Card>

// n8n answering "started" is not success. This card shows only what the workflow itself reported to TrustLayer after it was started.
function WorkflowTriggered({ r }) {
  const [state, setState] = useState({ state: 'pending' })
  const [gaveUp, setGaveUp] = useState(false)
  useEffect(() => {
    let stop = false
    let tries = 0
    const poll = async () => {
      if (stop) return
      try {
        const s = await api(`/assistant/workflow-status?workflow=${encodeURIComponent(r.workflow)}&since=${encodeURIComponent(r.triggered_at)}`)
        if (stop) return
        setState(s)
        if (s.state !== 'pending') return
      } catch (e) { if (!stop) setState({ state: 'error', detail: e.message }); return }
      if (++tries >= 20) { setGaveUp(true); return } // ~60 s
      setTimeout(poll, 3000)
    }
    poll()
    return () => { stop = true }
  }, [r.workflow, r.triggered_at])
  const done = state.state !== 'pending'
  return (
    <Card title={`n8n: ${r.name}`} meta={fmtTime(r.triggered_at)}>
      <div className="space-y-1 px-3 py-2">
        <p className="text-slate-700">n8n accepted the request and started the workflow.</p>
        {!done && !gaveUp && <p className="flex items-center gap-1.5 text-slate-600"><Loader2 className="h-3 w-3 animate-spin" aria-hidden />Waiting for the workflow to report its result…</p>}
        {!done && gaveUp && <p className="text-amber-800">No result has been reported yet. It may still be running; check the Automation page. Nothing is assumed.</p>}
        {done && state.state !== 'error' && <div className="flex flex-wrap items-center gap-1.5"><Badge tone={state.state}>{state.state}</Badge><span className="text-slate-700">{state.detail}</span></div>}
        {state.state === 'error' && <p className="text-red-700">Could not read the workflow status: {state.detail}</p>}
      </div>
    </Card>
  )
}

const KINDS = { security_events: SecurityEvents, scans: Scans, scan_started: ScanStarted, automation: Automation, page_help: PageHelp, audit_answer: AuditAnswer, workflow_triggered: WorkflowTriggered }

export default function ResultCard({ result }) {
  const View = result && KINDS[result.kind]
  return View ? <View r={result} /> : null
}
