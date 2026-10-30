"""B1 data-protection engine API. Every route requires a signed-in user; roles are enforced here on the server (the UI only mirrors them).
Admin sees real values, Support partial masks, Analyst redaction/hashes. Errors never echo data values."""
import datetime as dt
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.audit import logger as audit
from app.b1 import activity, discover, mask, overview, policy, query as q, targets
from app.b1.detect import KINDS, TAG_OF, TAGS
from app.core.security import Actor, current_actor, limiter, require
from app.policies.engine import has_permission
from app.database.models import AuditEvent, User
from app.database.session import get_session

log = logging.getLogger("trustlayer.b1")
router = APIRouter(prefix="/api/b1")


def _role_label(role: str) -> str:
    """Audit label for any account role; a refused role must not raise while the refusal is being recorded."""
    try:
        return mask.normalize_role(role)
    except PermissionError:
        return "unmapped"


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def _target(name: str) -> targets.Target:
    try:
        return targets.get_target(name)
    except KeyError:
        raise _err(422, "unknown_target", "Unknown database target. Use one of: " + ", ".join(targets.NAMES) + ".") from None
    except LookupError:
        raise _err(503, "target_unavailable", "That database is not configured on the server.") from None


class Guard:
    """Translates engine errors into safe, value-free HTTP errors."""

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        if ev is None:
            return False
        if isinstance(ev, HTTPException):
            return False
        if isinstance(ev, PermissionError):
            raise _err(403, "b1_forbidden", str(ev) or "Your role is not permitted to do that.") from None
        if isinstance(ev, q.ScanRequired):
            raise _err(409, "scan_required", "This table has not been scanned yet. An Admin must run a scan first, so its columns are classified.") from None
        if isinstance(ev, LookupError):
            raise _err(404, "unknown_object", "Unknown table or column.") from None
        if isinstance(ev, ValueError):
            raise _err(422, "unsupported_query", str(ev)[:200]) from None
        if isinstance(ev, SQLAlchemyError):
            log.warning("b1 database error: %s", type(ev).__name__)
            raise _err(502, "database_unavailable", "The target database could not be queried. Check its connection and try again.") from None
        return False


class TargetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(default=targets.NAME, max_length=16)


class ReviewIn(TargetIn):
    table: str = Field(max_length=64)
    column: str = Field(max_length=64)
    kind: str = Field(max_length=32)
    confirm_masking_release: bool = False  # must be true to set NON_SENSITIVE or otherwise release masking (server-side guard, not a UI-only check)


class ClearIn(TargetIn):
    table: str = Field(max_length=64)
    column: str = Field(max_length=64)
    confirm_masking_release: bool = False


class QueryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(default=targets.NAME, max_length=16)
    sql: str | None = Field(default=None, max_length=600)
    table: str | None = Field(default=None, max_length=64)
    columns: list[str] = Field(default_factory=list, max_length=60)
    filters: list[q.Filter] = Field(default_factory=list, max_length=5)
    order_by: str | None = Field(default=None, max_length=64)
    descending: bool = False
    limit: int = Field(20, ge=1, le=q.MAX_LIMIT)

    def spec(self) -> q.QuerySpec:
        if self.sql:
            return q.parse_sql(self.sql, self.target)
        if not self.table or not self.columns:
            raise ValueError("Provide either `sql`, or `table` and `columns`.")
        return q.QuerySpec(target=self.target, table=self.table, columns=self.columns, filters=self.filters, order_by=self.order_by,
                           descending=self.descending, limit=self.limit)


@router.get("/targets")
def list_targets(fresh: bool = False, actor: Actor = Depends(require("b1_query"))):
    """Every backend (Neon PostgreSQL, SQLite, MySQL) with a live health check; an unconfigured one says so. Never includes a connection string, host, path or credential."""
    return {"targets": targets.available(fresh), "role": mask.normalize_role(actor.role)}


