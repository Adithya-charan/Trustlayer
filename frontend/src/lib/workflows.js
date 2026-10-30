// Honest workflow state derived ONLY from run reports the workflows posted to TrustLayer.
// A workflow file existing, or being scheduled in n8n, never counts as "active": only reports do.
// "Running" cannot be shown because workflows report on completion, and "not configured" cannot be told
// apart from "never ran", so both are described as "No run reported".
const UNIT = { minute: 1, hour: 60, day: 1440, week: 10080, month: 43200 }

export function intervalMinutes(schedule) {
  const m = /^Every (?:(\d+) )?(minute|hour|day|week|month)s?$/.exec(schedule || '')
  return m ? (Number(m[1] || 1)) * UNIT[m[2]] : null
}

export function workflowState(w) {
  if (!w.last_status) return { key: 'not_run', label: 'No run reported', tone: 'idle', hint: 'Not configured in n8n, or it has not run yet. TrustLayer only knows what workflows report.' }
  if (w.last_status === 'FAILED') return { key: 'failed', label: 'Last run failed', tone: 'bad', hint: 'The most recent report is a failure.' }
  if (w.last_status === 'RETRYING') return { key: 'retrying', label: 'Retrying', tone: 'warn', hint: 'The latest report says a retry is in progress.' }
  const iv = intervalMinutes(w.schedule)
  const ageMin = (Date.now() - new Date(w.last_run_at).getTime()) / 60000
  if (iv && ageMin > iv * 2.5) return { key: 'stale', label: 'Unknown', tone: 'warn', hint: 'The last success is older than 2.5 scheduled intervals, so current status is unknown.' }
  return { key: 'healthy', label: 'Last run succeeded', tone: 'ok', hint: 'The most recent report succeeded and is within its expected interval.' }
}
