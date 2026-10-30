# Voice assistant: setup and architecture

The assistant is one conversation, reachable by typing (Ask AI panel), by clicking the mic (Sarvam speech-to-text), or by live voice
(LiveKit room + Sarvam + Tavus avatar). All three feed the same backend router, so permissions, confirmations and audit are identical.

```
typed / mic clip ──► POST /api/assistant/chat ─────────────┐
                                                           ▼
browser mic ─► LiveKit room ─► agent worker ─► POST /api/assistant/agent/chat ─► Groq picks ONE approved tool
   ▲                │  Sarvam STT (in)            (ticket + agent key)            ─► role/permission check ─► tool runs (or a signed
   │                │  Sarvam TTS (out)                                              confirmation is returned) ─► audit event
   └─ Tavus avatar video/audio ◄─ speech of the backend's `spoken` line
```

* **Groq** only names a tool (`assistant/tools.py` is the whole allow-list: no SQL, shell, HTTP or arbitrary workflow tools).
* **Backend** validates name, arguments and the caller's *current* role on every call. Consequential tools return a single-use signed
  confirmation; only the signed-in user's browser session can redeem it (a spoken "yes" cannot).
* **LiveKit token** (browser): one room, microphone publish only, no data publish, no admin, 10 minute TTL, minted by the backend.
* **Agent ticket**: 15 minute signed ticket passed to the worker as dispatch metadata. Useless alone: the worker must also present
  `VOICE_AGENT_SECRET`, and the backend re-reads the user's role each turn. The worker holds no model key and cannot confirm anything.
* **Tavus** renders the agent's speech. When the avatar runs, the agent's own audio output is disabled (one voice only). If the avatar
  cannot start, the UI says so and the session continues voice-only. The Tavus pal is NOT used unless `TAVUS_USE_PAL=true`.
* **n8n** runs only the three approved on-demand workflows through a fixed, header-authenticated webhook path. n8n answering "started"
  is shown as started; success/failure is shown only from the run report the workflow posts to TrustLayer.

## Environment variables (names; set values in `backend/.env`, never commit)
`GROQ_API_KEY`, `GROQ_MODEL` | `SARVAM_API_KEY`, `SARVAM_LANGUAGE`, `SARVAM_TTS_SPEAKER` | `LIVEKIT_URL`, `LIVEKIT_API_KEY`,
`LIVEKIT_API_SECRET` | `TAVUS_API_KEY`, `TAVUS_FACE_ID` (`TAVUS_PAL_ID`, `TAVUS_USE_PAL` optional) | `VOICE_AGENT_SECRET` (32+ random chars) |
`N8N_WEBHOOK_BASE_URL` (e.g. `http://127.0.0.1:5678/webhook`), `N8N_TRIGGER_SECRET` (32+ random chars).

## Run
1. Backend and frontend as usual (restart the backend after changing `.env`).
2. Agent worker (its own venv; installed from `voice_agent/requirements.txt`):
   `voice_agent/.venv/Scripts/python.exe voice_agent/agent.py dev`  (it refuses to start and names any missing variable).
3. On-demand workflows: `cd backend && .venv/Scripts/python.exe -m scripts.make_on_demand_workflows`, import the three files in
   `n8n/on-demand/`, create the n8n Header Auth credential **TrustLayer Trigger Key** (header `X-TrustLayer-Trigger-Key`, value =
   `N8N_TRIGGER_SECRET`), then **publish only those copies**. They contain no schedule, so publishing them starts nothing on a timer.
   The originals stay unpublished. Note: the scan copy keeps the original's hourly idempotency key, so a second on-demand scan within the
   same hour returns that hour's scan instead of running a new one (the direct "start scan" tool always runs a new scan).

**If the avatar or live voice "does nothing":** the worker (step 2) is a separate process and is not started by the backend or `npm run dev`. With it stopped, the
Sarvam, LiveKit and Tavus keys can all be valid and the page still never connects. Check that the worker log says `registered worker`.
The worker calls the backend at `TRUSTLAYER_BACKEND_URL` (default `http://127.0.0.1:8000`); it must be the backend the browser is signed into.
The worker names the Sarvam TTS model explicitly (`SARVAM_TTS_MODEL`, default `bulbul:v3`; `SARVAM_TTS_SPEAKER`, default `priya`). The plugin's own default
(`bulbul:v2`) rejects `priya`, which made the avatar join but stay silent.

## Tests
`cd backend && .venv/Scripts/python.exe -m pytest` (mock transports; provider variables are blanked in `tests/conftest.py`).
`cd voice_agent && .venv/Scripts/python.exe -m pytest test_agent.py` (offline). The live chain (LiveKit + Sarvam + Tavus together) can only
be verified with real, funded keys and a running worker.

## Typed and confirmed replies are spoken by the avatar

**Why the avatar used to stay silent:** typed messages go through `POST /api/assistant/chat` and the answer appeared as text only. Browser text-to-speech is
deliberately muted during a live session (the avatar is meant to be the only voice), but the worker only spoke replies that came from *spoken* turns
(`llm_node`). Nothing told the avatar to say a typed or confirmed reply. Tavus is not generating answers here: it only renders the audio the LiveKit agent outputs.

**Fix (supported mechanism):** `chat` and `confirm` accept the caller's live `room`. After the normal authorized, audited logic runs, the backend sends the
line it composed (`spoken`) to the agent as a server-originated LiveKit data message (topic `trustlayer.say`, room ownership checked). The worker accepts only
server-originated packets, caps the length, drops repeated ids (so a reply is never spoken twice), interrupts any speech in progress and calls
`AgentSession.say(text)`, which flows through the same TTS -> Tavus path as spoken turns. The response carries `speech.requested`; the panel shows a notice when
it is false. The text always stays in the conversation panel. `requested: true` means the message was handed to LiveKit, not that audio played; the agent reports
`agent_state: speaking` and a `spoken` event separately.

No microphone is needed for this: if the browser denies the mic the session stays connected and the avatar still speaks typed replies.

## Languages
The worker listens with Sarvam auto-detect (`SARVAM_LANGUAGE`, default `unknown`) and `voice_agent/translate.py` translates the transcript to English for the backend
(which parses, authorizes and audits in English) and the spoken reply back into the language used, voiced by Sarvam `bulbul:v3` in that language. Supported: English, Hindi,
Bengali, Gujarati, Kannada, Malayalam, Marathi, Odia, Punjabi, Tamil, Telugu. Verified with synthesized Hindi and Telugu speech in a real room (transcript, audit task, spoken reply
in the same language). Typed replies are spoken in English. The on-screen reply card stays in English.
