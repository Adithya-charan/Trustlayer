import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, AudioLines, Bot, Loader2, Maximize2, Mic, MicOff, Minimize2, PanelRightClose, PanelRightOpen, PhoneOff } from 'lucide-react'
import { Button, Notice, cn } from '../components/ui'
import { useAssistantContext } from './AssistantContext'

const CONNECTION = {
  idle: ['bg-slate-400', 'Not started'], connecting: ['bg-amber-500', 'Connecting'], connected: ['bg-emerald-500', 'Connected'],
  reconnecting: ['bg-amber-500', 'Reconnecting'], disconnected: ['bg-slate-400', 'Disconnected'], error: ['bg-red-500', 'Error'],
}
const AGENT = { idle: 'Idle', listening: 'Listening', processing: 'Thinking', speaking: 'Speaking' }

// The avatar video (Tavus, rendered in the LiveKit room) with connection and assistant states and the Start / End / mute / fullscreen controls.
// `workspaceRef` is what fullscreen expands (the page passes its whole workspace so the conversation stays visible); `panel` adds the
// show/hide conversation button. The video is never stretched or cropped: it keeps the track's own aspect ratio and letterboxes.
export default function VoiceStage({ compact = false, workspaceRef, panel }) {
  const { assistant, live } = useAssistantContext()
  const section = useRef(null)
  const video = useRef(null)
  const [fullscreen, setFullscreen] = useState(false)
  const ready = Boolean(assistant.status.voice?.realtime_audio)
  const [dot, label] = CONNECTION[live.connection]
  const connected = live.connection === 'connected'
  const canFullscreen = !compact && typeof document !== 'undefined' && document.fullscreenEnabled

  useEffect(() => {
    const el = video.current
    if (!el || !live.videoTrack) return undefined
    live.videoTrack.attach(el)
    return () => { live.videoTrack?.detach(el) }
  }, [live.videoTrack])

  useEffect(() => {
    const sync = () => setFullscreen(Boolean(document.fullscreenElement))
    document.addEventListener('fullscreenchange', sync)
    return () => document.removeEventListener('fullscreenchange', sync)
  }, [])

  const toggleFullscreen = useCallback(async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen()
      else await (workspaceRef?.current || section.current)?.requestFullscreen()
    } catch { /* the browser refused (for example inside a frame); the layout simply stays as it is */ }
  }, [workspaceRef])

  const speaking = live.agentState === 'speaking'
  const videoMax = compact ? 'max-h-60' : fullscreen ? 'max-h-[calc(100dvh-9rem)]' : 'max-h-[calc(100dvh-14rem)]'

  return (
    <section ref={section} aria-label="Live voice" className={cn('flex flex-col rounded-2xl border border-slate-200 bg-white', compact ? 'm-3 p-3' : 'p-3 sm:p-4')}>
      <div className={cn('relative overflow-hidden rounded-xl bg-slate-950', speaking && 'ring-2 ring-violet-400')}>
        <video ref={video} autoPlay playsInline muted aria-label="Assistant avatar" className={cn('mx-auto block w-full object-contain', videoMax, !live.videoTrack && 'hidden')} />
        {!live.videoTrack && (
          <div className={cn('flex flex-col items-center justify-center gap-3 bg-gradient-to-br from-navy-50 to-violet-50 text-center text-slate-600', compact ? 'aspect-video' : 'aspect-video min-h-[16rem]')}>
            {live.connection === 'connecting' ? <Loader2 className="h-9 w-9 animate-spin text-navy-600" aria-hidden /> : <Bot className="h-12 w-12 text-navy-600" aria-hidden />}
            <p className="max-w-sm px-4 text-sm">
              {live.connection === 'connecting' ? 'Connecting to the live voice service…'
                : connected ? 'Connected. The avatar video is not showing (still loading, or this is a voice-only session). You can keep typing; replies are also spoken when audio is available.'
                : live.connection === 'error' || live.connection === 'disconnected' ? 'The avatar session is not running. You can still chat in the conversation panel.'
                : 'The avatar appears here once a conversation starts.'}
            </p>
          </div>
        )}
        {(connected || live.connection === 'reconnecting') && (
          <span className="absolute left-3 top-3 flex items-center gap-1.5 rounded-full bg-white/90 px-2.5 py-1 text-xs font-medium text-slate-800 shadow">
            <AudioLines className={cn('h-3.5 w-3.5', speaking && 'text-violet-600')} aria-hidden />{live.connection === 'reconnecting' ? 'Reconnecting…' : AGENT[live.agentState]}
          </span>
        )}
      </div>

      <div role="status" aria-live="polite" className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-700">
        <span className="flex items-center gap-1.5"><span aria-hidden className={cn('h-2 w-2 rounded-full', dot)} />{label}</span>
        {connected && <span>Assistant: {AGENT[live.agentState]}</span>}
        {connected && <span>Microphone: {live.micOn ? 'on' : 'muted'}</span>}
      </div>

      {live.error && <Notice tone="error" className="mt-3 flex items-start gap-2 text-xs"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />{live.error}</Notice>}
      {live.micError && connected && <Notice tone="warn" className="mt-3 text-xs">{live.micError}</Notice>}
      {live.connection === 'disconnected' && !live.error && <Notice tone="warn" className="mt-3 text-xs">The live voice session ended. Start a new conversation to continue.</Notice>}
      {!ready && assistant.status.state === 'online' && <Notice tone="warn" className="mt-3 text-xs">Live voice is not configured on the server yet, so the avatar cannot start. Typed chat still works.</Notice>}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {!live.active ? (
          <Button size="sm" onClick={live.start} disabled={!ready || assistant.status.state !== 'online'}><AudioLines className="h-4 w-4" aria-hidden /> Start conversation</Button>
        ) : (
          <>
            <Button size="sm" variant="danger" onClick={live.end}><PhoneOff className="h-4 w-4" aria-hidden /> End conversation</Button>
            <Button size="sm" variant="outline" onClick={live.toggleMic} disabled={!connected} aria-pressed={!live.micOn}>
              {live.micOn ? <><MicOff className="h-4 w-4" aria-hidden /> Mute</> : <><Mic className="h-4 w-4" aria-hidden /> Unmute</>}
            </Button>
          </>
        )}
        <span className="ml-auto flex items-center gap-2">
          {panel && (
            <Button size="sm" variant="outline" onClick={panel.toggle} aria-expanded={panel.open} aria-controls={panel.id}>
              {panel.open ? <PanelRightClose className="h-4 w-4" aria-hidden /> : <PanelRightOpen className="h-4 w-4" aria-hidden />}
              <span className="hidden sm:inline">{panel.open ? 'Hide conversation' : 'Show conversation'}</span><span className="sm:hidden">{panel.open ? 'Hide' : 'Show'}</span>
            </Button>
          )}
          {canFullscreen && (
            <Button size="sm" variant="outline" onClick={toggleFullscreen} aria-pressed={fullscreen}>
              {fullscreen ? <><Minimize2 className="h-4 w-4" aria-hidden /> Exit full screen</> : <><Maximize2 className="h-4 w-4" aria-hidden /> Full screen</>}
            </Button>
          )}
        </span>
      </div>
      {compact && <p className="mt-2 text-[10px] leading-snug text-slate-500">Your microphone is used only while a conversation is active. Results shown are real backend data for your role, and anything that changes state needs your click to confirm.</p>}
    </section>
  )
}
