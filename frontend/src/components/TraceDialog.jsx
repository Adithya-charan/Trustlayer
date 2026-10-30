import * as Dialog from '@radix-ui/react-dialog'
import { AnimatePresence, motion } from 'framer-motion'
import { X } from 'lucide-react'
import { Badge, ErrorState, Loading } from './ui'
import DecisionTimeline from './DecisionTimeline'
import { useApi } from '../lib/useApi'
import { useFocusReturn } from '../lib/useFocusReturn'

export default function TraceDialog({ requestId, onClose }) {
  const { data, error, loading, reload } = useApi(requestId ? `/decisions/${requestId}` : null, [requestId])
  const returnFocus = useFocusReturn(Boolean(requestId))
  return (
    <Dialog.Root open={Boolean(requestId)} onOpenChange={(o) => !o && onClose()}>
      <AnimatePresence>
        {requestId && (
          <Dialog.Portal forceMount>
            <Dialog.Overlay asChild forceMount><motion.div className="fixed inset-0 z-40 bg-slate-200/70 backdrop-blur-sm" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} /></Dialog.Overlay>
            <Dialog.Content asChild forceMount onCloseAutoFocus={returnFocus}>
              <div className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center p-3">
              <motion.div initial={{ opacity: 0, y: 16, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 8 }} transition={{ duration: 0.18 }}
                className="pointer-events-auto max-h-[88vh] w-full max-w-xl overflow-y-auto rounded-2xl bg-white p-5 shadow-2xl sm:p-7">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <Dialog.Title className="text-lg font-semibold text-body">Decision trace</Dialog.Title>
                    <Dialog.Description className="text-sm text-muted">Why this request was allowed, protected or denied. No data values are stored or shown.</Dialog.Description>
                  </div>
                  <Dialog.Close className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100" aria-label="Close"><X className="h-5 w-5" /></Dialog.Close>
                </div>
                <div className="mt-5">
                  {loading && !data && <Loading label="Loading decision trace" />}
                  {error && <ErrorState error={error} onRetry={reload} className="m-0" />}
                  {data && <><div className="mb-4 flex flex-wrap items-center gap-2"><Badge tone={data.decision}>{data.decision === 'PARTIAL' ? 'MASKED' : data.decision}</Badge><span className="text-xs text-muted">{data.policy}</span></div><DecisionTimeline data={data} /></>}
                </div>
              </motion.div>
              </div>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  )
}
