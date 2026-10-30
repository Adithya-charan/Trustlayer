import { motion } from 'framer-motion'
import { CountUp } from './brand'
import { Badge, Empty, ErrorState, Loading, Pager, Table, Td, Th, cn } from './ui'

const ACCENTS = {
  blue: { bar: 'from-blue-500 to-blue-400', icon: 'bg-blue-50 text-blue-600' },
  violet: { bar: 'from-violet-500 to-violet-400', icon: 'bg-violet-50 text-violet-600' },
  emerald: { bar: 'from-green-500 to-green-400', icon: 'bg-green-50 text-green-600' },
  amber: { bar: 'from-amber-500 to-amber-400', icon: 'bg-amber-50 text-amber-600' },
  rose: { bar: 'from-rose-500 to-rose-400', icon: 'bg-rose-50 text-rose-600' },
  cyan: { bar: 'from-teal-500 to-teal-400', icon: 'bg-teal-50 text-teal-600' },
}

// Metric card: shows only numbers the backend supplied. `value` may be a string (e.g. "13 / 14") or a number (animated once).
export function MetricCard({ label, value, sub, icon: Icon, accent = 'blue', delay = 0, loading }) {
  const a = ACCENTS[accent]
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, delay }} whileHover={{ y: -2 }}
      className="group relative overflow-hidden rounded-2xl border border-slate-200/80 bg-white p-5 shadow-card transition-shadow hover:shadow-lift">
      <span className={cn('absolute inset-x-0 top-0 h-1 bg-gradient-to-r', a.bar)} aria-hidden />
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted">{label}</p>
        {Icon && <span className={cn('flex h-9 w-9 items-center justify-center rounded-xl', a.icon)}><Icon className="h-[18px] w-[18px]" aria-hidden /></span>}
      </div>
      <p className="mt-3 text-3xl font-semibold tabular-nums tracking-tight text-body">{loading ? <span className="inline-block h-8 w-16 animate-pulse rounded bg-slate-100" /> : <CountUp value={value} />}</p>
      {sub && <p className="mt-1 text-xs text-muted">{sub}</p>}
    </motion.div>
  )
}

// Generic table: columns = [{ key, header, render?, className? }]. Handles loading, error, empty and optional pagination.
export function DataTable({ caption, columns, rows, rowKey, loading, error, onRetry, empty, onRowClick, pager }) {
  if (loading && !rows) return <Loading label={`Loading ${caption}`} />
  if (error) return <ErrorState error={error} onRetry={onRetry} />
  if (rows && rows.length === 0) return empty || <Empty title="Nothing to show" />
  if (!rows) return null
  return (
    <>
      <Table caption={caption}>
        <thead><tr>{columns.map((c) => <Th key={c.key} className={c.thClass}>{c.header}</Th>)}</tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={rowKey(r)} className={onRowClick ? 'cursor-pointer' : ''} onClick={onRowClick ? () => onRowClick(r) : undefined}>
              {columns.map((c) => <Td key={c.key} className={c.className}>{c.render ? c.render(r) : r[c.key]}</Td>)}
            </tr>
          ))}
        </tbody>
      </Table>
      {pager && <Pager label={`${caption} pagination`} {...pager} />}
    </>
  )
}

export { Badge }
