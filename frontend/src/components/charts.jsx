import { useState } from 'react'
import { motion } from 'framer-motion'
import { Empty } from './ui'

// Charts render only the data they are given. When every value is zero they say so instead of drawing filler.
// Colour meaning: green = allowed/protected, blue = masked, amber = elevated, rose = blocked/critical, violet = analytical.
export const CHART_COLORS = {
  ALLOW: '#16A34A', PARTIAL: '#2563EB', DENY: '#E11D48',
  COMPLETED: '#16A34A', FAILED: '#E11D48', SUCCESS: '#16A34A', RETRYING: '#D97706',
  HIGH: '#E11D48', MEDIUM: '#D97706', LOW: '#16A34A', CRITICAL: '#BE123C',
}
const FALLBACK = ['#2563EB', '#7C3AED', '#0D9488', '#D97706', '#E11D48', '#16A34A', '#64748B']

export function TimeBars({ series, keys, labels = {}, height = 150, emptyTitle, emptyHint, unit = 'events' }) {
  const [hover, setHover] = useState(null)
  const totals = series.map((p) => keys.reduce((a, k) => a + (p[k] || 0), 0))
  const max = Math.max(...totals, 0)
  if (max === 0) return <Empty title={emptyTitle || 'No events in this period'} hint={emptyHint} />
  const W = 560, padL = 28, padB = 20, bw = (W - padL) / series.length
  const H = height
  const step = Math.max(1, Math.ceil(series.length / 7))
  const hp = hover != null ? series[hover] : null
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H + padB}`} className="w-full" role="img" aria-label={`${unit} per day. ${series.filter((p, i) => totals[i] > 0).map((p) => `${p.date}: ${keys.map((k) => `${labels[k] || k} ${p[k] || 0}`).join(', ')}`).join('; ')}`}>
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={padL} x2={W} y1={H - H * f} y2={H - H * f} stroke="#E2E8F0" strokeWidth="1" strokeDasharray={f ? '3 4' : undefined} />
            <text x={padL - 4} y={H - H * f + 3} textAnchor="end" fontSize="9" fill="#64748B">{Math.round(max * f)}</text>
          </g>
        ))}
        {series.map((p, i) => {
          let y = H
          return (
            <g key={p.date} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={padL + i * bw} y={0} width={bw} height={H} fill={hover === i ? 'rgba(71,118,255,0.07)' : 'transparent'} />
              {keys.map((k) => {
                const h = ((p[k] || 0) / max) * H
                y -= h
                return h > 0 ? <motion.rect key={k} x={padL + i * bw + bw * 0.18} y={y} width={bw * 0.64} height={h} fill={CHART_COLORS[k] || FALLBACK[0]} rx="2" initial={{ scaleY: 0 }} animate={{ scaleY: 1 }} transition={{ duration: 0.45, delay: i * 0.015 }} style={{ transformBox: 'fill-box', transformOrigin: 'bottom' }} /> : null
              })}
              {i % step === 0 && <text x={padL + i * bw + bw / 2} y={H + 13} textAnchor="middle" fontSize="9" fill="#64748B">{p.date.slice(5)}</text>}
            </g>
          )
        })}
      </svg>
      {hp && (
        <div role="status" className="pointer-events-none absolute top-0 z-10 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-lift" style={{ left: `${Math.min(70, Math.max(0, ((padL + hover * bw) / W) * 100))}%` }}>
          <p className="font-semibold text-body">{hp.date}</p>
          {keys.map((k) => <p key={k} className="flex items-center gap-1.5 text-muted"><span className="h-2 w-2 rounded-sm" style={{ background: CHART_COLORS[k] }} />{labels[k] || k}: <b className="text-body">{hp[k] || 0}</b></p>)}
        </div>
      )}
      <ul className="mt-1 flex flex-wrap gap-3 text-xs text-muted">
        {keys.map((k) => <li key={k} className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: CHART_COLORS[k] }} />{labels[k] || k}</li>)}
      </ul>
    </div>
  )
}

export function HBars({ data, emptyTitle = 'Nothing to show', colorFor }) {
  const rows = data.filter((d) => d.value > 0)
  const max = Math.max(...rows.map((d) => d.value), 0)
  if (!max) return <Empty title={emptyTitle} />
  return (
    <ul className="space-y-3">
      {rows.map((d, i) => {
        const color = colorFor?.(d.label) || FALLBACK[i % FALLBACK.length]
        return (
          <li key={d.label} className="text-xs" title={`${d.label}: ${d.value}`}>
            <div className="mb-1 flex justify-between text-slate-700"><span>{d.label}</span><span className="font-semibold tabular-nums text-body">{d.value}</span></div>
            <div className="h-2 rounded-full bg-slate-100" aria-hidden><div className="h-2 rounded-full transition-[width] duration-500" style={{ width: `${(d.value / max) * 100}%`, background: `linear-gradient(90deg, ${color}, ${color}cc)` }} /></div>
          </li>
        )
      })}
    </ul>
  )
}

export function Donut({ data, emptyTitle = 'No events in this period', size = 128 }) {
  const [hover, setHover] = useState(null)
  const rows = data.filter((d) => d.value > 0)
  const total = rows.reduce((a, d) => a + d.value, 0)
  if (!total) return <Empty title={emptyTitle} />
  const r = 42, c = 2 * Math.PI * r
  let offset = 0
  const h = hover != null ? rows[hover] : null
  return (
    <div className="flex flex-wrap items-center gap-5">
      <svg width={size} height={size} viewBox="0 0 100 100" role="img" aria-label={rows.map((d) => `${d.label} ${d.value}`).join(', ')}>
        <g transform="rotate(-90 50 50)">
          {rows.map((d, i) => {
            const len = (d.value / total) * c
            const el = <circle key={d.label} cx="50" cy="50" r={r} fill="none" stroke={d.color || FALLBACK[i % FALLBACK.length]} strokeWidth={hover === i ? 16 : 13} strokeDasharray={`${len - 1} ${c - len + 1}`} strokeDashoffset={-offset} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} className="transition-[stroke-width] duration-150" />
            offset += len
            return el
          })}
        </g>
        <text x="50" y="49" textAnchor="middle" fontSize="17" fontWeight="600" fill="#172033">{h ? h.value : total}</text>
        <text x="50" y="62" textAnchor="middle" fontSize="7" fill="#64748B">{h ? h.label : 'total'}</text>
      </svg>
      <ul className="space-y-1.5 text-xs text-slate-700">
        {rows.map((d, i) => <li key={d.label} className="flex items-center gap-2" onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}><span className="h-2.5 w-2.5 rounded-sm" style={{ background: d.color || FALLBACK[i % FALLBACK.length] }} />{d.label} <span className="font-semibold tabular-nums text-body">{d.value}</span></li>)}
      </ul>
    </div>
  )
}
