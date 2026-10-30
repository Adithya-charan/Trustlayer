import { useEffect, useRef, useState } from 'react'
import { Bot, Workflow } from 'lucide-react'
import { Badge, PageHeader, cn } from '../components/ui'
import { useAssistantContext } from '../assistant/AssistantContext'
import { Composer, Message, Typing } from '../assistant/AssistantDock'
import VoiceStage from '../assistant/VoiceStage'

const AGENT = { idle: 'Idle', listening: 'Listening', processing: 'Thinking', speaking: 'Speaking' }

// The avatar is the main focus (about 75% of the desktop workspace); the conversation, agent activity and the typed composer sit in a
// narrower side panel that can be hidden. On tablet and phone the panel stacks under the avatar. The panel is the same conversation as the
// "Ask AI" dock: typed, spoken and confirmed turns share one history and one set of backend permissions, and every typed reply is also
// handed to the avatar by the backend while a live session is running.
export default function VoiceAssistant() {
  const { assistant, live } = useAssistantContext()
  const workspace = useRef(null)
  const list = useRef(null)
  const input = useRef(null)
  const [panelOpen, setPanelOpen] = useState(true)
  useEffect(() => { if (list.current) list.current.scrollTop = list.current.scrollHeight }, [assistant.messages, assistant.busy, panelOpen])
  const off = assistant.status.state !== 'online'
  const automation = assistant.status.workflowExecution

  return (
    <>
      <PageHeader title="Voice Assistant" description="Talk or type to the TrustLayer operator. The backend checks your permissions and runs only approved tools, and the avatar speaks the answer while the same text appears in the conversation panel." />
      <div ref={workspace} className={cn('group/ws grid gap-4 [&:fullscreen]:content-start [&:fullscreen]:overflow-auto [&:fullscreen]:bg-mist [&:fullscreen]:p-3', panelOpen ? 'lg:grid-cols-[minmax(0,3fr)_minmax(18rem,1fr)]' : 'lg:grid-cols-1')}>
        <VoiceStage workspaceRef={workspace} panel={{ open: panelOpen, toggle: () => setPanelOpen((o) => !o), id: 'conversation-panel' }} />
        <aside id="conversation-panel" aria-label="Conversation" hidden={!panelOpen}
          className="flex min-h-[22rem] max-h-[70dvh] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white lg:max-h-[calc(100dvh-9rem)] group-[:fullscreen]/ws:max-h-[calc(100dvh-2rem)]">
          <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-slate-200 px-4 py-3">
            <h2 className="text-sm font-semibold text-slate-900">Conversation</h2>
            <span className="ml-auto flex flex-wrap items-center gap-1.5 text-xs">
              <Badge tone={live.connection === 'connected' ? 'good' : 'neutral'}>{live.connection === 'connected' ? `Avatar: ${AGENT[live.agentState]}` : 'Avatar off'}</Badge>
              <Badge tone={automation ? 'good' : 'neutral'}><Workflow className="mr-1 inline h-3 w-3" aria-hidden />{automation ? 'n8n workflows configured' : 'n8n not configured'}</Badge>
            </span>
          </header>
          {assistant.messages.length === 0 ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 px-5 text-center text-sm text-slate-600">
              <Bot className="h-8 w-8 text-navy-600" aria-hidden />
              <p className="font-medium text-slate-900">No conversation yet</p>
              <p className="text-xs">Start the conversation and speak, or type below. Requests, results and the avatar's spoken replies appear here as text.</p>
            </div>
          ) : (
            <div ref={list} className="flex-1 overflow-y-auto px-4 py-4">
              <ol role="log" aria-live="polite" aria-label="Conversation messages" className="space-y-4">
                {assistant.messages.map((m) => <Message key={m.id} m={m} busy={assistant.busy} onConfirm={assistant.confirm} onCancel={assistant.cancel} />)}
                {assistant.busy && <li><Typing /></li>}
              </ol>
            </div>
          )}
          <Composer a={assistant} disabled={off} inputRef={input} id="voice-page-input" />
        </aside>
      </div>
    </>
  )
}
