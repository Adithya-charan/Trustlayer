import { Empty } from './ui'

// All charts render only the data they are given. When every value is zero they say so instead of drawing filler.

export const CHART_COLORS = {
  ALLOW: '#0f766e', PARTIAL: '#2f5fb3', DENY: '#b91c1c',
  COMPLETED: '#0f766e', FAILED: '#b91c1c', SUCCESS: '#0f766e', RETRYING: '#b45309',
  HIGH: '#c2410c', MEDIUM: '#b45309', LOW: '#0f766e', CRITICAL: '#b91c1c',
}
const FALLBACK = ['#244b92', '#0f766e', '#7c8db5', '#b45309', '#6d28d9', '#475569', '#0e7490']

export function TimeBars({ series, keys, labels = {}, height = 150, emptyTitle, emptyHint, unit = 'events' }) {
  const totals = series.map((p) => keys.reduce((a, k) => a + (p[k] || 0), 0))
  const max = Math.max(...totals, 0)
  if (max === 0) return <Empty title={emptyTitle || 'No events in this period'} hint={emptyHint} />
  const W = 560, padL = 28, padB = 20, bw = (W - padL) / series.length
  const H = height
  const step = Math.max(1, Math.ceil(series.length / 7))
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H + padB}`} className="w-full" role="img" aria-label={`${unit} per day: ${series.map((p, i) => `${p.date} ${totals[i]}`).join(', ')}`}>
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={padL} x2={W} y1={H - H * f} y2={H - H * f} stroke="#e2e8f0" strokeWidth="1" />
            <text x={padL - 4} y={H - H * f + 3} textAnchor="end" fontSize="9" fill="#64748b">{Math.round(max * f)}</text>
          </g>
        ))}
        {series.map((p, i) => {
          let y = H
          return (
            <g key={p.date}>
              {keys.map((k) => {
                const h = ((p[k] || 0) / max) * H
                y -= h
                return h > 0 ? <rect key={k} x={padL + i * bw + bw * 0.15} y={y} width={bw * 0.7} height={h} fill={CHART_COLORS[k] || FALLBACK[0]} rx="1.5"><title>{`${p.date} · ${labels[k] || k}: ${p[k]}`}</title></rect> : null
              })}
              {i % step === 0 && <text x={padL + i * bw + bw / 2} y={H + 13} textAnchor="middle" fontSize="9" fill="#64748b">{p.date.slice(5)}</text>}
            </g>
          )
        })}
      </svg>
      <ul className="mt-1 flex flex-wrap gap-3 text-xs text-slate-600">
        {keys.map((k) => <li key={k} className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: CHART_COLORS[k] }} />{labels[k] || k}</li>)}
      </ul>
    </div>
  )
}

export function HBars({ data, emptyTitle = 'Nothing to show', colorFor }) {
  const rows = data.filter((d) => d.value > 0)
  const max = Math.max(...rows.map((d) => d.value), 0)
  if (!max) return <Empty title={emptyTitle} />
  return (
    <ul className="space-y-2">
      {rows.map((d, i) => (
        <li key={d.label} className="text-xs">
          <div className="mb-0.5 flex justify-between text-slate-700"><span>{d.label}</span><span className="tabular-nums font-medium">{d.value}</span></div>
          <div className="h-2 rounded-full bg-slate-100" aria-hidden><div className="h-2 rounded-full" style={{ width: `${(d.value / max) * 100}%`, background: colorFor?.(d.label) || FALLBACK[i % FALLBACK.length] }} /></div>
        </li>
      ))}
    </ul>
  )
}

export function Donut({ data, emptyTitle = 'No events in this period', size = 120 }) {
  const rows = data.filter((d) => d.value > 0)
  const total = rows.reduce((a, d) => a + d.value, 0)
  if (!total) return <Empty title={emptyTitle} />
  const r = 42, c = 2 * Math.PI * r
  let offset = 0
  return (
    <div className="flex items-center gap-4">
      <svg width={size} height={size} viewBox="0 0 100 100" role="img" aria-label={rows.map((d) => `${d.label} ${d.value}`).join(', ')}>
        <g transform="rotate(-90 50 50)">
          {rows.map((d, i) => {
            const len = (d.value / total) * c
            const el = <circle key={d.label} cx="50" cy="50" r={r} fill="none" stroke={d.color || FALLBACK[i % FALLBACK.length]} strokeWidth="14" strokeDasharray={`${len} ${c - len}`} strokeDashoffset={-offset}><title>{`${d.label}: ${d.value}`}</title></circle>
            offset += len
            return el
          })}
        </g>
        <text x="50" y="54" textAnchor="middle" fontSize="16" fontWeight="600" fill="#0f172a">{total}</text>
      </svg>
      <ul className="space-y-1 text-xs text-slate-700">
        {rows.map((d, i) => <li key={d.label} className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: d.color || FALLBACK[i % FALLBACK.length] }} />{d.label} <span className="tabular-nums font-medium">{d.value}</span></li>)}
      </ul>
    </div>
  )
}
