import { useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { ArrowRight, Plus, Trash2, X } from 'lucide-react'
import { api } from '../lib/api'
import { useApi } from '../lib/useApi'
import { AUDITORS } from '../lib/router'
import { Badge, Button, Empty, ErrorState, Loading, Notice, PageHeader, Panel, PanelHeader, Select, Table, Td, Th, fmtTime, qs, strategyTone } from '../components/ui'

const STRATEGY_HELP = {
  ALLOW: 'Returned unchanged (never permitted for government or account IDs).',
  PARTIAL_MASK: 'Keeps a safe part: last 4 characters, initials, email domain, year, or a numeric range.',
  FULL_MASK: 'Replaced by a fixed ******** so even the length is hidden.',
  REDACT: 'Replaced by [REDACTED].',
  HASH: 'Keyed hash: stable for joins, not reversible.',
  DENY: 'Field is withheld entirely.',
}

function NewRule({ meta, onDone }) {
  const [open, setOpen] = useState(false)
  const [v, setV] = useState({ role: meta.roles[0], purpose: meta.purposes[0], category: meta.categories[0], strategy: 'FULL_MASK' })
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  async function save(e) {
    e.preventDefault(); setBusy(true); setErr(null)
    try { await api('/policies', { method: 'POST', body: { ...v, enabled: true } }); setOpen(false); onDone() }
    catch (x) { setErr(x.extra?.errors?.map((m) => m.message).join('; ') || x.message) } finally { setBusy(false) }
  }
  const set = (k) => (val) => setV((s) => ({ ...s, [k]: val }))
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild><Button size="sm"><Plus className="h-4 w-4" aria-hidden /> New rule</Button></Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-slate-900/40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-xl bg-white p-6 shadow-xl">
          <div className="flex justify-between"><Dialog.Title className="text-lg font-semibold">New policy rule</Dialog.Title><Dialog.Close aria-label="Close" className="rounded p-1 hover:bg-slate-100"><X className="h-5 w-5" /></Dialog.Close></div>
          <Dialog.Description className="mb-3 text-xs text-slate-500">One rule per role, purpose and field classification. The server validates it and records the change in the audit trail.</Dialog.Description>
          <form onSubmit={save} className="grid gap-3">
            <Select label="Role" value={v.role} onChange={set('role')} options={meta.roles} />
            <Select label="Purpose" value={v.purpose} onChange={set('purpose')} options={meta.purposes} />
            <Select label="Field classification" value={v.category} onChange={set('category')} options={meta.categories} />
            <Select label="Strategy" value={v.strategy} onChange={set('strategy')} options={meta.strategies} />
            <p className="text-xs text-slate-500">{STRATEGY_HELP[v.strategy]}</p>
            {err && <Notice tone="error">{err}</Notice>}
            <Button type="submit" loading={busy}>Create rule</Button>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

function Demonstrator({ me, meta }) {
  const roles = meta ? meta.roles : [me.role]
  const [role, setRole] = useState(me.role)
  const [purpose, setPurpose] = useState('')
  const [field, setField] = useState('pan')
  const schema = useApi('/access/schema', [])
  const purposes = meta ? meta.purposes : schema.data?.purposes || []
  const fields = schema.data?.fields.map((f) => f.name).filter((n) => n !== 'id') || []
  const [res, setRes] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)

  async function run(e) {
    e.preventDefault(); setBusy(true); setErr(null); setRes(null)
    try { setRes(await api('/policies/simulate', { method: 'POST', body: { role, purpose: purpose || purposes[0], field } })) }
    catch (x) { setErr(x) } finally { setBusy(false) }
  }
  const step = (title, body) => <div className="min-w-[8rem] flex-1 rounded-lg border border-slate-200 p-3"><p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{title}</p><div className="mt-1 text-sm">{body}</div></div>

  return (
    <Panel>
      <PanelHeader title="Policy demonstrator" subtitle="Shows how one field travels through classification, policy and masking. Uses fixed synthetic example values, never stored records." />
      <form onSubmit={run} className="flex flex-wrap items-end gap-3 px-5 py-4">
        <Select label="Role" value={role} onChange={setRole} options={roles} />
        <Select label="Purpose" value={purpose || purposes[0] || ''} onChange={setPurpose} options={purposes.length ? purposes : ['—']} />
        <Select label="Field" value={field} onChange={setField} options={fields.length ? fields : ['pan']} />
        <Button type="submit" loading={busy} disabled={!purposes.length || !fields.length}>Evaluate</Button>
        {!meta && <p className="text-xs text-slate-500">You can simulate your own role ({me.role}). Auditors can simulate any role.</p>}
      </form>
      {err && <div className="px-5 pb-4"><Notice tone="error">{err.message}</Notice></div>}
      {res && (
        <div className="space-y-3 px-5 pb-5">
          <div className="flex flex-wrap items-stretch gap-2">
            {step('1 · Original (synthetic)', <code className="break-all">{String(res.original)}</code>)}
            <ArrowRight className="mt-6 hidden h-4 w-4 text-slate-400 sm:block" aria-hidden />
            {step('2 · Classification', <><Badge>{res.category}</Badge> <Badge tone={res.sensitivity}>{res.sensitivity}</Badge></>)}
            <ArrowRight className="mt-6 hidden h-4 w-4 text-slate-400 sm:block" aria-hidden />
            {step('3 · Policy', <><code className="text-xs">{res.policy}</code><div className="mt-1"><Badge tone={strategyTone(res.strategy)}>{res.strategy}</Badge></div></>)}
            <ArrowRight className="mt-6 hidden h-4 w-4 text-slate-400 sm:block" aria-hidden />
            {step('4 · Output', res.output === null ? <span className="text-red-700">Withheld (not returned)</span> : <code className="break-all">{String(res.output)}</code>)}
          </div>
          <p className="text-sm text-slate-700"><span className="font-medium">Explanation:</span> {res.explanation} <span className="text-slate-500">{STRATEGY_HELP[res.strategy]}</span></p>
          <p className="text-xs text-slate-500">{res.note}</p>
        </div>
      )}
    </Panel>
  )
}

export default function Policies({ me, version, bump }) {
  const auditor = AUDITORS.includes(me.role)
  const [f, setF] = useState({ role: '', purpose: '', enabled: '' })
  const all = useApi(auditor ? `/policies/all${qs(f)}` : null, [version, auditor, f.role, f.purpose, f.enabled])
  const mine = useApi(!auditor ? '/policies' : null, [version, auditor])
  const [msg, setMsg] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const meta = all.data?.roles ? all.data : null
  const manage = Boolean(meta?.can_manage)

  async function act(id, fn) {
    setBusyId(id); setMsg(null)
    try { await fn(); bump(); setMsg({ tone: 'success', text: 'Change saved and recorded in the audit trail.' }) }
    catch (e) { setMsg({ tone: 'error', text: e.extra?.errors?.map((m) => m.message).join('; ') || e.message }) } finally { setBusyId(null) }
  }

  return (
    <>
      <PageHeader title="Policies & masking" description="Rules map a role, purpose and field classification to a decision and masking strategy. The backend enforces them on every request; absent or disabled rules mean deny." actions={manage && meta && <NewRule meta={meta} onDone={() => { bump(); setMsg({ tone: 'success', text: 'Rule created.' }) }} />} />
      <div className="space-y-5">
        <Panel>
          <PanelHeader title={auditor ? 'Policy rules' : 'Your policy rules'} subtitle={manage ? 'Edit strategy, enable or disable, or delete. Changes apply to the next request.' : auditor ? 'Read-only for your role. Security admins can edit.' : 'Rules that apply to your role.'} />
          {auditor && (
            <div className="flex flex-wrap gap-3 border-b border-slate-100 px-5 py-3">
              <Select label="Role" value={f.role} onChange={(v) => setF({ ...f, role: v })} options={[['', 'All'], ...(meta?.roles || [])]} />
              <Select label="Purpose" value={f.purpose} onChange={(v) => setF({ ...f, purpose: v })} options={[['', 'All'], ...(meta?.purposes || [])]} />
              <Select label="Status" value={f.enabled} onChange={(v) => setF({ ...f, enabled: v })} options={[['', 'All'], ['true', 'Enabled'], ['false', 'Disabled']]} />
            </div>
          )}
          {msg && <div className="px-5 pt-3"><Notice tone={msg.tone}>{msg.text}</Notice></div>}
          {(all.loading && auditor && !all.data) && <Loading />}
          {auditor && all.error && <ErrorState error={all.error} onRetry={all.reload} />}
          {auditor && all.data?.items?.length === 0 && <Empty title="No rules match" />}
          {auditor && all.data?.items?.length > 0 && (
            <Table caption="Policy rules">
              <thead><tr><Th>ID</Th><Th>Role</Th><Th>Purpose</Th><Th>Classification</Th><Th>Decision</Th><Th>Strategy</Th><Th>Status</Th><Th>Updated</Th>{manage && <Th>Actions</Th>}</tr></thead>
              <tbody>
                {all.data.items.map((p) => (
                  <tr key={p.id} className={p.enabled ? '' : 'bg-slate-50 text-slate-500'}>
                    <Td className="font-mono text-xs">{p.identifier}</Td><Td className="text-xs">{p.role}</Td><Td className="text-xs">{p.purpose}</Td>
                    <Td><Badge>{p.category}</Badge></Td><Td><Badge tone={p.decision}>{p.decision}</Badge></Td>
                    <Td>{manage ? (
                      <select aria-label={`Strategy for ${p.name}`} value={p.strategy} disabled={busyId === p.id} onChange={(e) => act(p.id, () => api(`/policies/${p.id}`, { method: 'PATCH', body: { strategy: e.target.value } }))} className="min-h-8 rounded-lg border border-slate-300 bg-white px-1 text-xs">
                        {all.data.strategies.map((s) => <option key={s}>{s}</option>)}
                      </select>) : <Badge tone={strategyTone(p.strategy)}>{p.strategy}</Badge>}</Td>
                    <Td><Badge tone={p.enabled ? 'ALLOW' : 'neutral'}>{p.enabled ? 'Enabled' : 'Disabled'}</Badge></Td>
                    <Td className="text-xs">{fmtTime(p.updated_at)}<span className="block text-slate-400">{p.updated_by}</span></Td>
                    {manage && <Td><span className="flex gap-1">
                      <Button size="sm" variant="outline" disabled={busyId === p.id} onClick={() => act(p.id, () => api(`/policies/${p.id}`, { method: 'PATCH', body: { enabled: !p.enabled } }))}>{p.enabled ? 'Disable' : 'Enable'}</Button>
                      <Button size="sm" variant="danger" disabled={busyId === p.id} aria-label={`Delete ${p.identifier}`} onClick={() => window.confirm(`Delete ${p.identifier} (${p.name})? Requests that relied on it will be denied.`) && act(p.id, () => api(`/policies/${p.id}`, { method: 'DELETE' }))}><Trash2 className="h-3.5 w-3.5" aria-hidden /></Button></span></Td>}
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
          {!auditor && mine.error && <ErrorState error={mine.error} onRetry={mine.reload} />}
          {!auditor && mine.data?.purposes && (mine.data.purposes.length === 0 ? <Empty title="No rules for your role" /> : (
            <div className="space-y-4 p-5">{mine.data.purposes.map((p) => (
              <div key={p.purpose}><h3 className="mb-1 text-sm font-medium">Purpose: {p.purpose}</h3>
                <div className="flex flex-wrap gap-2">{Object.entries(p.rules).map(([c, s]) => <span key={c} className="flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1 text-xs">{c} <Badge tone={strategyTone(s)}>{s}</Badge></span>)}</div></div>))}</div>
          ))}
          {meta && <p className="border-t border-slate-100 px-5 py-3 text-xs text-slate-500">{meta.note}</p>}
        </Panel>

        <Demonstrator me={me} meta={meta} />

        <Panel>
          <PanelHeader title="Masking strategies" subtitle="Originals are never modified; protection is applied to the returned copy only." />
          <dl className="grid gap-x-6 gap-y-2 p-5 text-sm sm:grid-cols-2">
            {Object.entries(STRATEGY_HELP).map(([k, v]) => <div key={k} className="flex gap-2"><dt className="w-28 shrink-0"><Badge tone={strategyTone(k)}>{k}</Badge></dt><dd className="text-slate-600">{v}</dd></div>)}
          </dl>
        </Panel>
      </div>
    </>
  )
}
