"""Turns stored audit events into the answers an Admin actually wants: who did what, to which resource and field, which policy decided, why, and what happened.
Everything here is read from the audit trail (names, kinds, strategies, policies; never data values). It is the single source for the Audit Center, the
Recent Activity views, the dashboard counters and the assistant, so they cannot disagree."""
import datetime as dt
import re

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.b1 import mask
from app.database.models import AuditEvent, User

OPERATIONS = ("b1_query", "b1_access_denied", "b1_policy_change", "b1_review", "b1_scan", "auth_login")
ACTION = {"b1_query": "Query", "b1_access_denied": "Access attempt", "b1_policy_change": "Policy change", "b1_review": "Classification review", "b1_scan": "Scan",
          "auth_login": "Login", "b1_upload_analyze": "Dataset upload"}
RESULT_WORD = {"ALLOW": "ALLOWED", "PARTIAL": "MASKED", "HASH": "HASHED", "REDACT": "REDACTED", "DENY": "WITHHELD"}
STRATEGY_WHY = {
    "PARTIAL": "only part of the value is shown; the full {kind} is not permitted for {role} users",
    "HASH": "a keyed hash is returned, so {kind} can be joined and counted without exposing the raw value",
    "REDACT": "the {kind} value is replaced with [REDACTED]",
    "DENY": "raw {kind} is not permitted for {role} users, so the column is withheld",
}
SOURCE_LABEL = {"user": "personal policy set by an Admin", "role": "role policy edited by an Admin", "default": "built-in role policy"}


def why_field(role: str, username: str, kind: str, tag: str | None, strategy: str, source: str = "default") -> dict:
    """The explanation for ONE field in ONE result: the policy path, the decision word, and a sentence saying why."""
    if role == "Admin" and strategy == "ALLOW":
        reason = "Admin accounts are permitted to view real values."
    elif tag == "NON_SENSITIVE" and strategy == "ALLOW":
        reason = "This column is not classified as sensitive, so no masking applies."
    elif strategy == "ALLOW":
        reason = f"An Admin-edited policy lets {role} users see {kind} in clear."
    else:
        reason = STRATEGY_WHY.get(strategy, "the policy applies {strategy}").format(kind=kind, role=role, strategy=strategy)
        reason = reason[:1].upper() + reason[1:] + "."
    src = SOURCE_LABEL.get(source, SOURCE_LABEL["default"]) if role != "Admin" and tag != "NON_SENSITIVE" else "no policy needed" if tag == "NON_SENSITIVE" else "Admin role"
    if source == "user" and username:
        src = f"personal policy for {username}, set by an Admin"
    return {"kind": kind, "strategy": strategy, "result": RESULT_WORD.get(strategy, strategy), "source": source, "source_label": src,
            "policy_path": f"{role} → {kind} → {strategy}", "reason": reason}


def field_detail(name: str, role: str, username: str, kind: str, tag: str | None, strategy: str, source: str) -> dict:
    return {"name": name, **why_field(role, username, kind, tag, strategy, source)}


# ---------- reading stored events ----------
_CHANGE_RE = re.compile(r"^(changed|reset to default): (.+) \((user|role)\) (\w+) (\w+) -> (\w+)")


def _policy_change(e: AuditEvent, names: dict[str, str]) -> dict | None:
    d = e.detail or {}
    if d.get("old") and d.get("new"):
        return d
    m = _CHANGE_RE.match(e.reason or "")  # events recorded before structured detail existed
    if not m:
        return None
    verb, who, scope, kind, old, new = m.groups()
    return {"verb": "reset" if verb.startswith("reset") else "changed", "scope": scope, "subject": e.subject_ref, "display_name": who, "kind": kind, "old": old, "new": new, "note": ""}


def _is_noop(e: AuditEvent) -> bool:
    ch = _policy_change(e, {})
    return bool(ch) and ch.get("old") == ch.get("new")


def humanize(e: AuditEvent, names: dict[str, str] | None = None) -> dict:
    """One stored event as who / what / where / why / policy / decision / result. Older events (without `detail`) are explained from their fields and reason."""
    names = names or {}
    detail = e.detail or {}
    actor_name = names.get(e.actor, e.actor)
    fields = [f for f in (detail.get("fields") or [])]
    if not fields and e.operation in ("b1_query", "b1_access_denied"):
        fields = [{"name": n, **why_field(e.role, e.actor, v.get("category", "-"), None, v.get("strategy", "-"), "default")} for n, v in (e.fields or {}).items()]
    change = _policy_change(e, names) if e.operation == "b1_policy_change" else None
    out = {"id": e.id, "ts": e.ts, "request_id": e.request_id, "actor": e.actor, "actor_name": actor_name, "role": e.role, "operation": e.operation,
           "action": ACTION.get(e.operation, e.operation.replace("b1_", "").replace("_", " ").capitalize()), "resource": e.subject_ref, "fields": fields, "policy": e.policy,
           "decision": e.decision, "reason": e.reason, "change": None, "result": "", "why": []}
    if e.operation == "b1_query":
        out["result"] = _query_result(e, fields)
        out["why"] = [f"{f['name']}: {f['policy_path']} ({f['source_label']}) — {f['reason']}" for f in fields if f.get("strategy") != "ALLOW"] or ["No sensitive column was masked in this result."]
    elif e.operation == "b1_access_denied":
        out["result"] = "Access restricted by the current policy; the column was not returned."
        out["why"] = [f"{f['name']}: {f['policy_path']} ({f['source_label']}) — {f['reason']}" for f in fields]
    elif change:
        subject = change.get("display_name") or change.get("subject") or "?"
        out["change"] = {"subject": subject, "subject_username": change.get("subject"), "scope": change.get("scope"), "kind": change.get("kind"), "old": change.get("old"),
                         "new": change.get("new"), "verb": change.get("verb", "changed"), "note": change.get("note") or ""}
        out["result"] = f"{change.get('kind')}: {change.get('old')} → {change.get('new')} for {subject}" + (" (reset to default)" if change.get("verb") == "reset" else "")
        out["why"] = [change.get("note") or f"{actor_name} ({e.role}) changed the {change.get('scope')} policy; the database itself is unchanged."]
    elif e.operation == "auth_login":
        out["result"] = "Signed in" if e.decision == "ALLOW" else "Sign-in refused"
        out["why"] = [e.reason]
    else:
        out["result"] = e.reason
        out["why"] = [e.reason]
    return out


