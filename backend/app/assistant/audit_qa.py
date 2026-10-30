"""Natural-language access to the security trail. The model only chooses a tool and its arguments; every fact in the reply is read from the audit trail by
Python at the moment of the question. Nothing here returns a data value (the trail holds none). The last answer is kept server-side per user, so a follow-up
such as 'who made the first one?' is resolved against what THIS user was actually shown, never against client-supplied text."""
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.b1 import activity
from app.core.security import Actor

ADMIN_ROLES = {"Admin", "security_admin"}
TTL = 3600.0
_last: dict[str, tuple[float, dict]] = {}

OPERATION_SETS = {
    "query": ("b1_query",), "denied": ("b1_access_denied",), "access": ("b1_query", "b1_access_denied"), "policy_change": ("b1_policy_change",),
    "login": ("auth_login",), "review": ("b1_review",), "scan": ("b1_scan",),
}


class PolicyChangesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(3, ge=1, le=20)
    user: str | None = Field(None, max_length=64)
    kind: str | None = Field(None, max_length=32)


class ActivityArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(5, ge=1, le=20)
    user: str | None = Field(None, max_length=64)
    decision: Literal["ALLOW", "MASK", "DENY"] | None = None
    operation: Literal["access", "query", "denied", "policy_change", "login", "review", "scan"] | None = None
    field: str | None = Field(None, max_length=64)
    hours: int | None = Field(None, ge=1, le=24 * 90)
    after_change_of: str | None = Field(None, max_length=32)  # e.g. PAN: only events after the most recent policy change of that kind


class FollowupArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aspect: Literal["who", "when", "why", "policy", "result", "details"] = "details"
    index: int = Field(1, ge=1, le=20)


def _remember(actor: Actor, kind: str, items: list[dict]) -> None:
    now = time.monotonic()
    for k in [k for k, (t, _) in _last.items() if now - t > TTL]:
        _last.pop(k, None)
    _last[actor.username] = (now, {"kind": kind, "items": items})


def _when(ts) -> str:
    return ts.strftime("%d %b %H:%M UTC") if hasattr(ts, "strftime") else str(ts)


def _line(n: int, h: dict) -> str:
    who = f"{h['actor_name']} ({h['role']})"
    if h["change"]:
        c = h["change"]
        base = f"{c['subject']} — {c['kind']}: {c['old']} → {c['new']}, changed by {who}"
        note = f" Reason: {c['note']}." if c["note"] else ""
        return f"{n}. {base} on {_when(h['ts'])}.{note}"
    where = f" on {h['resource']}" if h["resource"] else ""
    return f"{n}. {_when(h['ts'])} — {who}: {h['action']}{where}. {h['result']} [{h['decision']}]"


def _answer(kind: str, header: str, items: list[dict], actor: Actor, empty: str) -> dict:
    _remember(actor, kind, items)
    if not items:
        return {"kind": "audit_answer", "reply": empty, "items": []}
    lines = [header] + [_line(i + 1, h) for i, h in enumerate(items)]
    if len(items) == 1 and items[0]["why"]:
        lines.append("Why: " + items[0]["why"][0])
    return {"kind": "audit_answer", "reply": "\n".join(lines), "items": items}


def policy_changes(db: Session, actor: Actor, a: PolicyChangesArgs) -> dict:
    user = None
    if a.user:
        user = activity.resolve_user(db, a.user) or a.user
    items = activity.policy_changes(db, limit=a.limit, user=user, kind=a.kind)
    n = len(items)
    return _answer("policy_changes", f"Here {'is the' if n == 1 else 'are the'} {n} most recent policy change{'s' if n != 1 else ''}:", items, actor,
                   "No masking-policy changes have been recorded" + (f" for {a.user}" if a.user else "") + ".")


def access_history(db: Session, actor: Actor, a: ActivityArgs) -> dict:
    is_admin = actor.role in ADMIN_ROLES
    user = None
    if a.user:
        user = activity.resolve_user(db, a.user)
        if user is None:
            return {"kind": "audit_answer", "reply": f"I could not find exactly one user matching '{a.user}'.", "items": []}
    if not is_admin:
        if user and user != actor.username:
            return {"kind": "audit_answer", "reply": "You can only ask about your own activity.", "items": [], "refused": True}
        user = actor.username
    ops = OPERATION_SETS.get(a.operation) if a.operation else activity.OPERATIONS
    after = None
    if a.after_change_of:
        if not is_admin:
            return {"kind": "audit_answer", "reply": "Policy changes can only be asked about by an Admin.", "items": [], "refused": True}
        last = activity.policy_changes(db, limit=1, kind=a.after_change_of)
        if not last:
            return {"kind": "audit_answer", "reply": f"No {a.after_change_of.upper()} policy change has been recorded, so there is nothing to compare against.", "items": []}
        after = last[0]["ts"]
    items = activity.feed(db, limit=a.limit, user=user, decision=a.decision, operations=ops, field=a.field, hours=a.hours, own_only=not is_admin, after=after)
    if after is not None:
        c = last[0]["change"]
        header_extra = f" after {last[0]['actor_name']} changed {c['subject']}'s {c['kind']} policy ({c['old']} → {c['new']}) on {_when(after)}"
    else:
        header_extra = ""
    who = f" for {a.user}" if a.user else (" for you" if not is_admin else "")
    what = {"denied": "denied access attempt", "access": "access attempt", "policy_change": "policy change", "login": "sign-in"}.get(a.operation or "", "security event")
    if a.decision == "DENY" and not a.operation:
        what = "denied or refused request"
    n = len(items)
    return _answer("activity", f"Here {'is the' if n == 1 else 'are the'} {n} most recent {what}{'s' if n != 1 else ''}{who}{header_extra}:", items, actor,
                   (f"Nothing has been recorded{who} since{header_extra.replace(' after', '', 1)}." if after is not None else f"I found no matching {what}s{who}."))


def followup(db: Session, actor: Actor, a: FollowupArgs) -> dict:
    hit = _last.get(actor.username)
    if hit is None or time.monotonic() - hit[0] > TTL:
        return {"kind": "audit_answer", "reply": "I don't have an earlier answer to refer to. Ask about recent policy changes or activity first.", "items": []}
    items = hit[1]["items"]
    if a.index > len(items):
        return {"kind": "audit_answer", "reply": f"My last answer had only {len(items)} item{'s' if len(items) != 1 else ''}.", "items": []}
    h = items[a.index - 1]
    who = f"{h['actor_name']} ({h['role']})"
    if h["change"]:
        c = h["change"]
        about = f"the change to {c['subject']}'s {c['kind']} policy ({c['old']} → {c['new']})"
    else:
        about = f"item {a.index} ({h['action']}{' on ' + h['resource'] if h['resource'] else ''})"
    text = {
        "who": f"{who} was responsible for {about}.",
        "when": f"{about.capitalize()} happened on {_when(h['ts'])}.",
        "why": "Why: " + " ".join(h["why"]) if h["why"] else "No reason was recorded for it.",
        "policy": f"Policy: {h['policy']}." + "".join(f" {f['name']}: {f['policy_path']} ({f['source_label']})." for f in h["fields"][:4]),
        "result": f"Result: {h['result']} [{h['decision']}].",
        "details": _line(a.index, h) + (" Why: " + h["why"][0] if h["why"] else ""),
    }[a.aspect]
    return {"kind": "audit_answer", "reply": text, "items": [h]}
