import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { Badge, ErrorState, Loading, fmtTime } from './ui'
import { useApi } from '../lib/useApi'

export default function TraceDialog({ requestId, onClose }) {
  const { data, error, loading, reload } = useApi(requestId ? `/decisions/${requestId}` : null, [requestId])
  return (
    <Dialog.Root open={Boolean(requestId)} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-navy-900/40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[85vh] w-[min(40rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl bg-white p-6 shadow-xl">
          <div className="flex items-start justify-between gap-4">
            <div>
              <Dialog.Title className="text-lg font-semibold text-navy-900">Decision trace</Dialog.Title>
              <Dialog.Description className="text-sm text-slate-600">Why this request was allowed, protected or denied. No data values are stored here.</Dialog.Description>
            </div>
            <Dialog.Close className="rounded-lg p-1 text-slate-500 hover:bg-navy-50" aria-label="Close"><X className="h-5 w-5" /></Dialog.Close>
          </div>
          <div className="mt-4 space-y-4 text-sm">
            {loading && <Loading label="Loading decision trace" />}
            {error && <ErrorState error={error} onRetry={reload} />}
            {data && requestId && (
              <>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
                  <dt className="text-slate-500">Decision</dt><dd><Badge tone={data.decision}>{data.decision}</Badge></dd>
                  <dt className="text-slate-500">Actor / role</dt><dd>{data.actor} · {data.role}</dd>
                  <dt className="text-slate-500">Operation</dt><dd>{data.operation}</dd>
                  <dt className="text-slate-500">Declared purpose</dt><dd>{data.purpose}</dd>
                  <dt className="text-slate-500">Policy evaluated</dt><dd>{data.policy}</dd>
                  <dt className="text-slate-500">Time</dt><dd>{fmtTime(data.ts)}</dd>
                  <dt className="text-slate-500">Request ID</dt><dd className="break-all font-mono text-xs">{data.request_id}</dd>
                </dl>
                <p className="rounded-xl bg-navy-50 p-3 text-navy-900"><span className="font-medium">Reason: </span>{data.reason}</p>
                <div>
                  <h3 className="mb-1 font-medium text-navy-900">Field handling</h3>
                  {Object.keys(data.fields).length === 0 ? <p className="text-slate-500">No fields involved.</p> : (
                    <ul className="divide-y divide-navy-100 rounded-xl border border-navy-100">
                      {Object.entries(data.fields).map(([f, v]) => (
                        <li key={f} className="flex items-center justify-between gap-2 px-3 py-2">
                          <span className="font-mono text-xs">{f}</span>
                          <span className="flex items-center gap-2"><Badge>{v.category}</Badge><Badge tone={v.strategy === 'DENY' ? 'DENY' : v.strategy === 'ALLOW' ? 'ALLOW' : 'PARTIAL'}>{v.strategy}</Badge></span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div>
                  <h3 className="mb-1 font-medium text-navy-900">Risk assessment</h3>
                  <p>Score {data.risk_score}{data.risk_response ? ` · response: ${data.risk_response}` : ' · no action needed'}</p>
                  {data.risk_signals.length > 0 && (
                    <ul className="mt-1 list-disc pl-5 text-slate-700">{data.risk_signals.map((s, i) => <li key={i}>{s.rule}: {s.detail}</li>)}</ul>
                  )}
                </div>
              </>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
