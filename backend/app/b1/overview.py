"""Real, live metrics for the Overview page: every number is computed from the connected backends, the stored classification and the audit trail.
Nothing here is hard-coded. Slow-moving facts (table row counts, backend health) are cached for a short time so the page never re-scans a database."""
import datetime as dt
import threading
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.b1 import activity, mask, policy
from app.b1.detect import TAG_OF
from app.b1.targets import Target
from app.database.models import AuditEvent, B1FieldTag

TTL = 30.0
_lock = threading.Lock()
_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str, fn):
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < TTL:
            return hit[1]
    value = fn()  # outside the lock: a slow database must not block other requests
    with _lock:
        _cache[key] = (time.monotonic(), value)
    return value


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def counts(target: Target) -> list[dict]:
    def build():
        return [{"name": n, "rows": target.row_count(t)} for n, t in sorted(target.tables().items())]

    return _cached(f"rows:{id(target)}", build)


def build(db: Session, target: Target) -> dict:
    per_table = counts(target)
    tags = db.scalars(select(B1FieldTag).where(B1FieldTag.target == target.name)).all()
    kinds = {t.kind for t in tags if TAG_OF.get(t.kind, t.tag) != "NON_SENSITIVE"}
    by_tag: dict[str, int] = {}
    sensitive = protected = 0
    role_ov = policy.load_roles(db)
    for t in tags:
        tag = TAG_OF.get(t.kind, t.tag)
        if tag == "NON_SENSITIVE":
            continue
        sensitive += 1
        by_tag[tag] = by_tag.get(tag, 0) + 1
        if any(mask.strategy_for(r, t.kind, tag, role_ov.get(r)) != "ALLOW" for r in policy.EDITABLE_ROLES):
            protected += 1
    custom = policy.list_overrides(db)
    q = select(AuditEvent.decision, func.count()).where(AuditEvent.operation == "b1_query")
    total = {d: n for d, n in db.execute(q.group_by(AuditEvent.decision))}
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
    recent = {d: n for d, n in db.execute(q.where(AuditEvent.ts > since).group_by(AuditEvent.decision))}
    events = db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.operation.like("b1_%"))) or 0
    changes = db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.operation == "b1_policy_change")) or 0
    last_scan = max((t.updated_at for t in tags), default=None)
    return {
        "target": target.name,
        "dataset": {"tables": len(per_table), "records": sum(t["rows"] for t in per_table), "per_table": per_table},
        "discovery": {"scanned": bool(tags), "columns": len(tags), "sensitive_fields": sensitive, "by_tag": by_tag, "embedded_pii_fields": sum(1 for t in tags if t.kind == "FREE_TEXT_PII"),
                      "needs_review": sum(1 for t in tags if t.status == "uncertain" and not t.override), "last_scan": last_scan},
        "protection": {"protected_fields": protected, "active_rules": len(policy.EDITABLE_ROLES) * len(kinds), "custom_policies": len(custom)},
        "audit": {"events": events, "total": sum(total.values()), "allowed": total.get("ALLOW", 0), "masked": total.get("MASK", 0), "denied": total.get("DENY", 0),
                  "policy_changes": changes, "last_24h": recent, "today": activity.today(db)},
    }
