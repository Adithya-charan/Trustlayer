"""TrustLayer voice agent worker (LiveKit Agents 1.8).

Audio path:  browser mic -> LiveKit room -> Sarvam speech-to-text -> TrustLayer backend (Groq router, permissions, audit)
             -> Sarvam text-to-speech -> Tavus avatar (renders the speech as lip-synced video) -> LiveKit -> browser.
Exactly one component speaks: when the avatar is running the agent's own audio output is disabled; if the avatar cannot start the
worker says so on screen and continues voice-only, never silently.
Run (dev):   .venv/Scripts/python.exe agent.py dev        Run (prod):  .venv/Scripts/python.exe agent.py start"""
import asyncio
import json
import logging
import os
import sys

import envload

envload.load()  # must run before the plugins read their keys from the environment

from livekit import agents, rtc  # noqa: E402
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, JobProcess, llm  # noqa: E402
from livekit.agents.voice.room_io import RoomOptions  # noqa: E402
from livekit.plugins import sarvam, silero, tavus  # noqa: E402

from brain import Brain  # noqa: E402
from saying import SayGate  # noqa: E402
from translate import ENGLISH, Translator, make_post  # noqa: E402

log = logging.getLogger("trustlayer.voice")
AGENT_NAME = os.environ.get("VOICE_AGENT_NAME", "trustlayer-voice")
TOPIC = "trustlayer.event"
SESSION_LIMIT_S = 15 * 60  # matches the ticket lifetime; the session ends when the ticket would no longer work

server = AgentServer()


class BackendBrain(llm.LLM):
    """Marker model. LiveKit only generates a reply when the session has an LLM, but this worker has no model of its own: TrustLayerAgent.llm_node
    answers every turn through the TrustLayer backend. chat() is therefore never used; if something ever calls it we fail loudly instead of
    silently substituting a different model."""

    @property
    def model(self) -> str:
        return "trustlayer-backend"

    @property
    def provider(self) -> str:
        return "trustlayer"

    def chat(self, *args, **kwargs):
        raise RuntimeError("The voice worker has no model of its own; every turn is answered by the TrustLayer backend.")


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()  # Sarvam's speech-to-text is not streaming, so voice-activity detection ends each turn


server.setup_fnc = prewarm


