import { useApi } from '../lib/useApi'
import { Badge, ErrorState, Loading, PageHeader, Panel, PanelHeader } from '../components/ui'

const Row = ({ k, children }) => <div className="flex flex-wrap justify-between gap-2 border-t border-slate-100 px-5 py-3 text-sm first:border-t-0"><dt className="text-slate-500">{k}</dt><dd className="text-right font-medium text-slate-900">{children}</dd></div>

export default function Settings({ me }) {
  const { data, error, loading, reload } = useApi('/settings', [])
  return (
    <>
      <PageHeader title="Settings" description="Read-only view of the running configuration. Secrets are never shown. Change values in backend/.env and restart the backend." />
      {loading && !data && <Panel><Loading /></Panel>}
      {error && <Panel><ErrorState error={error} onRetry={reload} /></Panel>}
      {data && (
        <div className="grid gap-5 lg:grid-cols-2">
          <Panel>
            <PanelHeader title="System" />
            <dl>
              <Row k="Environment">{data.environment}</Row>
              <Row k="Backend version">{data.version}</Row>
              <Row k="Database"><Badge tone={data.database.connected ? 'ALLOW' : 'DENY'}>{data.database.connected ? 'Connected' : 'Unreachable'}</Badge></Row>
              <Row k="Configuration valid"><Badge tone={data.config_ok ? 'ALLOW' : 'DENY'}>{data.config_ok ? 'Yes' : 'Problems found'}</Badge></Row>
              <Row k="PII detector">{data.presidio_enabled ? 'Presidio + deterministic rules' : 'Deterministic rules only'}</Row>
              <Row k="n8n editor">{data.n8n_editor_url}</Row>
            </dl>
          </Panel>
          <Panel>
            <PanelHeader title="Your session" />
            <dl>
              <Row k="User">{me.username}</Row>
              <Row k="Role">{me.role}</Row>
              <Row k="Token lifetime">{data.session_minutes} minutes</Row>
            </dl>
          </Panel>
          <Panel className="lg:col-span-2">
            <PanelHeader title="Risk thresholds" subtitle="Applied per principal over a rolling window" />
            <dl className="grid sm:grid-cols-2">
              <Row k="Window">{data.risk.window_minutes} minutes</Row>
              <Row k="Restricted-access threshold">{data.risk.denied_field_threshold} requests</Row>
              <Row k="Reconstruction threshold">{data.risk.distinct_subsets_threshold} field combinations</Row>
              <Row k="Volume threshold">{data.risk.volume_threshold} requests</Row>
              <Row k="Tighten masking at score">{data.risk.elevated_score}</Row>
              <Row k="Block at score">{data.risk.block_score}</Row>
            </dl>
            <p className="border-t border-slate-100 px-5 py-3 text-xs text-slate-500">{data.retention} {data.read_only}</p>
          </Panel>
        </div>
      )}
    </>
  )
}
