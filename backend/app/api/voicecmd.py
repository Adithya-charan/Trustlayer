"""Voice Command Control API. The browser sends the TEXT it heard (speech-to-text happens server-side); this layer parses it into one approved intent,
checks the caller's real role for it, audits the decision and returns an action for the dashboard to carry out. It never runs SQL, never returns data
and never widens access: opened pages and tables still go through the normal identity -> policy engine -> masking path. Anything that changes policy
returns a signed, single-use confirmation which only the same signed-in user can redeem, and is re-authorized when redeemed."""
import datetime as dt
import re
import time
import uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import voicecmd
from app.api.b1 import PolicyIn, _policy_op
from app.assistant.tools import PAGES
from app.audit import logger as audit
from app.b1 import mask, policy
from app.core.config import get_settings
from app.core.security import Actor, current_actor, limiter
from app.database.models import User
from app.database.session import get_session
from app.policies.engine import has_permission

router = APIRouter(prefix="/api/voice-command")
_used: dict[str, float] = {}  # jti -> expiry (single-process prototype, like the assistant's confirmations)
CONFIRM_TTL = 120

PAGE_LABEL = {"overview": "Overview", "discovery": "Data Discovery", "explorer": "Data Explorer", "policies": "Access Policies", "access": "Users & Access",
              "audit": "Audit Center", "voice": "Voice Assistant", "automation": "Automation", "settings": "Settings"}
# intent -> (route to open, permission the caller needs, spoken result)
ROUTES = {
    "SHOW_HIGH_RISK_FIELDS": ("discovery?risk=High", "b1_query", "Showing high risk fields."),
    "SHOW_PII_FIELDS": ("discovery?tag=PII", "b1_query", "Showing PII fields."),
    "SHOW_SENSITIVE_FIELDS": ("discovery?tag=SENSITIVE", "b1_query", "Showing all sensitive fields."),
    "SHOW_FINANCIAL_FIELDS": ("discovery?tag=FINANCIAL_CONFIDENTIAL", "b1_query", "Showing financial sensitive fields."),
    "SHOW_PAYMENT_FIELDS": ("discovery?tag=PAYMENT_SENSITIVE", "b1_query", "Showing payment sensitive fields."),
    "SHOW_EMBEDDED_PII": ("discovery?embedded=1", "b1_query", "Showing PII embedded in free text."),
    "RUN_MASKING_DEMO": ("policies?demo=1", "b1_query", "Running the same query under every identity."),
    "SHOW_DENIED_REQUESTS": ("audit?decision=DENY", "b1_review", "Showing denied requests."),
    "SHOW_MASKED_REQUESTS": ("audit?decision=MASK", "b1_review", "Showing masked requests."),
    "SHOW_RECENT_AUDIT": ("audit?view=activity", "b1_review", "Showing recent activity."),
    "OPEN_AUDIT": ("audit", "b1_review", "Opening the Audit Center."),
    "SHOW_POLICY_CHANGES": ("audit?operation=policy_change", "b1_review", "Showing policy changes."),
}


class CommandIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=300)


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=20, max_length=2000)


def _record(db: Session, actor: Actor, intent: str, decision: str, reason: str) -> None:
    try:
        role = mask.normalize_role(actor.role)
    except PermissionError:
        role = actor.role
    audit.record(db, request_id=audit.new_request_id(), actor=actor.username, role=role, operation="b1_voice", purpose="b1_demo", fields={}, policy=f"voice/{intent}",
                 decision=decision, reason=reason[:300])


def _out(heard: str, intent: voicecmd.Intent, status: str, message: str, action=None, confirmation=None) -> dict:
    return {"heard": heard, "intent": intent.name, "label": intent.label, "params": intent.params, "status": status, "message": message, "action": action, "confirmation": confirmation}


def _can_open(role: str, page: str) -> bool:
    allowed = PAGES.get(page, set())
    return page in PAGES and (allowed is None or role in allowed)


def _strip(name: str) -> str:
    """Some seeded accounts carry their role in the display name ("Kavya Hegde (Analyst)"); spoken and shown names drop that suffix."""
    return re.sub(r"\s*\((admin|support|analyst|security[ _]admin|compliance[ _]officer)\)\s*$", "", name or "", flags=re.I)