class TrustLayerAgent(Agent):
    """No model of its own: every user turn is answered by the TrustLayer backend, which decides, authorizes and records."""

    def __init__(self, brain: Brain, emit, translator: Translator, tts):
        super().__init__(instructions="TrustLayer voice operator. Answers come only from the TrustLayer backend.")
        self.brain, self.emit, self.translator, self.voice = brain, emit, translator, tts

    async def llm_node(self, chat_ctx, tools, model_settings):
        user = next((m for m in reversed(chat_ctx.messages()) if m.role == "user"), None)
        text = (user.text_content if user else None) or ""
        # The backend works in English: translate the user's words in, and its spoken line back into the language they used, voiced in that language.
        english, lang = await self.translator.to_english(text)
        out = await self.brain.turn(english)
        spoken, spoken_lang = await self.translator.from_english(out["spoken"], lang)
        if out["event"]:
            await self.emit({**out["event"], "spoken": spoken, "language": spoken_lang})
        if spoken:
            self.voice.update_options(target_language_code=spoken_lang)
            yield spoken


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    try:  # the signed-in user; identity == username (set by the backend token). Do not wait forever for someone who already left.
        participant = await asyncio.wait_for(ctx.wait_for_participant(), timeout=45)
    except asyncio.TimeoutError:
        ctx.shutdown(reason="no participant joined")
        return
    identity = participant.identity
    ctx.room.on("participant_disconnected", lambda p: p.identity == identity and ctx.shutdown(reason="user left"))  # free the job and the room

    async def emit(event: dict) -> None:
        # Only the user in this room ever receives events (results, confirmations, transcripts).
        await ctx.room.local_participant.publish_data(json.dumps(event, default=str), reliable=True, destination_identities=[identity], topic=TOPIC)

    def emit_soon(event: dict) -> None:
        asyncio.create_task(emit(event))

    brain = Brain(os.environ.get("TRUSTLAYER_BACKEND_URL", "http://127.0.0.1:8000"), os.environ["VOICE_AGENT_SECRET"], ctx.job.metadata)
    lang = os.environ.get("SARVAM_LANGUAGE", "unknown")  # "unknown" = Sarvam detects which Indian language is being spoken
    # The plugin's default model (bulbul:v2) rejects the "priya" speaker, so name a model that supports it.
    tts = sarvam.TTS(target_language_code=ENGLISH, model=os.environ.get("SARVAM_TTS_MODEL") or "bulbul:v3", speaker=os.environ.get("SARVAM_TTS_SPEAKER") or "priya")  # female voice to match the avatar
    translator = Translator(make_post(os.environ["SARVAM_API_KEY"]))
    session = AgentSession(
        stt=sarvam.STT(language=lang),
        tts=tts,
        vad=ctx.proc.userdata["vad"],
        llm=BackendBrain(),  # required for LiveKit to generate replies at all; see BackendBrain
    )
    session.on("user_input_transcribed", lambda ev: ev.is_final and emit_soon({"type": "user_transcript", "text": ev.transcript}))
    session.on("agent_state_changed", lambda ev: emit_soon({"type": "agent_state", "state": ev.new_state}))

    gate = SayGate()

    async def speak(say_id: str, text: str) -> None:
        # Typed and confirmed replies reach the avatar here: the backend names the line, AgentSession.say() voices it through the same TTS ->
        # audio output -> Tavus path as spoken turns. A newer reply replaces one still being spoken.
        try:
            await session.interrupt()
            tts.update_options(target_language_code=ENGLISH)  # typed replies are English
            await session.say(text, allow_interruptions=True).wait_for_playout()
            await emit({"type": "spoken", "id": say_id, "ok": True})
        except Exception as exc:  # noqa: BLE001 - the text stays on screen; tell the user instead of failing silently
            log.warning("say failed: %s", type(exc).__name__)
            await emit({"type": "spoken", "id": say_id, "ok": False})
            await emit({"type": "notice", "message": "The avatar could not speak that reply. It is shown as text."})

    def on_data(packet: rtc.DataPacket) -> None:
        accepted = gate.accept(packet.topic, packet.participant, packet.data)
        if accepted:
            asyncio.create_task(speak(*accepted))

    ctx.room.on("data_received", on_data)

    avatar_running = False
    if envload.avatar_configured():
        try:
            kwargs = {"face_id": os.environ["TAVUS_FACE_ID"]}
            # By default Tavus's stock LiveKit setup is used. A custom pal can have its own conversation settings and talk over this agent, so it is
            # opt-in (TAVUS_USE_PAL=true) and only after the pal is confirmed to be configured for LiveKit's audio mode.
            if os.environ.get("TAVUS_USE_PAL", "").lower() == "true" and os.environ.get("TAVUS_PAL_ID"):
                kwargs["pal_id"] = os.environ["TAVUS_PAL_ID"]
            await tavus.AvatarSession(**kwargs).start(session, room=ctx.room)  # must start before the session so it owns the audio output
            avatar_running = True
        except Exception as exc:  # noqa: BLE001 - reported on screen; never swallowed silently
            log.warning("tavus avatar failed to start: %s", type(exc).__name__)
            await emit({"type": "notice", "message": "The avatar could not start, so this conversation is voice-only."})

    # record=False: LiveKit Cloud may offer session recording (the job request carried enable_recording). TrustLayer stores no audio or transcripts,
    # so the worker opts out explicitly instead of inheriting that default.
    await session.start(agent=TrustLayerAgent(brain, emit, translator, tts), room=ctx.room, record=False,
                        room_options=RoomOptions(participant_identity=identity, audio_output=not avatar_running, text_output=False, text_input=False,
                                                 delete_room_on_close=True))
    await emit({"type": "ready", "avatar": avatar_running})

    async def limit() -> None:
        await asyncio.sleep(SESSION_LIMIT_S)
        await emit({"type": "notice", "message": "The voice session reached its time limit. Start a new conversation to continue."})
        ctx.shutdown(reason="session time limit")

    asyncio.create_task(limit())


if __name__ == "__main__":
    problems = envload.missing()
    if problems:
        sys.exit("Voice agent not started. Missing configuration: " + ", ".join(problems) + " (set them in backend/.env).")
    agents.cli.run_app(server)