@router.get("/overview")
def overview_view(target: str = targets.NAME, actor: Actor = Depends(require("b1_query")), db: Session = Depends(get_session)):
    """Live headline numbers for the Overview page: backends, tables, records, sensitive/protected fields, active policies and audit counts."""
    t = _target(target)
    with Guard():
        return {**overview.build(db, t), "backends": targets.available(), "role": mask.normalize_role(actor.role)}


@router.post("/scan")
def scan(body: TargetIn, actor: Actor = Depends(require("b1_scan")), db: Session = Depends(get_session)):
    limiter.check(f"b1scan:{actor.username}", 6, 60)
    t = _target(body.target)
    with Guard():
        result = discover.scan(db, t, actor.username)
    audit.record(db, request_id=audit.new_request_id(), actor=actor.username, role=mask.normalize_role(actor.role), operation="b1_scan", purpose="b1_demo", fields={},
                 policy="b1/scan", decision="ALLOW", reason=f"scanned {result['tables']} tables, {result['columns']} columns on {t.name}; ML supplement {result['ml_supplement']['mode']}", subject_ref=t.name)
    overview.clear_cache()
    return {"target": t.name, **result}


RISK = {"PII_HIGH": "High", "PAYMENT_SENSITIVE": "High", "PII_MEDIUM": "Medium", "FINANCIAL_CONFIDENTIAL": "Medium", "NON_SENSITIVE": "Low"}


@router.get("/schema")
def schema(target: str = targets.NAME, actor: Actor = Depends(require("b1_query")), db: Session = Depends(get_session)):
    """Data Explorer metadata: tables, row counts and per column type, classification, detection methods, risk and the masking the CALLER's policy applies.
    Contains no data values; sample rows come from /query, which masks and audits them."""
    t = _target(target)
    role = mask.normalize_role(actor.role)
    ov = policy.load(db, actor.username, role)
    with Guard():
        tags = {(f["table"], f["column"]): f for f in discover.fields(db, t)}
        counts = {c["name"]: c["rows"] for c in overview.counts(t)}  # cached for a short time: counting 9 tables on a remote database is slow
        tables = []
        for name, table in sorted(t.tables().items()):
            cols = []
            for c in table.columns:
                f = tags.get((name, c.name))
                tag = f["tag"] if f else None
                strategy = mask.strategy_for(role, f["kind"], tag, ov) if f else None
                cols.append({"name": c.name, "type": str(c.type), "primary_key": c.primary_key, "nullable": bool(c.nullable),
                             "kind": f["kind"] if f else None, "tag": tag, "confidence": f["confidence"] if f else None, "status": f["status"] if f else None,
                             "methods": f["methods"] if f else [], "rationale": f["rationale"] if f else "", "reviewed": f["reviewed"] if f else False,
                             "risk": RISK.get(tag) if f else None, "strategy": strategy,
                             "masked": None if strategy is None else strategy != "ALLOW"})
            tables.append({"name": name, "rows": counts.get(name, 0), "columns": cols,
                           "sensitive_columns": sum(1 for x in cols if x["tag"] and x["tag"] != "NON_SENSITIVE"),
                           "risk": next((r for r in ("High", "Medium") if any(x["risk"] == r for x in cols)), "Low" if tags else None)})
    return {"target": t.name, "dialect": t.dialect, "scanned": bool(tags), "your_role": role, "tables": tables}


@router.get("/fields")
def fields(target: str = targets.NAME, table: str | None = None, status: str | None = None, actor: Actor = Depends(require("b1_query")), db: Session = Depends(get_session)):
    t = _target(target)
    with Guard():
        return {"target": t.name, "fields": discover.fields(db, t, table, status)}