def _name(u: User) -> str:
    return _strip(u.display_name) or u.username


def _targets(db: Session) -> list[dict]:
    """Accounts a policy can target, so spoken names resolve to a real user. Admins are excluded: their policy cannot be edited."""
    return [{"username": u.username, "display_name": _name(u)} for u in db.scalars(select(User).where(User.active.is_(True))) if mask.ROLE_ALIASES.get(u.role) in policy.EDITABLE_ROLES]


def _people(db: Session) -> list[dict]:
    return [{"username": u.username, "display_name": _name(u)} for u in db.scalars(select(User).where(User.active.is_(True))) if u.role in mask.ROLE_ALIASES]


@router.post("")
def command(body: CommandIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    limiter.check(f"voice:{actor.username}", 40, 60)
    heard = body.text.strip()
    admins = has_permission(actor.role, "b1_policy")
    intent = voicecmd.parse(heard, _people(db) if admins else _targets(db))
    name = intent.name

    def refuse(why: str):
        _record(db, actor, name, "DENY", f"voice command refused: {why}")
        return _out(heard, intent, "denied", why)

    if name in ("UNKNOWN", "HELP", "CHANGE_POLICY_INCOMPLETE", "CHANGE_POLICY_REFUSED"):
        return _out(heard, intent, "unknown" if name != "HELP" else "ok",
                    intent.hint if name != "UNKNOWN" else "I couldn't understand that command. Try: \"Show high risk PII\".")

    if name == "OPEN_PAGE":
        page = intent.params["page"]
        if not _can_open(actor.role, page):
            return refuse(f"Your role cannot open {PAGE_LABEL[page]}.")
        _record(db, actor, name, "ALLOW", f"voice opened {page}")
        return _out(heard, intent, "ok", f"Opening {PAGE_LABEL[page]}.", {"kind": "navigate", "route": page})

    if name in ROUTES:
        route, perm, said = ROUTES[name]
        if not has_permission(actor.role, perm):
            return refuse(f"Your role is not permitted to do that ({PAGE_LABEL[route.split('?')[0]]} is restricted).")
        _record(db, actor, name, "ALLOW", f"voice intent {name}")
        return _out(heard, intent, "ok", said, {"kind": "navigate", "route": route})

    if name == "OPEN_TABLE":
        if not has_permission(actor.role, "b1_query"):
            return refuse("Your role cannot browse data.")
        t = intent.params["table"]
        _record(db, actor, name, "ALLOW", f"voice opened table {t} (shown under the caller's own policy)")
        return _out(heard, intent, "ok", f"Opening {t.replace('_', ' ')}. You will see it exactly as your role is allowed to.", {"kind": "navigate", "route": f"explorer?table={t}"})

    if name in ("SHOW_ROLE_POLICIES", "SHOW_ROLE_ACCESS"):
        if not has_permission(actor.role, "b1_query"):
            return refuse("Your role cannot view policies.")
        role = intent.params["role"]
        demo = "&demo=1" if name == "SHOW_ROLE_ACCESS" else ""
        _record(db, actor, name, "ALLOW", f"voice intent {name} {role}")
        return _out(heard, intent, "ok", f"Showing the {role} policy." if not demo else f"Showing what {role} receives.", {"kind": "navigate", "route": f"policies?role={role}{demo}"})

    if name == "SHOW_ROLE_ACTIVITY":
        if not has_permission(actor.role, "b1_review"):
            return refuse("Your role is not permitted to read the audit trail.")
        _record(db, actor, name, "ALLOW", f"voice intent {name} {intent.params['role']}")
        return _out(heard, intent, "ok", f"Showing {intent.params['role']} activity.", {"kind": "navigate", "route": f"audit?role={intent.params['role']}"})

    if name == "SHOW_USER_ACTIVITY":
        if not has_permission(actor.role, "b1_review"):
            return refuse("Your role is not permitted to read other users' activity.")
        _record(db, actor, name, "ALLOW", f"voice opened activity of {intent.params['username']}")
        return _out(heard, intent, "ok", f"Showing {intent.params['display_name']}'s activity.", {"kind": "navigate", "route": f"audit?view=activity&user={intent.params['username']}"})

    if name == "OPEN_USER_ACCESS":
        if not has_permission(actor.role, "b1_policy"):
            return refuse("Your role is not permitted to view other users' access.")
        _record(db, actor, name, "ALLOW", f"voice opened access of {intent.params['username']}")
        return _out(heard, intent, "ok", f"Opening {intent.params['display_name']}'s access.", {"kind": "navigate", "route": f"access?user={intent.params['username']}"})

    if name == "SCAN_DATABASE":
        if not has_permission(actor.role, "b1_scan"):
            return refuse("Only an Admin can scan the database.")
        _record(db, actor, name, "ALLOW", "voice requested a database scan (the scan itself is authorized and audited by the scan endpoint)")
        return _out(heard, intent, "ok", "Scanning the database.", {"kind": "scan", "route": "discovery"})

    if name == "CHANGE_POLICY":
        p = intent.params
        if not has_permission(actor.role, "b1_policy"):
            return refuse("Only an Admin can change masking policy.")
        try:
            old, _ = policy.current(db, p["scope"], p["subject"], p["kind"])
        except (ValueError, LookupError):
            return refuse("That policy cannot be changed.")
        if old == p["strategy"]:
            return _out(heard, intent, "ok", f"{p['display_name']}'s {p['kind']} policy is already {voicecmd.strategy_phrase(old)}. Nothing to change.")
        exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=CONFIRM_TTL)
        token = jwt.encode({"sub": actor.username, "purpose": "voice-confirm", "scope": p["scope"], "subject": p["subject"], "kind": p["kind"], "strategy": p["strategy"],
                            "jti": str(uuid.uuid4()), "exp": exp}, get_settings().jwt_secret, algorithm="HS256")
        summary = f"I can change {p['display_name']}'s {p['kind']} policy from {voicecmd.strategy_phrase(old)} to {voicecmd.strategy_phrase(p['strategy'])}. Do you want me to apply this?"
        _record(db, actor, name, "ALLOW", f"voice asked to confirm: {p['subject']} {p['kind']} {old} -> {p['strategy']}")
        return _out(heard, intent, "confirm", summary, None, {"token": token, "summary": summary, "expires_at": exp.isoformat(), "old": old, "new": p["strategy"]})

    return _out(heard, intent, "unknown", "I couldn't understand that command. Try: \"Show high risk PII\".")


