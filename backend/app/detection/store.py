"""Short-lived, in-memory store of ANALYSIS RESULTS (never rows or cell values), so the assistant can answer questions about an upload.
Per owner, capped, expires after one hour, lost on restart by design."""
import threading
import time
import uuid

TTL, PER_OWNER = 3600, 10
_lock = threading.Lock()
_items: dict[str, dict] = {}


def put(owner: str, name: str, result: dict) -> str:
    aid = uuid.uuid4().hex[:12]
    with _lock:
        now = time.time()
        for k in [k for k, v in _items.items() if now - v["at"] > TTL]:
            del _items[k]
        mine = sorted((k for k, v in _items.items() if v["owner"] == owner), key=lambda k: _items[k]["at"])
        for k in mine[: max(0, len(mine) - PER_OWNER + 1)]:
            del _items[k]
        _items[aid] = {"owner": owner, "name": name, "at": now, "result": result}
    return aid


def get(owner: str, aid: str | None = None) -> dict | None:
    """The owner's analysis by id, or their most recent when `aid` is None. Other users' analyses are invisible."""
    with _lock:
        mine = {k: v for k, v in _items.items() if v["owner"] == owner and time.time() - v["at"] <= TTL}
        if aid:
            v = mine.get(aid)
            return {"id": aid, **v} if v else None
        if not mine:
            return None
        k = max(mine, key=lambda k: mine[k]["at"])
        return {"id": k, **mine[k]}


def clear() -> None:
    with _lock:
        _items.clear()