def _deny_review(db: Session, actor: Actor, table: str, column: str, reason: str, kind: str = "") -> None:
    """Audits a refused classification change (authorization, or a missing masking-release confirmation) and raises nothing; callers raise."""
    audit.record(db, request_id=audit.new_request_id(), actor=actor.username, role=_role_label(actor.role), operation="b1_review", purpose="b1_demo",
                 fields={column: {"category": kind or "-", "strategy": "DENY"}}, policy="b1/review", decision="DENY", reason=f"{table}.{column}: {reason}")


@router.patch("/fields")
def review(body: ReviewIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """Sets a column's classification by hand. Admin / Security Admin only (server-side). Setting NON_SENSITIVE releases masking for every role, so it
    needs confirm_masking_release=true; without it the change is refused and the refusal is audited."""
    if not has_permission(actor.role, "b1_review"):
        _deny_review(db, actor, body.table, body.column, "refused: role not permitted to review classifications", body.kind)
        raise HTTPException(403, "Your role is not permitted to perform this operation")
    t = _target(body.target)
    if body.kind == "NON_SENSITIVE" and not body.confirm_masking_release:
        _deny_review(db, actor, body.table, body.column, "refused: masking release not confirmed", body.kind)
        raise _err(409, "release_confirmation_required", "Setting NON_SENSITIVE removes masking for every role. Confirm this release to continue.")
    with Guard():
        if body.kind not in KINDS:
            raise ValueError("Unknown classification.")
        out = discover.override(db, t, body.table, body.column, body.kind, actor.username)
    prev = out["previous"]
    prior = f"previously {prev['kind']} ({prev['status']})" if prev else "previously unclassified"
    release = " MASKING RELEASED for every role" if out["released"] else ""
    audit.record(db, request_id=audit.new_request_id(), actor=actor.username, role=_role_label(actor.role), operation="b1_review", purpose="b1_demo",
                 fields={body.column: {"category": body.kind, "strategy": "ALLOW"}}, policy="b1/review", decision="ALLOW",
                 reason=f"classification of {body.table}.{body.column} set to {body.kind} ({prior}).{release}", subject_ref=t.name)
    return out


@router.post("/fields/clear")
def clear_review(body: ClearIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """Removes a manual decision and re-runs the normal detection for that column. Admin / Security Admin only. If the cleared decision protected the
    column and detection now finds nothing sensitive, that is a masking release and needs confirm_masking_release=true."""
    if not has_permission(actor.role, "b1_review"):
        _deny_review(db, actor, body.table, body.column, "clear refused: role not permitted to review classifications")
        raise HTTPException(403, "Your role is not permitted to perform this operation")
    t = _target(body.target)
    try:
        with Guard():
            out = _clear_checked(db, t, body, actor)
    except discover.NoOverride:
        audit.record(db, request_id=audit.new_request_id(), actor=actor.username, role=_role_label(actor.role), operation="b1_review", purpose="b1_demo",
                     fields={body.column: {"category": "-", "strategy": "ALLOW"}}, policy="b1/review", decision="ALLOW",
                     reason=f"clear of {body.table}.{body.column}: no manual override present; nothing changed", subject_ref=t.name)
        raise _err(409, "no_override", "This column has no manual override to clear.") from None
    return out


def _clear_checked(db: Session, t, body: ClearIn, actor: Actor) -> dict:
    """Clear, with the masking-release guard applied to the same detection result that is then written (see discover.clear_override)."""
    try:
        out = discover.clear_override(db, t, body.table, body.column, actor.username, confirm_release=body.confirm_masking_release)
    except discover.ReleaseNeedsConfirmation as e:
        _deny_review(db, actor, body.table, body.column, f"clear refused: would release masking without confirmation (detection would restore {e.restored['kind']})")
        raise _err(409, "release_confirmation_required", "Clearing this decision would remove masking for every role, because detection finds nothing sensitive. Confirm this release to continue.") from None
    prev, res = out["previous"], out["restored"]
    release = " MASKING RELEASED for every role" if out["released"] else ""
    audit.record(db, request_id=audit.new_request_id(), actor=actor.username, role=_role_label(actor.role), operation="b1_review", purpose="b1_demo",
                 fields={body.column: {"category": res["kind"], "strategy": "ALLOW"}}, policy="b1/review", decision="ALLOW",
                 reason=(f"override cleared on {body.table}.{body.column}: previously {prev['kind']} ({prev['status']}, methods {', '.join(prev['methods']) or 'none'}); "
                         f"restored by detection to {res['kind']} ({res['status']}, methods {', '.join(res['methods']) or 'none'}); "
                         f"sampled={'yes' if out['sampled'] else 'no'}; ML supplement {out['ml_supplement']['mode']}.{release}"),
                 subject_ref=t.name)
    return out


STRATEGY_HELP = {"ALLOW": "Real value returned (Admin; also non-sensitive columns).", "PARTIAL": "Partially masked, e.g. 4111-XXXX-XXXX-1111.",
                 "REDACT": "Replaced by [REDACTED].", "HASH": "Keyed hash: stable for joins, not reversible.", "DENY": "Column withheld entirely."}


@router.get("/policy")
def policy_view(actor: Actor = Depends(require("b1_query")), db: Session = Depends(get_session)):
    """The masking policy in force: built-in defaults with any Admin-edited role policies applied, plus the caller's own effective policy."""
    role = mask.normalize_role(actor.role)
    kinds = [k for k in KINDS]
    ov = policy.load(db, actor.username, role)
    return {"roles": list(mask.ROLES), "tags": list(TAGS), "kinds": [{"kind": k, "tag": TAG_OF[k]} for k in kinds],
            "matrix": mask.policy_matrix(kinds, policy.load_roles(db)), "defaults": mask.policy_matrix(kinds), "strategies": STRATEGY_HELP,
            "your_role": role, "yours": {k: {"strategy": mask.strategy_for(role, k, TAG_OF[k], ov), "source": policy.source_for(ov, k)} for k in kinds}}


class PolicyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["user", "role"]
    subject: str = Field(min_length=1, max_length=64)  # a username (scope=user) or Support/Analyst (scope=role)
    kind: str = Field(max_length=32)
    strategy: str = Field(default="", max_length=16)
    note: str = Field(default="", max_length=120)  # the Admin's reason for the change; shown in the audit trail


def _policy_op(db: Session, actor: Actor, body: PolicyIn, reset: bool) -> dict:
    try:
        with Guard():
            out = policy.reset_policy(db, body.scope, body.subject, body.kind, actor.username) if reset else                 policy.set_policy(db, body.scope, body.subject, body.kind, body.strategy, actor.username)
    except HTTPException as e:
        if e.status_code == 404:
            raise _err(404, "unknown_user", "That user does not exist or is inactive.") from None
        raise
    if out["old"] == out["new"]:  # nothing changed for this person, so it is not a policy change and must not appear in the history
        return {**out, "changed": False}
    who = out["display_name"] or out["subject"]
    verb = "reset to default" if reset else "changed"
    audit.record(db, request_id=audit.new_request_id(), actor=actor.username, role=mask.normalize_role(actor.role), operation="b1_policy_change", purpose="b1_demo",
                 fields={out["kind"]: {"category": out["kind"], "strategy": out["new"]}}, policy="b1/policy-edit", decision="ALLOW",
                 reason=f"{verb}: {who} ({out['scope']}) {out['kind']} {out['old']} -> {out['new']}"[:300], subject_ref=out["subject"][:64],
                 detail={"verb": "reset" if reset else "changed", "scope": out["scope"], "subject": out["subject"], "display_name": who, "role": out["role"], "kind": out["kind"],
                         "old": out["old"], "new": out["new"], "note": body.note.strip()})
    return {**out, "changed": True}


@router.put("/policy/overrides")
def set_policy(body: PolicyIn, actor: Actor = Depends(require("b1_policy")), db: Session = Depends(get_session)):
    """Admin-only. Persists a user- or role-level masking strategy; the very next query by that user/role uses it. Audited with old -> new."""
    limiter.check(f"b1p:{actor.username}", 30, 60)
    return _policy_op(db, actor, body, reset=False)


@router.post("/policy/overrides/reset")
def reset_policy(body: PolicyIn, actor: Actor = Depends(require("b1_policy")), db: Session = Depends(get_session)):
    limiter.check(f"b1p:{actor.username}", 30, 60)
    return _policy_op(db, actor, body, reset=True)


@router.get("/policy/overrides")
def policy_overrides(actor: Actor = Depends(require("b1_policy")), db: Session = Depends(get_session)):
    return {"overrides": policy.list_overrides(db)}


@router.get("/policy/users/{username}")
def policy_user(username: str, actor: Actor = Depends(require("b1_policy")), db: Session = Depends(get_session)):
    try:
        with Guard():
            return policy.effective_for_user(db, username)
    except HTTPException as e:
        if e.status_code == 404:
            raise _err(404, "unknown_user", "That user does not exist or is inactive.") from None
        raise


@router.get("/users")
def users(actor: Actor = Depends(require("b1_policy")), db: Session = Depends(get_session)):
    """Accounts that can use the data protection engine, with role and how many Admin-edited policies apply to each. No credentials."""
    counts: dict[str, int] = {}
    for o in policy.list_overrides(db):
        if o["scope"] == "user":
            counts[o["subject"]] = counts.get(o["subject"], 0) + 1
    rows = db.scalars(select(User).where(User.active.is_(True)).order_by(User.id)).all()
    out = []
    for u in rows:
        if u.role not in mask.ROLE_ALIASES:
            continue
        role = mask.ROLE_ALIASES[u.role]
        last = db.scalar(select(AuditEvent).where(AuditEvent.actor == u.username).order_by(AuditEvent.id.desc()).limit(1))
        out.append({"username": u.username, "display_name": u.display_name, "account_role": u.role, "role": role, "custom_policies": counts.get(u.username, 0),
                    "last_activity": last.ts if last else None, "editable": role != "Admin"})
    return {"users": out}


@router.post("/query")
def run_query(body: QueryIn, actor: Actor = Depends(require("b1_query")), db: Session = Depends(get_session)):
    limiter.check(f"b1q:{actor.username}", 60, 60)
    t = _target(body.target)
    with Guard():
        spec = body.spec()
        return q.run_query(db, t, spec, actor.username, actor.role)


@router.post("/compare")
def compare(body: QueryIn, actor: Actor = Depends(require("b1_compare")), db: Session = Depends(get_session)):
    limiter.check(f"b1q:{actor.username}", 60, 60)
    t = _target(body.target)
    with Guard():
        return q.run_compare(db, t, body.spec(), actor.username)


class PreviewIn(QueryIn):
    username: str = Field(min_length=1, max_length=64)


@router.post("/preview")
def preview(body: PreviewIn, actor: Actor = Depends(require("b1_policy")), db: Session = Depends(get_session)):
    """Admin-only: run a query exactly as another user would receive it (their role plus their own policy). Never returns more than that user sees."""
    limiter.check(f"b1q:{actor.username}", 60, 60)
    t = _target(body.target)
    user = db.scalar(select(User).where(User.username == body.username, User.active.is_(True)))
    if user is None or user.role not in mask.ROLE_ALIASES:
        raise _err(404, "unknown_user", "That user does not exist or cannot use the data protection engine.")
    with Guard():
        return q.run_preview(db, t, body.spec(), actor.username, user.username, user.role)


@router.get("/audit")
def b1_audit(limit: int = 25, user: str | None = Query(None, max_length=64), role: str | None = Query(None, max_length=16),
             decision: str | None = Query(None, max_length=16), operation: str | None = Query(None, max_length=32),
             resource: str | None = Query(None, max_length=64), hours: int | None = Query(None, ge=1, le=24 * 90),
             actor: Actor = Depends(require("b1_review")), db: Session = Depends(get_session)):
    """Recent B1 events, filterable by user, role, decision (ALLOW/MASK/DENY), operation, resource (table) and age. Field NAMES and strategies only; never values."""
    stmt = select(AuditEvent).where(AuditEvent.operation.like("b1_%"))
    if user:
        stmt = stmt.where(AuditEvent.actor == user)
    if role:
        stmt = stmt.where(AuditEvent.role == mask.ROLE_ALIASES.get(role, role))
    if decision:
        stmt = stmt.where(AuditEvent.decision == decision.upper())
    if operation:
        stmt = stmt.where(AuditEvent.operation == (operation if operation.startswith("b1_") else f"b1_{operation}"))
    if resource:
        stmt = stmt.where(AuditEvent.subject_ref == resource)
    if hours:
        stmt = stmt.where(AuditEvent.ts > dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours))
    rows = db.scalars(stmt.order_by(AuditEvent.id.desc()).limit(max(1, min(limit, 200)))).all()
    names = {u.username: u.display_name for u in db.scalars(select(User))}
    out = []
    for r in rows:
        h = activity.humanize(r, names)
        out.append({"ts": r.ts, "actor": r.actor, "actor_name": h["actor_name"], "role": r.role, "operation": r.operation, "action": h["action"], "decision": r.decision, "policy": r.policy,
                    "resource": r.subject_ref, "reason": r.reason, "fields": r.fields, "request_id": r.request_id, "why": h["why"], "result": h["result"], "change": h["change"],
                    "field_details": h["fields"]})
    return {"events": out}


def _feed(db, limit, user, hours, decision=None, operation=None, field=None, own_only=False):
    return {"events": activity.feed(db, limit=max(1, min(limit, 100)), user=user, hours=hours, decision=decision, operations=(operation,) if operation else activity.OPERATIONS, field=field, own_only=own_only)}


@router.get("/activity")
def recent_activity(limit: int = 15, user: str | None = Query(None, max_length=64), decision: str | None = Query(None, max_length=16), operation: str | None = Query(None, max_length=32),
                    field: str | None = Query(None, max_length=64), hours: int | None = Query(None, ge=1, le=24 * 90),
                    actor: Actor = Depends(require("b1_review")), db: Session = Depends(get_session)):
    """Admin: meaningful security activity (queries, access attempts, policy changes, reviews, scans, sign-ins) with who / what / why / policy / result."""
    return _feed(db, limit, user, hours, decision, operation, field)


@router.get("/activity/users/{username}")
def user_activity(username: str, limit: int = 25, hours: int | None = Query(None, ge=1, le=24 * 90), actor: Actor = Depends(require("b1_review")), db: Session = Depends(get_session)):
    """Admin: one user's history, including policy changes made to them."""
    u = db.scalar(select(User).where(User.username == username))
    if u is None:
        raise _err(404, "unknown_user", "That user does not exist.")
    return {"user": {"username": u.username, "display_name": u.display_name, "role": _role_label(u.role)}, **_feed(db, limit, username, hours)}


@router.get("/me/activity")
def my_activity(limit: int = 15, actor: Actor = Depends(require("b1_query")), db: Session = Depends(get_session)):
    """Anyone: their OWN recent activity. The server reads the identity from the token; there is no user parameter to change."""
    return _feed(db, limit, actor.username, None, own_only=True)


@router.get("/policy/history")
def policy_history(limit: int = 10, user: str | None = Query(None, max_length=64), kind: str | None = Query(None, max_length=32),
                   actor: Actor = Depends(require("b1_policy")), db: Session = Depends(get_session)):
    """Admin: the latest masking-policy changes, newest first, with old -> new, who changed it, and the reason."""
    return {"changes": activity.policy_changes(db, limit=max(1, min(limit, 50)), user=user, kind=kind)}
