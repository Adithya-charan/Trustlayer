"""Language bridge for the voice worker. The TrustLayer backend (intent parser, assistant, audit) works in English, so a spoken turn in another Indian
language is translated to English on the way in, and the backend's spoken line is translated back for the avatar's voice. Uses Sarvam's translate API
(Mayura), which also reports the detected source language. Any failure falls back to the original text, so a turn never breaks because of translation."""
import logging
from typing import Awaitable, Callable

import aiohttp

log = logging.getLogger("trustlayer.voice")
URL = "https://api.sarvam.ai/translate"
ENGLISH = "en-IN"
MAX_CHARS = 900  # Mayura accepts up to 1000 characters per call
SUPPORTED = {"en-IN", "hi-IN", "bn-IN", "gu-IN", "kn-IN", "ml-IN", "mr-IN", "od-IN", "pa-IN", "ta-IN", "te-IN"}

Post = Callable[[dict], Awaitable[dict | None]]


def make_post(api_key: str) -> Post:
    async def post(body: dict) -> dict | None:
        timeout = aiohttp.ClientTimeout(total=12)
        async with aiohttp.ClientSession(timeout=timeout) as s, s.post(URL, headers={"api-subscription-key": api_key}, json=body) as r:
            if r.status != 200:
                log.warning("translate failed: HTTP %s", r.status)
                return None
            return await r.json(content_type=None)
    return post


class Translator:
    def __init__(self, post: Post):
        self.post = post

    async def to_english(self, text: str) -> tuple[str, str]:
        """Returns (english_text, detected_language_code). Falls back to (text, en-IN) on any problem."""
        text = (text or "").strip()[:MAX_CHARS]
        if not text or text.isascii():  # plain ASCII is treated as English; native-script text goes to the translator
            return text, ENGLISH
        try:
            data = await self.post({"input": text, "source_language_code": "auto", "target_language_code": ENGLISH, "model": "mayura:v1"})
        except Exception as exc:  # noqa: BLE001
            log.warning("translate failed: %s", type(exc).__name__)
            return text, ENGLISH
        if not data or not data.get("translated_text"):
            return text, ENGLISH
        lang = data.get("source_language_code")
        return str(data["translated_text"]), lang if lang in SUPPORTED else ENGLISH

    async def from_english(self, text: str, lang: str) -> tuple[str, str]:
        """Returns (text, language_the_text_is_in); the language is en-IN when translation was not needed or failed, so the voice never reads English in another accent."""
        text = (text or "").strip()
        if not text or lang == ENGLISH or lang not in SUPPORTED:
            return text, ENGLISH
        try:
            data = await self.post({"input": text[:MAX_CHARS], "source_language_code": ENGLISH, "target_language_code": lang, "model": "mayura:v1"})
        except Exception as exc:  # noqa: BLE001
            log.warning("translate failed: %s", type(exc).__name__)
            return text, ENGLISH
        if data and data.get("translated_text"):
            return str(data["translated_text"]), lang
        return text, ENGLISH