def _query_result(e: AuditEvent, fields: list[dict]) -> str:
    if not fields:
        return e.reason
    parts = [f"{f['name']} {f.get('result', f.get('strategy', '')).lower()}" for f in fields]
    return ", ".join(parts[:6]) + (f" (+{len(parts) - 6} more)" if len(parts) > 6 else "")


def _names(db: Session) -> dict[str, str]:
    return {u.username: u.display_name for u in db.scalars(select(User))}


def _filters(stmt, *, user=None, role=None, decision=None, operation=None, resource=None, hours=None, field=None, own_only=False, after=None):
    if user and own_only:  # a user's self-view: only what THEY did, never an Admin's actions about them
        stmt = stmt.where(AuditEvent.actor == user)
    elif user:
        stmt = stmt.where(or_(AuditEvent.actor == user, (AuditEvent.operation == "b1_policy_change") & (AuditEvent.subject_ref == user)))
    if role:
        stmt = stmt.where(AuditEvent.role == mask.ROLE_ALIASES.get(role, role))
    if decision:
        stmt = stmt.where(AuditEvent.decision == decision.upper())
    if operation:
        stmt = stmt.where(AuditEvent.operation == operation)
    if resource:
        stmt = stmt.where(AuditEvent.subject_ref == resource)
    if after is not None:
        stmt = stmt.where(AuditEvent.ts > after)
    if hours:
        stmt = stmt.where(AuditEvent.ts > dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours))
    return stmt


def feed(db: Session, *, limit: int = 25, offset: int = 0, operations: tuple[str, ...] = OPERATIONS, field: str | None = None, **flt) -> list[dict]:
    """Newest first. `field` keeps only events that touched that column name (matched on stored field names, case-insensitive)."""
    stmt = _filters(select(AuditEvent).where(AuditEvent.operation.in_(operations)), **flt).order_by(AuditEvent.id.desc())
    names = _names(db)
    out: list[dict] = []
    want = (field or "").lower()
    for e in db.scalars(stmt.offset(offset).limit(1000)):
        if e.operation == "b1_policy_change" and _is_noop(e):
            continue
        if want and not any(want in k.lower() for k in (e.fields or {})) and not (e.detail or {}).get("kind", "").lower() == want:
            continue
        out.append(humanize(e, names))
        if len(out) >= limit:
            break
    return out


def policy_changes(db: Session, *, limit: int = 5, user: str | None = None, kind: str | None = None) -> list[dict]:
    """The latest policy changes, newest first. `user` matches the person whose policy changed (or the Admin who changed it)."""
    names = _names(db)
    out: list[dict] = []
    want_user = (user or "").lower()
    stmt = select(AuditEvent).where(AuditEvent.operation == "b1_policy_change").order_by(AuditEvent.id.desc()).limit(500)
    for e in db.scalars(stmt):
        h = humanize(e, names)
        ch = h["change"]
        if not ch or ch["old"] == ch["new"]:  # an Admin re-saving the strategy a person already had changed nothing
            continue
        if kind and (ch["kind"] or "").upper() != kind.upper():
            continue
        if want_user and want_user not in " ".join(str(x or "") for x in (ch["subject"], ch["subject_username"], h["actor"], h["actor_name"])).lower():
            continue
        out.append(h)
        if len(out) >= limit:
            break
    return out


def resolve_user(db: Session, text: str) -> str | None:
    """Maps a name the way people say it ('Kavya', 'kavya hegde', 'analyst_kavya') to ONE username, or None when it is unknown or ambiguous."""
    t = (text or "").strip().lower()
    if not t:
        return None
    users = list(db.scalars(select(User).where(User.active.is_(True))))
    exact = [u for u in users if t in (u.username.lower(), u.display_name.lower())]
    if len(exact) == 1:
        return exact[0].username
    part = [u for u in users if t in u.username.lower() or t in u.display_name.lower() or any(w == t for w in u.display_name.lower().split())]
    return part[0].username if len(part) == 1 else None


# ---------- dashboard counters ----------
def today(db: Session, hours: int = 24) -> dict:
    """Counters for the last `hours` hours, every one a COUNT over stored audit events."""
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    base = select(func.count()).select_from(AuditEvent).where(AuditEvent.ts > since)
    n = lambda *c: db.scalar(base.where(*c)) or 0  # noqa: E731
    return {"hours": hours, "access_events": n(AuditEvent.operation == "b1_query"), "masked_requests": n(AuditEvent.operation == "b1_query", AuditEvent.decision == "MASK"),
            "blocked_attempts": n(AuditEvent.operation == "b1_access_denied") + n(AuditEvent.decision == "DENY", AuditEvent.operation.in_(("b1_query", "b1_review", "b1_policy_change"))),
            "policy_changes": n(AuditEvent.operation == "b1_policy_change"), "logins": n(AuditEvent.operation == "auth_login", AuditEvent.decision == "ALLOW")}
