"""Editable B1 masking policy. Resolution order, per classification kind: the user's own policy > the role's policy > the built-in default
(app.b1.mask.default_strategy). Admin is never restricted and non-sensitive columns are never masked, so only Support/Analyst subjects and sensitive
kinds can be edited. Every change is stored here and audited by the API (who, whom, which kind, old -> new); policy rows hold no data values."""
import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.b1 import mask
from app.b1.detect import KINDS, TAG_OF
from app.database.models import B1RolePolicy, B1UserPolicy, User

EDITABLE_ROLES = ("Support", "Analyst")
Overrides = dict  # kind -> (strategy, "user" | "role")


def editable_kinds() -> list[str]:
    return [k for k in KINDS if TAG_OF[k] != "NON_SENSITIVE"]


def load_roles(db: Session) -> dict[str, Overrides]:
    out: dict[str, Overrides] = {r: {} for r in EDITABLE_ROLES}
    for row in db.scalars(select(B1RolePolicy)):
        if row.role in out and row.kind in KINDS:
            out[row.role][row.kind] = (row.strategy, "role")
    return out


def load(db: Session, username: str, role: str) -> Overrides:
    """Overrides that apply to this user: role policy, then the user's own on top."""
    role = mask.normalize_role(role)
    if role == "Admin":
        return {}
    out = dict(load_roles(db).get(role, {}))
    for row in db.scalars(select(B1UserPolicy).where(B1UserPolicy.username == username)):
        if row.kind in KINDS:
            out[row.kind] = (row.strategy, "user")
    return out


def source_for(overrides: Overrides | None, kind: str) -> str:
    return overrides[kind][1] if overrides and kind in overrides else "default"


def describe(role: str, source: str, username: str) -> str:
    """The policy label recorded in the audit trail for a query."""
    return {"user": f"b1/{role}/user:{username}", "role": f"b1/{role}/custom"}.get(source, f"b1/{role}")


def _subject(db: Session, scope: str, subject: str) -> tuple[str, str | None]:
    """Validates the subject and returns (role, display_name). User subjects must be an active non-Admin account."""
    if scope == "role":
        if subject not in EDITABLE_ROLES:
            raise ValueError("Only the Support and Analyst roles have editable policies; Admin always sees real values.")
        return subject, None
    user = db.scalar(select(User).where(User.username == subject, User.active.is_(True)))
    if user is None:
        raise LookupError("unknown user")
    role = mask.normalize_role(user.role)
    if role == "Admin":
        raise ValueError("Admin accounts always see real values; their policy cannot be edited.")
    return role, user.display_name


def _check(kind: str, strategy: str) -> None:
    if kind not in editable_kinds():
        raise ValueError("Unknown or non-sensitive classification; only sensitive kinds have a masking policy.")
    if strategy not in mask.STRATEGIES:
        raise ValueError("Unknown masking strategy.")


def current(db: Session, scope: str, subject: str, kind: str) -> tuple[str, str]:
    """(strategy, source) in force for the subject and kind."""
    role, _ = _subject(db, scope, subject)
    ov = load(db, subject, role) if scope == "user" else load_roles(db).get(role, {})
    return mask.strategy_for(role, kind, TAG_OF[kind], ov), source_for(ov, kind)


def set_policy(db: Session, scope: str, subject: str, kind: str, strategy: str, admin: str) -> dict:
    _check(kind, strategy)
    role, display = _subject(db, scope, subject)
    old, _src = current(db, scope, subject, kind)
    model, key = (B1UserPolicy, B1UserPolicy.username) if scope == "user" else (B1RolePolicy, B1RolePolicy.role)
    row = db.scalar(select(model).where(key == subject, model.kind == kind))
    now = dt.datetime.now(dt.timezone.utc)
    if row is None:
        row = model(**{"username" if scope == "user" else "role": subject}, kind=kind, strategy=strategy, updated_by=admin, updated_at=now)
        db.add(row)
    else:
        row.strategy, row.updated_by, row.updated_at = strategy, admin, now
    db.commit()
    return {"scope": scope, "subject": subject, "display_name": display, "role": role, "kind": kind, "old": old, "new": strategy}


def reset_policy(db: Session, scope: str, subject: str, kind: str, admin: str) -> dict:
    if kind not in editable_kinds():
        raise ValueError("Unknown or non-sensitive classification.")
    role, display = _subject(db, scope, subject)
    old, _src = current(db, scope, subject, kind)
    model, key = (B1UserPolicy, B1UserPolicy.username) if scope == "user" else (B1RolePolicy, B1RolePolicy.role)
    row = db.scalar(select(model).where(key == subject, model.kind == kind))
    if row is not None:
        db.delete(row)
        db.commit()
    new, _ = current(db, scope, subject, kind)
    return {"scope": scope, "subject": subject, "display_name": display, "role": role, "kind": kind, "old": old, "new": new}


def list_overrides(db: Session) -> list[dict]:
    names = {u.username: u.display_name for u in db.scalars(select(User))}
    rows = [{"scope": "role", "subject": r.role, "display_name": None, "kind": r.kind, "strategy": r.strategy, "updated_by": r.updated_by, "updated_at": r.updated_at}
            for r in db.scalars(select(B1RolePolicy).order_by(B1RolePolicy.role, B1RolePolicy.kind))]
    rows += [{"scope": "user", "subject": r.username, "display_name": names.get(r.username), "kind": r.kind, "strategy": r.strategy, "updated_by": r.updated_by,
              "updated_at": r.updated_at} for r in db.scalars(select(B1UserPolicy).order_by(B1UserPolicy.username, B1UserPolicy.kind))]
    return rows


def effective_for_user(db: Session, username: str) -> dict:
    """The user's full effective policy: kind -> {strategy, source, default}."""
    role, display = _subject(db, "user", username)
    ov = load(db, username, role)
    return {"username": username, "display_name": display, "role": role,
            "policy": {k: {"strategy": mask.strategy_for(role, k, TAG_OF[k], ov), "source": source_for(ov, k), "default": mask.default_strategy(role, k, TAG_OF[k])}
                       for k in editable_kinds()}}
