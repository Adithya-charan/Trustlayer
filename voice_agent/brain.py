"""The agent's ONLY brain is the TrustLayer backend. This bridge sends the user's transcribed words to POST /api/assistant/agent/chat with
the session ticket and the agent key, and returns what the backend decided. The worker holds no model key, runs no tools and cannot
confirm anything: the backend applies the same approved-tool router, role checks, confirmation rules and audit as the typed chat."""
import json
from typing import Awaitable, Callable

import aiohttp

Post = Callable[[str, dict, dict], Awaitable[tuple[int, dict]]]
MAX_HISTORY = 6


async def aiohttp_post(url: str, headers: dict, body: dict) -> tuple[int, dict]:
    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(timeout=timeout) as s, s.post(url, headers=headers, json=body) as r:
        try:
            return r.status, await r.json(content_type=None)
        except (aiohttp.ContentTypeError, json.JSONDecodeError):
            return r.status, {}


def _detail(data: dict) -> tuple[str, str]:
    d = data.get("detail") if isinstance(data, dict) else None
    if isinstance(d, dict):
        return str(d.get("code", "")), str(d.get("message", ""))
    return "", str(d or "")


class Brain:
    def __init__(self, base_url: str, agent_key: str, ticket: str, post: Post = aiohttp_post):
        self.url = f"{base_url.rstrip('/')}/api/assistant/agent/chat"
        self.headers = {"X-TrustLayer-Voice-Agent-Key": agent_key}
        self.ticket = ticket
        self.post = post
        self.history: list[dict] = []

    async def turn(self, message: str) -> dict:
        """Returns {"spoken": str, "event": dict}. `event` is what the browser renders. Failures are spoken honestly, never papered over."""
        message = message.strip()[:500]
        if not message:
            return {"spoken": "", "event": None}
        try:
            status, data = await self.post(self.url, self.headers, {"ticket": self.ticket, "message": message, "history": self.history[-MAX_HISTORY:]})
        except Exception:  # noqa: BLE001 - network failure or timeout; the exception text is deliberately not forwarded
            return self._failure("I could not reach TrustLayer just now. Please try again.", "backend_unreachable")
        if status == 200:
            reply = str(data.get("reply", ""))
            self.history += [{"role": "user", "content": message}, {"role": "assistant", "content": reply[:500]}]
            self.history = self.history[-MAX_HISTORY:]
            spoken = str(data.get("spoken") or reply)
            return {"spoken": spoken, "event": {"type": "assistant", "reply": reply, "spoken": spoken, "result": data.get("result"),
                                                "confirmation": data.get("confirmation"), "refused": bool(data.get("refused"))}}
        code, text = _detail(data)
        if status == 401:
            return self._failure("This voice session has expired. Please start a new conversation.", code or "session_expired")
        if status == 429:
            return self._failure("TrustLayer is rate limiting requests. Please wait a moment and try again.", code or "rate_limited")
        return self._failure(text or "Something went wrong on the server. Please try again.", code or f"http_{status}")

    @staticmethod
    def _failure(spoken: str, code: str) -> dict:
        return {"spoken": spoken, "event": {"type": "error", "code": code, "message": spoken}}