@router.post("/confirm")
def confirm(body: ConfirmIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """Redeems a confirmation. Re-checks the caller's permission and that the token is theirs, unexpired and unused, then applies the audited policy change."""
    limiter.check(f"voice:{actor.username}", 40, 60)
    try:
        c = jwt.decode(body.token, get_settings().jwt_secret, algorithms=["HS256"])
    except Exception:  # noqa: BLE001
        raise HTTPException(400, {"code": "bad_confirmation", "message": "That confirmation is invalid or has expired. Ask again."}) from None
    if c.get("purpose") != "voice-confirm" or c.get("sub") != actor.username:
        raise HTTPException(403, {"code": "bad_confirmation", "message": "That confirmation does not belong to you."})
    now = time.time()
    for k in [k for k, v in _used.items() if v < now]:
        _used.pop(k, None)
    if c["jti"] in _used:
        raise HTTPException(409, {"code": "confirmation_used", "message": "That confirmation was already used."})
    if not has_permission(actor.role, "b1_policy"):
        _record(db, actor, "CHANGE_POLICY", "DENY", "voice confirmation refused: role is not permitted")
        raise HTTPException(403, {"code": "forbidden", "message": "Your role is not permitted to change masking policy."})
    _used[c["jti"]] = float(c["exp"])
    out = _policy_op(db, actor, PolicyIn(scope=c["scope"], subject=c["subject"], kind=c["kind"], strategy=c["strategy"]), reset=False)
    _record(db, actor, "CHANGE_POLICY", "ALLOW", f"voice confirmed: {out['subject']} {out['kind']} {out['old']} -> {out['new']}")
    who = _strip(out["display_name"]) or out["subject"]
    return {"status": "done", "message": f"Done. {who}'s {out['kind']} policy is now {voicecmd.strategy_phrase(out['new'])}. The change is recorded in the audit trail.", "change": out,
            "action": {"kind": "navigate", "route": f"policies?user={out['subject']}" if out["scope"] == "user" else f"policies?role={out['subject']}"}}

