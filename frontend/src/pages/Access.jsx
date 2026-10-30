import { Fragment, useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, SlidersHorizontal } from 'lucide-react'
import { useApi } from '../lib/useApi'
import { Badge, Button, ErrorState, Loading, PageHeader, Panel, PanelHeader, Table, Td, Th, fmtTime } from '../components/ui'
import { SourceBadge, Strategy, TAG_TONE, personName } from '../components/b1'

const ROLE_NOTE = { Admin: 'Sees real values; can scan, review classifications, edit policies and read the audit trail.', Support: 'Sees partial masks, e.g. 4111-XXXX-XXXX-1111.', Analyst: 'Sees redactions and keyed hashes; the most restricted identifiers are withheld.' }

function Effective({ username, version }) {
  const { data, error, loading, reload } = useApi(`/b1/policy/users/${encodeURIComponent(username)}`, [username, version])
  const kinds = useApi('/b1/policy')
  if (loading && !data) return <Loading rows={2} label="Loading effective policy" />
  if (error) return <ErrorState error={error} onRetry={reload} />
  const tag = Object.fromEntries((kinds.data?.kinds || []).map((k) => [k.kind, k.tag]))
  return (
    <Table caption={`Effective policy of ${username}`}>
      <thead><tr><Th>Kind of data</Th><Th>Classification</Th><Th>Effective</Th><Th>Source</Th><Th>Built-in default</Th></tr></thead>
      <tbody>{Object.entries(data.policy).map(([k, v]) => (
        <tr key={k}><Td className="text-xs">{k}</Td><Td>{tag[k] && <Badge tone={TAG_TONE[tag[k]]}>{tag[k]}</Badge>}</Td><Td><Strategy s={v.strategy} /></Td>
          <Td>{v.source === 'default' ? <span className="text-xs text-slate-500">built-in</span> : <SourceBadge source={v.source} />}</Td><Td><span className="text-xs text-slate-500">{v.default.toLowerCase()}</span></Td></tr>
      ))}</tbody>
    </Table>
  )
}

export default function Access({ go, params, version }) {
  const { data, error, loading, reload } = useApi('/b1/users', [version])
  const [open, setOpen] = useState(null)
  const want = params.get('user')
  useEffect(() => { if (want) setOpen(want) }, [want])
  const users = data?.users || []
  const groups = ['Admin', 'Support', 'Analyst']

  return (
    <>
      <PageHeader title="Users & Access" description="The accounts that can use the data protection engine, their role, and the masking each one actually receives (built-in defaults plus anything an Admin has edited). Sign-in and passwords use the existing account system." />
      <div className="space-y-5">
        {loading && !data ? <Panel><Loading label="Loading users" /></Panel> : error ? <Panel><ErrorState error={error} onRetry={reload} /></Panel> : groups.map((g) => {
          const rows = users.filter((u) => u.role === g)
          if (!rows.length) return null
          return (
            <Panel key={g}>
              <PanelHeader title={`${g} (${rows.length})`} subtitle={ROLE_NOTE[g]} />
              <Table caption={`${g} users`}>
                <thead><tr><Th>User</Th><Th>Account</Th><Th>Edited policies</Th><Th>Last activity</Th><Th>Policy</Th></tr></thead>
                <tbody>{rows.map((u) => (
                  <Fragment key={u.username}>
                    <tr>
                      <Td><button type="button" onClick={() => setOpen(open === u.username ? null : u.username)} aria-expanded={open === u.username} className="inline-flex items-center gap-2 text-left font-medium text-slate-900">
                        {open === u.username ? <ChevronDown className="h-4 w-4" aria-hidden /> : <ChevronRight className="h-4 w-4" aria-hidden />}{personName(u)}</button></Td>
                      <Td className="text-xs text-slate-600"><span className="font-mono">{u.username}</span>{u.account_role !== u.role && <span className="ml-1">({u.account_role})</span>}</Td>
                      <Td>{u.custom_policies ? <Badge tone="info">{u.custom_policies} edited</Badge> : <span className="text-xs text-slate-500">built-in</span>}</Td>
                      <Td className="text-xs text-slate-600">{u.last_activity ? fmtTime(u.last_activity) : 'none recorded'}</Td>
                      <Td>{u.editable ? <Button size="sm" variant="outline" onClick={() => go(`policies?user=${u.username}`)}><SlidersHorizontal className="h-3.5 w-3.5" aria-hidden /> Edit</Button> : <span className="text-xs text-slate-500">always full access</span>}</Td>
                    </tr>
                    {open === u.username && <tr><td colSpan={5} className="border-t border-slate-100 bg-slate-50/50 p-0">{u.editable ? <Effective username={u.username} version={version} /> : <p className="px-5 py-4 text-sm text-slate-600">Admin accounts always receive real values; their policy cannot be restricted or edited.</p>}</td></tr>}
                  </Fragment>
                ))}</tbody>
              </Table>
            </Panel>
          )
        })}
      </div>
    </>
  )
}
