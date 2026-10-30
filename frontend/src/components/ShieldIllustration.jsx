import { useId } from 'react'
import { cn } from './ui'

// Light, restrained security illustration: a gradient shield with slowly flowing rings and four data "tokens".
// Pure SVG; the rings stop moving under prefers-reduced-motion (see index.css).
export default function ShieldIllustration({ className }) {
  const uid = useId().replace(/:/g, '')
  return (
    <svg viewBox="0 0 400 400" className={cn('h-full w-full', className)} role="img" aria-label="Illustration of a shield protecting data fields">
      <defs>
        <linearGradient id={`sh-${uid}`} x1="140" y1="90" x2="260" y2="310" gradientUnits="userSpaceOnUse"><stop stopColor="#2563EB" /><stop offset="1" stopColor="#7C3AED" /></linearGradient>
        <radialGradient id={`gl-${uid}`} cx="50%" cy="50%" r="50%"><stop stopColor="#2563EB" stopOpacity="0.16" /><stop offset="0.6" stopColor="#7C3AED" stopOpacity="0.08" /><stop offset="1" stopColor="#7C3AED" stopOpacity="0" /></radialGradient>
        <filter id={`ds-${uid}`} x="-20%" y="-20%" width="140%" height="150%"><feDropShadow dx="0" dy="10" stdDeviation="10" floodColor="#2563EB" floodOpacity="0.28" /></filter>
      </defs>
      <circle cx="200" cy="200" r="190" fill={`url(#gl-${uid})`} />
      <circle cx="200" cy="200" r="150" fill="none" stroke="#BFD6FD" strokeWidth="1.5" className="dash-flow animate-flow" />
      <circle cx="200" cy="200" r="118" fill="none" stroke="#DDD6FE" strokeWidth="1.5" strokeDasharray="2 8" />
      {/* tokens */}
      {[[200, 50, '#7C3AED', 'ID'], [350, 200, '#2563EB', '***'], [200, 350, '#0D9488', '#'], [50, 200, '#16A34A', '✓']].map(([x, y, c, t]) => (
        <g key={`${x}-${y}`}>
          <circle cx={x} cy={y} r="19" fill="#fff" stroke={c} strokeOpacity="0.35" />
          <text x={x} y={y + 5} textAnchor="middle" fontSize="13" fontWeight="700" fill={c}>{t}</text>
        </g>
      ))}
      <g filter={`url(#ds-${uid})`}>
        <path d="M200 112 140 136v54c0 40 26 74 60 90 34-16 60-50 60-90v-54L200 112Z" fill={`url(#sh-${uid})`} />
      </g>
      <path d="M200 112 140 136v54c0 40 26 74 60 90V112Z" fill="#fff" opacity="0.14" />
      <rect x="176" y="178" width="48" height="38" rx="8" fill="#fff" />
      <path d="M186 178v-10a14 14 0 0 1 28 0v10" fill="none" stroke="#fff" strokeWidth="7" strokeLinecap="round" />
      <circle cx="200" cy="196" r="5.5" fill="#2563EB" />
      <rect x="198" y="198" width="4" height="10" rx="2" fill="#2563EB" />
    </svg>
  )
}
