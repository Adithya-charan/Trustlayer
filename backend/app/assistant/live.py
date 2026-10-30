"""Live voice sessions. The backend mints (1) a short-lived LiveKit access token for the browser and (2) a signed ticket that lets the
agent worker act as that same user for one session. Secrets stay on the server: the browser gets only the room URL and its own token.

Least privilege: the browser may join exactly one room, publish its microphone only, and subscribe. It cannot publish data, create or
administer rooms. The ticket is useless alone: the agent must also present VOICE_AGENT_SECRET, and the backend re-checks the user's
current role on every turn."""
import asyncio
import datetime as dt
import hmac
import json
import logging
import time
import uuid

import jwt
from fastapi import HTTPException
from livekit import api as lk
from livekit.protocol import models as lk_models

from app.core.config import get_settings
from app.core.security import Actor

log = logging.getLogger("trustlayer.live")
TICKET_TTL = dt.timedelta(minutes=15)
TOKEN_TTL = dt.timedelta(minutes=10)
ROOM_TTL = 20 * 60  # seconds a room stays addressable: the 15-minute agent ticket plus slack
SAY_TOPIC = "trustlayer.say"
_ROOMS: dict[str, tuple[str, float]] = {}  # room -> (username, expires_at); single-process prototype, like the rate limiter


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def mint_ticket(actor: Actor, room: str) -> str:
    exp = dt.datetime.now(dt.timezone.utc) + TICKET_TTL
    return jwt.encode({"sub": actor.username, "purpose": "voice-agent", "room": room, "jti": str(uuid.uuid4()), "exp": exp},
                      get_settings().jwt_secret, algorithm="HS256")


def verify_ticket(ticket: str) -> dict:
    try:
        claims = jwt.decode(ticket, get_settings().jwt_secret, algorithms=["HS256"])
    except Exception:  # noqa: BLE001
        raise _error(401, "ticket_invalid", "The voice session ticket is invalid or has expired.") from None
    if claims.get("purpose") != "voice-agent" or not claims.get("sub"):
        raise _error(401, "ticket_invalid", "The voice session ticket is invalid or has expired.")
    return claims


def check_agent_key(presented: str | None) -> None:
    secret = get_settings().voice_agent_secret
    if len(secret) < 16 or not presented or not hmac.compare_digest(presented, secret):
        raise _error(401, "agent_unauthorized", "Invalid voice agent credentials.")


def _remember_room(room: str, username: str) -> None:
    now = time.time()
    for r in [r for r, (_, exp) in _ROOMS.items() if exp < now]:
        _ROOMS.pop(r, None)
    _ROOMS[room] = (username, now + ROOM_TTL)


def owns_room(username: str, room: str) -> bool:
    hit = _ROOMS.get(room)
    return bool(hit and hit[0] == username and hit[1] >= time.time())


async def _send_say(room: str, payload: bytes) -> None:
    s = get_settings()
    base = s.livekit_url.replace("wss://", "https://", 1).replace("ws://", "http://", 1)
    async with lk.LiveKitAPI(base, s.livekit_api_key, s.livekit_api_secret) as c:
        await c.room.send_data(lk.SendDataRequest(room=room, data=payload, kind=lk_models.DataPacket.RELIABLE, topic=SAY_TOPIC))


def say(actor: Actor, room: str | None, text: str) -> dict:
    """Asks the avatar to speak `text` (a line the BACKEND composed) in the caller's own live room, by sending a server-originated data message that only the
    agent worker acts on. `requested` means the message was handed to LiveKit; it is NOT proof that audio played (the agent reports that separately)."""
    if not room:
        return {"requested": False, "reason": "no live session"}
    if not get_settings().livekit_ready:
        return {"requested": False, "reason": "live voice is not configured"}
    if not owns_room(actor.username, room):
        return {"requested": False, "reason": "that live session is not active for your account"}
    text = (text or "").strip()[:1000]
    if not text:
        return {"requested": False, "reason": "nothing to say"}
    say_id = uuid.uuid4().hex
    try:
        asyncio.run(_send_say(room, json.dumps({"id": say_id, "text": text}).encode()))
    except Exception as exc:  # noqa: BLE001 - the reply stays visible as text; never echo provider text
        log.warning("say delivery failed: %s", type(exc).__name__)
        return {"requested": False, "id": say_id, "reason": "the avatar could not be reached, so the reply is shown as text only"}
    return {"requested": True, "id": say_id}


def create_session(actor: Actor) -> dict:
    s = get_settings()
    if not s.livekit_ready:
        raise _error(503, "live_not_configured", "Live voice is not configured on the server (LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, VOICE_AGENT_SECRET).")
    room = f"tl-{uuid.uuid4().hex[:12]}"
    token = (lk.AccessToken(s.livekit_api_key, s.livekit_api_secret)
             .with_identity(actor.username).with_name(actor.username).with_ttl(TOKEN_TTL)
             .with_grants(lk.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True, can_publish_data=False, can_publish_sources=["microphone"]))
             .with_room_config(lk.RoomConfiguration(agents=[lk.RoomAgentDispatch(agent_name=s.voice_agent_name, metadata=mint_ticket(actor, room))]))
             .to_jwt())
    _remember_room(room, actor.username)
    return {"url": s.livekit_url, "token": token, "room": room, "expires_in": int(TOKEN_TTL.total_seconds()), "avatar": s.avatar_ready}
