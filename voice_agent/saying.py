"""Decides whether a data message from the room is a legitimate request to speak. Pure logic (no LiveKit), so it is unit tested offline.

The backend sends `{"id", "text"}` on topic SAY_TOPIC through the LiveKit server API after it has authorized the caller and composed the line.
Browsers cannot publish data (their token forbids it), but the worker still accepts only packets with no participant (server-originated),
a bounded length, and an id it has not spoken before, so a replayed or duplicated message never makes the avatar speak twice."""
import json

SAY_TOPIC = "trustlayer.say"
MAX_CHARS = 1000
REMEMBER_IDS = 200


class SayGate:
    def __init__(self) -> None:
        self._seen: list[str] = []

    def accept(self, topic: str | None, participant, data: bytes) -> tuple[str, str] | None:
        """Returns (id, text) to speak, or None when the packet must be ignored."""
        if topic != SAY_TOPIC or participant is not None:  # participant is None only for packets sent through the server API
            return None
        try:
            msg = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None
        if not isinstance(msg, dict):
            return None
        say_id, text = msg.get("id"), msg.get("text")
        if not isinstance(say_id, str) or not say_id or len(say_id) > 64 or not isinstance(text, str):
            return None
        text = text.strip()[:MAX_CHARS]
        if not text or say_id in self._seen:
            return None
        self._seen.append(say_id)
        del self._seen[:-REMEMBER_IDS]
        return say_id, text
