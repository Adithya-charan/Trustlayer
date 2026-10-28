"""The single protected-access pipeline:
classification -> risk -> policy -> (execute) -> mask -> explain -> audit."""
import datetime as dt

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import logger as audit
from app.core.config import get_settings
from app.core.security import Actor
from app.database.models import Customer, FieldClassification
from app.masking.engine import mask_row
from app.policies import engine as policy_engine
from app.policies import store as policy_store
from app.policies.sql_gateway import ParsedQuery
from app.risk.detector import assess_risk
from app.scanner.classifier import sensitivity_of

COLUMNS = list(Customer.__table__.columns.keys())


def load_categories(db: Session) -> dict[str, str]:
    return {r.column_name: r.category for r in db.scalars(select(FieldClassification).where(FieldClassification.table_name == "customers"))}


def _coerce(column: str, value):
    col = Customer.__table__.columns[column]
    py = col.type.python_type
    if py is dt.date:
        return dt.date.fromisoformat(value) if isinstance(value, str) else value
    if py is int and not isinstance(value, int):
        raise ValueError("expected integer")
    if py is float and not isinstance(value, (int, float)):
        raise ValueError("expected number")
    if py is str and not isinstance(value, str):
        raise ValueError("expected text")
    return value


def _trace(request_id, pd, risk, fields):
    return {
        "request_id": request_id,
        "decision": pd.decision,
        "policy": pd.policy,
        "reason": pd.reason,
        "denied_fields": pd.denied_fields,
        "field_plan": {f: {"category": p["category"], "sensitivity": sensitivity_of(p["category"]), "strategy": p["strategy"]} for f, p in pd.plan.items()},
        "risk": {"score": risk.score, "signals": risk.signals, "response": risk.response},
    }


def run_query(db: Session, actor: Actor, purpose: str, pq: ParsedQuery) -> dict:
    settings = get_settings()
    request_id = audit.new_request_id()
    cats = load_categories(db)
    if not cats:
        raise HTTPException(409, "No field classifications yet. A security admin must run a scan first.")

    columns = COLUMNS if pq.star else pq.columns
    unknown = [c for c in columns + [f[0] for f in pq.filters] + ([pq.order_by[0]] if pq.order_by else []) if c not in cats]
    if unknown:
        raise HTTPException(400, "Query references unknown or unclassified columns.")

    fields = {c: cats[c] for c in columns}
    subject = next((f"customer:{v}" for c, op, v in pq.filters if c == "id" and op == "="), None)
    risk = assess_risk(db, actor.username, columns, subject, settings)
    table = policy_store.load_table(db)
    pd = policy_engine.evaluate(actor.role, purpose, fields, risk.elevated and risk.response != "BLOCK", table)

    def deny(status: int, reason: str, response: str | None = None):
        audit.record(db, request_id=request_id, actor=actor.username, role=actor.role, operation="query", purpose=purpose,
                     fields=pd.plan, policy=pd.policy, decision="DENY", reason=reason, subject_ref=subject,
                     risk_score=risk.score, risk_signals=risk.signals, risk_response=response or risk.response)
        raise HTTPException(status, {"message": reason, "request_id": request_id})

    if risk.response == "BLOCK":
        for s in risk.signals:
            audit.security_event(db, request_id=request_id, actor=actor.username, rule=s["rule"], severity="HIGH", detail=s["detail"], response="BLOCK")
        deny(429, "Request blocked: repeated suspicious access signals. A security event was recorded.")
    elif risk.response == "ELEVATED_MASKING":
        for s in risk.signals:
            audit.security_event(db, request_id=request_id, actor=actor.username, rule=s["rule"], severity="MEDIUM", detail=s["detail"], response="ELEVATED_MASKING")

    if pd.decision == "DENY":
        deny(403, pd.reason)

    # Filtering/sorting on a column must not reveal more than the output may show.
    probe_cols = [f[0] for f in pq.filters] + ([pq.order_by[0]] if pq.order_by else [])
    probe = policy_engine.evaluate(actor.role, purpose, {c: cats[c] for c in probe_cols}, risk.elevated, table) if probe_cols else None
    if probe and any(p["strategy"] != "ALLOW" for p in probe.plan.values()):
        deny(403, "Filtering or sorting on a protected column is not permitted for this role and purpose.")

    stmt = select(*[getattr(Customer, c) for c in columns])
    try:
        for c, op, v in pq.filters:
            col, v = getattr(Customer, c), _coerce(c, v)
            stmt = stmt.where({"=": col == v, "!=": col != v, ">": col > v, ">=": col >= v, "<": col < v, "<=": col <= v}[op])
        if pq.order_by:
            oc = getattr(Customer, pq.order_by[0])
            stmt = stmt.order_by(oc.desc() if pq.order_by[1] else oc)
        stmt = stmt.limit(pq.limit)
        raw_rows = [dict(r) for r in db.execute(stmt).mappings()]
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid filter value for column type.") from None

    rows = [mask_row(r, pd.plan) for r in raw_rows]
    audit.record(db, request_id=request_id, actor=actor.username, role=actor.role, operation="query", purpose=purpose,
                 fields=pd.plan, policy=pd.policy, decision=pd.decision, reason=pd.reason, subject_ref=subject,
                 risk_score=risk.score, risk_signals=risk.signals, risk_response=risk.response)
    return {"rows": rows, "row_count": len(rows), "trace": _trace(request_id, pd, risk, fields)}
