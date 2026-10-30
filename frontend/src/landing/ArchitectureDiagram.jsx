import { ArrowDown, ClipboardList, Database, EyeOff, FileSearch, GitBranch, Lock, MonitorSmartphone, SlidersHorizontal } from 'lucide-react'

// Mirrors the implemented system: one FastAPI backend (modular monolith) with scanner, policy engine,
// masking and risk, and audit logger, all persisting to Neon PostgreSQL. n8n is an optional layer that only
// calls /api/automation/*.
const NODES = [
  { id: 'ui', x: 14, y: 186, w: 170, h: 84, title: 'React Dashboard', sub: 'Vite · JWT session', icon: MonitorSmartphone, c: '#2563EB' },
  { id: 'api', x: 236, y: 186, w: 180, h: 84, title: 'FastAPI', sub: 'Auth · RBAC · rate limits', icon: Lock, c: '#7C3AED' },
  { id: 'scan', x: 492, y: 18, w: 220, h: 76, title: 'PII Scanner', sub: 'Presidio + deterministic rules', icon: FileSearch, c: '#7C3AED' },
  { id: 'policy', x: 492, y: 118, w: 220, h: 76, title: 'Policy Engine', sub: 'Role · purpose · classification', icon: SlidersHorizontal, c: '#2563EB' },
  { id: 'mask', x: 492, y: 218, w: 220, h: 76, title: 'Masking & Risk', sub: 'Strategies · risk rules · minimization', icon: EyeOff, c: '#0D9488' },
  { id: 'audit', x: 492, y: 318, w: 220, h: 76, title: 'Audit Logger', sub: 'Decisions, never values', icon: ClipboardList, c: '#16A34A' },
  { id: 'db', x: 776, y: 176, w: 172, h: 104, title: 'Neon PostgreSQL', sub: 'Fields · policies · audit · runs', icon: Database, c: '#0D9488' },
  { id: 'n8n', x: 236, y: 336, w: 180, h: 72, title: 'n8n (optional)', sub: 'Scan · alerts · reports', icon: GitBranch, c: '#D97706' },
]
const by = Object.fromEntries(NODES.map((n) => [n.id, n]))
const cy = (n) => n.y + n.h / 2
const curve = (ax, ay, bx, by2) => `M${ax} ${ay} C${(ax + bx) / 2} ${ay} ${(ax + bx) / 2} ${by2} ${bx} ${by2}`

const EDGES = [
  { d: curve(by.ui.x + by.ui.w, cy(by.ui), by.api.x, cy(by.api)), c: '#2563EB', label: 'REST /api', lx: 210, ly: 220 },
  ...['scan', 'policy', 'mask', 'audit'].map((id) => ({ d: curve(by.api.x + by.api.w, cy(by.api), by[id].x, cy(by[id])), c: by[id].c })),
  ...['scan', 'policy', 'mask', 'audit'].map((id) => ({ d: curve(by[id].x + by[id].w, cy(by[id]), by.db.x, cy(by.db)), c: by[id].c })),
  { d: `M${by.n8n.x + by.n8n.w / 2} ${by.n8n.y} L${by.api.x + by.api.w / 2} ${by.api.y + by.api.h}`, c: '#D97706', label: '/api/automation/*', lx: 340, ly: 312, dashed: true },
]

export default function ArchitectureDiagram() {
  return (
    <div>
      <div className="hidden md:block">
        <svg viewBox="0 0 962 430" className="w-full" role="img" aria-label="Architecture: the React dashboard calls FastAPI. FastAPI uses the PII scanner, policy engine, masking and risk evaluation, and audit logger, which all persist to Neon PostgreSQL. n8n is an optional layer that calls only the automation endpoints of FastAPI.">
          <defs><marker id="ad-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0 10 5 0 10z" fill="#64748B" /></marker></defs>
          {EDGES.map((e, i) => (
            <g key={i}>
              <path d={e.d} fill="none" stroke={e.c} strokeOpacity="0.18" strokeWidth="2.5" />
              <path d={e.d} fill="none" stroke={e.c} strokeOpacity="0.85" strokeWidth="1.6" markerEnd="url(#ad-arrow)" className="dash-flow animate-flow" strokeDasharray={e.dashed ? '3 7' : undefined} />
              {e.label && <text x={e.lx} y={e.ly} textAnchor="middle" fontSize="11" fill="#64748B">{e.label}</text>}
            </g>
          ))}
          {NODES.map((n) => (
            <g key={n.id} tabIndex={0} aria-label={`${n.title}: ${n.sub}`} className="group outline-none">
              <rect x={n.x} y={n.y} width={n.w} height={n.h} rx="16" fill="#fff" stroke={n.c} strokeOpacity="0.35" className="transition-all group-hover:[stroke-opacity:0.9] group-focus-visible:[stroke-opacity:0.9]" style={{ filter: 'drop-shadow(0 6px 14px rgba(15,23,42,0.07))' }} />
              <rect x={n.x} y={n.y + 14} width="4" height={n.h - 28} rx="2" fill={n.c} />
              <foreignObject x={n.x + 16} y={n.y + 8} width={n.w - 22} height={n.h - 16}>
                <div xmlns="http://www.w3.org/1999/xhtml" className="flex h-full flex-col justify-center text-left">
                  <span className="flex items-center gap-2 text-[13px] font-semibold text-body"><n.icon className="h-4 w-4 shrink-0" style={{ color: n.c }} aria-hidden="true" />{n.title}</span>
                  <span className="mt-1 text-[11px] leading-tight text-muted">{n.sub}</span>
                </div>
              </foreignObject>
            </g>
          ))}
        </svg>
      </div>

      <ol className="space-y-2 md:hidden" aria-label="Architecture flow">
        {['ui', 'api', 'scan', 'policy', 'mask', 'audit', 'db', 'n8n'].map((id, i, arr) => {
          const n = by[id]
          return (
            <li key={id}>
              <div className="rounded-xl border border-slate-200 bg-white p-3 shadow-card" style={{ borderLeft: `4px solid ${n.c}` }}>
                <p className="flex items-center gap-2 text-sm font-semibold text-body"><n.icon className="h-4 w-4" style={{ color: n.c }} aria-hidden />{n.title}</p>
                <p className="mt-0.5 text-xs text-muted">{n.sub}</p>
              </div>
              {i < arr.length - 1 && <ArrowDown className="mx-auto my-1 h-4 w-4 text-navy-500" aria-hidden />}
            </li>
          )
        })}
      </ol>
      <p className="mt-4 text-center text-xs text-muted">n8n calls only <code>/api/automation/*</code> and is not a security boundary. FastAPI enforces all access decisions.</p>
    </div>
  )
}
