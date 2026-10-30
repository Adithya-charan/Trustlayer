import datetime as dt

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.pipeline import run_query
from app.audit import logger as audit
from app.core.config import get_settings
from app.core.security import Actor, automation_auth, create_token, current_actor, limiter, require, verify_password
from app.database.models import AuditEvent, Customer, FieldClassification, ScanRun, SecurityEvent, User, WorkflowRun
from app.database.session import db_status, get_session
from app.insurance import calculator
from app.minimization import service as minimization
from app.policies import engine as policy_engine
from app.policies import store as policy_store
from app.policies.rules import POLICY_TABLE, PURPOSES
from app.policies.sql_gateway import UnsupportedQuery, parse_query
from app.risk.detector import assess_risk
from app.scanner import schema_inspector
from app.scanner.classifier import CATEGORIES, sensitivity_of

router = APIRouter(prefix="/api")


# ---------- health / auth ----------
@router.get("/health")
def health():
    s = get_settings()
    return {"status": "ok", "env": s.app_env, "database": db_status(), "config_ok": not s.config_problems(),
            "config_problems": s.config_problems(), "data": "synthetic demo data"}


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_session)):
    limiter.check(f"login:{body.username.lower()}", 10, 60)
    user = db.scalar(select(User).where(User.username == body.username, User.active.is_(True)))
    if not user or not verify_password(body.password, user.password_hash):
        if user:  # an unknown username is not recorded: the audit trail must not be fillable with arbitrary strings
            audit.record(db, request_id=audit.new_request_id(), actor=user.username, role=user.role, operation="auth_login", purpose="auth", fields={}, policy="auth/login",
                         decision="DENY", reason="sign-in refused: wrong password")
        raise HTTPException(401, "Invalid username or password")
    audit.record(db, request_id=audit.new_request_id(), actor=user.username, role=user.role, operation="auth_login", purpose="auth", fields={}, policy="auth/login",
                 decision="ALLOW", reason="signed in")
    return {"token": create_token(user.username, user.role), "user": {"username": user.username, "role": user.role, "display_name": user.display_name}}


@router.get("/auth/demo-users")
def demo_users(db: Session = Depends(get_session)):
    """Usernames/roles of the synthetic demo accounts (no secrets)."""
    return [{"username": u.username, "display_name": u.display_name, "role": u.role} for u in db.scalars(select(User).order_by(User.id))]


@router.get("/auth/me")
def me(actor: Actor = Depends(current_actor)):
    return {"username": actor.username, "role": actor.role}


# ---------- fields / scans ----------
def _field_out(f: FieldClassification) -> dict:
    return {"id": f.id, "table": f.table_name, "column": f.column_name, "data_type": f.data_type,
            "detected_category": f.detected_category, "category": f.category, "overridden": f.override_category is not None,
            "sensitivity": sensitivity_of(f.category), "confidence": f.confidence, "rationale": f.rationale, "reviewed_by": f.reviewed_by}


def _scan_out(s: ScanRun | None) -> dict | None:
    if s is None:
        return None
    return {"id": s.id, "status": s.status, "triggered_by": s.triggered_by, "started_at": s.started_at, "finished_at": s.finished_at,
            "fields_scanned": s.fields_scanned, "sensitive_found": s.sensitive_found, "presidio_used": s.presidio_used, "error": s.error,
            "source": s.source, "audit_request_id": s.request_id, "mode": "synchronous"}


class ScanIn(BaseModel):
    source: str = Field("customers", max_length=64)


def _do_scan(db: Session, who: str, role: str, source: str, key: str | None = None) -> dict:
    request_id = audit.new_request_id()
    try:
        scan = schema_inspector.run_scan(db, triggered_by=who, idempotency_key=key, source=source, request_id=request_id)
    except ValueError:
        raise HTTPException(422, "Unknown data source") from None
    if scan.request_id == request_id:  # a repeated idempotent trigger returns the original scan and records no second audit event
        audit.record(db, request_id=request_id, actor=who, role=role, operation="scan", purpose="security_admin", fields={},
                     policy="security_admin/scan", decision="ALLOW" if scan.status == "COMPLETED" else "DENY",
                     reason=f"scan of '{source}' {scan.status.lower()}: {scan.sensitive_found}/{scan.fields_scanned} sensitive fields")
    return _scan_out(scan)


@router.get("/sources")
def list_sources(actor: Actor = Depends(require("view_dashboard")), db: Session = Depends(get_session)):
    out = []
    for key, model in schema_inspector.SCAN_TARGETS.items():
        last = db.scalar(select(ScanRun).where(ScanRun.source == key).order_by(ScanRun.id.desc()).limit(1))
        out.append({"id": key, "name": "Customers (synthetic demo data)", "table": key, "records": db.scalar(select(func.count()).select_from(model)) or 0,
                    "columns": len(model.__table__.columns), "last_scan": _scan_out(last)})
    return out


@router.get("/scans")
def list_scans(limit: int = 20, actor: Actor = Depends(require("view_dashboard")), db: Session = Depends(get_session)):
    rows = db.scalars(select(ScanRun).order_by(ScanRun.id.desc()).limit(max(1, min(limit, 100)))).all()
    return [_scan_out(r) for r in rows]


@router.post("/scans")
def start_scan(body: ScanIn | None = None, actor: Actor = Depends(require("scan")), db: Session = Depends(get_session)):
    limiter.check(f"scan:{actor.username}", 5, 60)
    return _do_scan(db, actor.username, actor.role, (body.source if body else "customers"))


@router.get("/fields")
def list_fields(category: str | None = None, sensitivity: str | None = None, source: str | None = None, q: str | None = None,
                actor: Actor = Depends(require("view_dashboard")), db: Session = Depends(get_session)):
    stmt = select(FieldClassification).order_by(FieldClassification.id)
    if source:
        stmt = stmt.where(FieldClassification.table_name == source)
    out = [_field_out(r) for r in db.scalars(stmt).all()]
    if category:
        out = [f for f in out if f["category"] == category]
    if sensitivity:
        out = [f for f in out if f["sensitivity"] == sensitivity]
    if q:
        out = [f for f in out if q.lower() in f["column"].lower()]
    return out


@router.get("/fields/{field_id}")
def field_detail(field_id: int, actor: Actor = Depends(require("view_dashboard")), db: Session = Depends(get_session)):
    f = db.get(FieldClassification, field_id)
    if not f:
        raise HTTPException(404, "Field not found")
    auditor = policy_engine.has_permission(actor.role, "view_audit")
    outcomes = []
    for (role, purpose), rules in sorted(policy_store.load_table(db).items()):
        if not auditor and role != actor.role:
            continue  # non-auditors only see how policy treats their own role
        outcomes.append({"role": role, "purpose": purpose, "strategy": rules.get(f.category, "DENY")})
    detail = _field_out(f)
    detail["policy_outcomes"] = outcomes
    detail["evidence"] = {"signals": f.rationale, "detected_category": f.detected_category, "confidence": f.confidence,
                          "note": "Evidence is rationale text and match ratios only; sampled values are never stored or shown."}
    detail["related_audit_events"] = []
    if auditor:
        for e in db.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(400)):
            if f.column_name in e.fields:
                detail["related_audit_events"].append(_audit_out(e))
            if len(detail["related_audit_events"]) >= 10:
                break
        scan = db.get(ScanRun, f.last_scan_id) if f.last_scan_id else None
        detail["scan"] = _scan_out(scan)
    return detail


class ReviewIn(BaseModel):
    category: str


@router.patch("/fields/{field_id}")
def review_field(field_id: int, body: ReviewIn, actor: Actor = Depends(require("review_field")), db: Session = Depends(get_session)):
    if body.category not in CATEGORIES:
        raise HTTPException(422, "Unknown category")
    f = db.get(FieldClassification, field_id)
    if not f:
        raise HTTPException(404, "Field not found")
    f.override_category = None if body.category == f.detected_category else body.category
    f.reviewed_by = actor.username
    db.commit()
    audit.record(db, request_id=audit.new_request_id(), actor=actor.username, role=actor.role, operation="review_field", purpose="audit_review",
                 fields={f.column_name: {"category": f.category, "strategy": "ALLOW"}}, policy="classification-review", decision="ALLOW",
                 reason=f"classification of '{f.column_name}' set to {f.category}")
    return _field_out(f)


# ---------- policies ----------
@router.get("/policies")
def list_policies(actor: Actor = Depends(require("view_policies")), db: Session = Depends(get_session)):
    mine = [{"purpose": p, "rules": rules} for (role, p), rules in sorted(policy_store.load_table(db).items()) if role == actor.role]
    return {"role": actor.role, "purposes": mine, "all_purposes": list(PURPOSES),
            "risk": {k: v for k, v in get_settings().model_dump().items() if k.startswith("risk_")}}


# ---------- protected query ----------
class QueryIn(BaseModel):
    sql: str = Field(max_length=500)
    purpose: str


@router.post("/query")
def query(body: QueryIn, actor: Actor = Depends(require("query")), db: Session = Depends(get_session)):
    limiter.check(f"query:{actor.username}", 60, 60)
    if body.purpose not in PURPOSES:
        raise HTTPException(422, "Unknown purpose")
    try:
        pq = parse_query(body.sql)
    except UnsupportedQuery as exc:
        audit.record(db, request_id=audit.new_request_id(), actor=actor.username, role=actor.role, operation="query", purpose=body.purpose,
                     fields={}, policy="sql-gateway", decision="DENY", reason=f"unsupported query shape: {exc}")
        raise HTTPException(400, {"message": str(exc), "supported": "SELECT cols FROM customers [WHERE col op literal AND ...] [ORDER BY col] [LIMIT n<=50]"}) from None
    return run_query(db, actor, body.purpose, pq)


# ---------- insurance ----------
class AssessIn(BaseModel):
    customer_id: int = Field(ge=1)
    assumptions: dict | None = None


@router.post("/insurance/assess")
def assess(body: AssessIn, actor: Actor = Depends(require("insurance_assess")), db: Session = Depends(get_session)):
    limiter.check(f"assess:{actor.username}", 30, 60)
    purpose, request_id = "insurance_assessment", audit.new_request_id()
    subject = f"customer:{body.customer_id}"
    risk = assess_risk(db, actor.username, list(minimization.REQUIRED_INPUTS), subject, get_settings())

    def fail(status, msg, decision="DENY", pd=None):
        audit.record(db, request_id=request_id, actor=actor.username, role=actor.role, operation="insurance_assess", purpose=purpose,
                     fields=pd.plan if pd else {}, policy=f"{actor.role}/{purpose}", decision=decision, reason=msg, subject_ref=subject,
                     risk_score=risk.score, risk_signals=risk.signals, risk_response=risk.response)
        raise HTTPException(status, {"message": msg, "request_id": request_id})

    if risk.response == "BLOCK":
        fail(429, "Request blocked: repeated suspicious access signals.")
    try:
        payload, report = minimization.build_payload(db, body.customer_id, actor.role, purpose, risk.elevated)
    except minimization.MinimizationError as exc:
        fail(403, str(exc))
    except LookupError:
        fail(404, "Customer not found", "DENY")
    try:
        result = calculator.assess(payload, body.assumptions)
    except calculator.InputError as exc:
        fail(422, str(exc), "DENY", report["decision"])

    pd = report["decision"]
    audit.record(db, request_id=request_id, actor=actor.username, role=actor.role, operation="insurance_assess", purpose=purpose,
                 fields={k: {"category": v["category"], "strategy": "ALLOW"} for k, v in ((i["input"], i) for i in report["inputs_used"])},
                 policy=pd.policy, decision="ALLOW", reason="Assessment completed with minimized inputs", subject_ref=subject,
                 risk_score=risk.score, risk_signals=risk.signals, risk_response=risk.response)
    return {"request_id": request_id, "result": result, "minimization": {"inputs_used": report["inputs_used"], "attributes_excluded": report["attributes_excluded"],
            "note": "Only the listed inputs were sent to the assessment service. Exact values are not echoed back."}}


# ---------- audit / decisions / security events ----------
def _audit_out(e: AuditEvent) -> dict:
    return {"request_id": e.request_id, "ts": e.ts, "actor": e.actor, "role": e.role, "operation": e.operation, "purpose": e.purpose,
            "subject_ref": e.subject_ref, "fields": e.fields, "policy": e.policy, "decision": e.decision, "reason": e.reason,
            "risk_score": e.risk_score, "risk_signals": e.risk_signals, "risk_response": e.risk_response}


@router.get("/audit")
def audit_list(limit: int = 25, offset: int = 0, actor_name: str | None = Query(None, alias="actor"), decision: str | None = None,
               operation: str | None = None, purpose: str | None = None, role: str | None = None, q: str | None = None,
               since_days: int | None = Query(None, ge=1, le=365), min_risk: int | None = Query(None, ge=0),
               actor: Actor = Depends(require("view_audit")), db: Session = Depends(get_session)):
    conds = []
    if actor_name:
        conds.append(AuditEvent.actor == actor_name)
    if decision:
        conds.append(AuditEvent.decision == decision)
    if operation:
        conds.append(AuditEvent.operation == operation)
    if purpose:
        conds.append(AuditEvent.purpose == purpose)
    if role:
        conds.append(AuditEvent.role == role)
    if min_risk:
        conds.append(AuditEvent.risk_score >= min_risk)
    if since_days:
        conds.append(AuditEvent.ts >= dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=since_days))
    if q:
        like = f"%{q.strip()[:60]}%"
        conds.append(or_(AuditEvent.request_id.ilike(like), AuditEvent.actor.ilike(like), AuditEvent.policy.ilike(like), AuditEvent.reason.ilike(like)))
    limit, offset = max(1, min(limit, 100)), max(0, offset)
    total = db.scalar(select(func.count()).select_from(AuditEvent).where(*conds)) or 0
    rows = db.scalars(select(AuditEvent).where(*conds).order_by(AuditEvent.id.desc()).offset(offset).limit(limit)).all()
    counts = dict(db.execute(select(AuditEvent.decision, func.count()).where(*conds).group_by(AuditEvent.decision)).all())
    return {"summary": counts, "total": total, "offset": offset, "limit": limit, "events": [_audit_out(r) for r in rows]}


@router.get("/decisions/{request_id}")
def decision_trace(request_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    e = db.scalar(select(AuditEvent).where(AuditEvent.request_id == request_id))
    if not e:
        raise HTTPException(404, "Decision not found")
    if e.actor != actor.username and not policy_engine.has_permission(actor.role, "view_audit"):
        raise HTTPException(403, "You may only view traces of your own requests")
    return _audit_out(e)


@router.get("/my-requests")
def my_requests(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    rows = db.scalars(select(AuditEvent).where(AuditEvent.actor == actor.username).order_by(AuditEvent.id.desc()).limit(15)).all()
    return [_audit_out(r) for r in rows]


@router.get("/security-events")
def security_events(actor: Actor = Depends(require("view_security_events")), db: Session = Depends(get_session)):
    rows = db.scalars(select(SecurityEvent).order_by(SecurityEvent.id.desc()).limit(25)).all()
    return [{"id": r.id, "ts": r.ts, "actor": r.actor, "rule": r.rule, "severity": r.severity, "detail": r.detail, "response": r.response, "request_id": r.request_id} for r in rows]


# ---------- dashboard ----------
@router.get("/dashboard")
def dashboard(actor: Actor = Depends(require("view_dashboard")), db: Session = Depends(get_session)):
    fields = db.scalars(select(FieldClassification)).all()
    by_sens: dict[str, int] = {}
    for f in fields:
        by_sens[sensitivity_of(f.category)] = by_sens.get(sensitivity_of(f.category), 0) + 1
    last_scan = db.scalar(select(ScanRun).order_by(ScanRun.id.desc()).limit(1))
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
    decisions = dict(db.execute(select(AuditEvent.decision, func.count()).where(AuditEvent.ts >= since).group_by(AuditEvent.decision)).all())
    sec_24h = db.scalar(select(func.count()).select_from(SecurityEvent).where(SecurityEvent.ts >= since)) or 0
    runs = db.scalars(select(WorkflowRun).order_by(WorkflowRun.id.desc()).limit(8)).all()
    return {
        "source": {"name": "customers (synthetic demo data)", "records": db.scalar(select(func.count()).select_from(Customer)) or 0},
        "fields": {"total": len(fields), "sensitive": sum(1 for f in fields if sensitivity_of(f.category) != "LOW"), "by_sensitivity": by_sens,
                   "overridden": sum(1 for f in fields if f.override_category)},
        "last_scan": _scan_out(last_scan),
        "decisions_24h": decisions,
        "security_events_24h": sec_24h,
        "workflows": [{"workflow": r.workflow, "status": r.status, "attempt": r.attempt, "detail": r.detail, "ts": r.ts} for r in runs],
    }


# ---------- automation (n8n) : authenticated by shared secret; orchestration only ----------
@router.post("/automation/scans")
def automation_scan(idempotency_key: str | None = Header(default=None, max_length=128), who: str = Depends(automation_auth), db: Session = Depends(get_session)):
    limiter.check("automation-scan", 20, 60)
    return _do_scan(db, who, "automation", "customers", idempotency_key)


@router.get("/automation/security-events")
def automation_security_events(since_id: int = 0, severity: str | None = Query(None, pattern="^(HIGH|MEDIUM)$"), who: str = Depends(automation_auth),
                               db: Session = Depends(get_session)):
    """Minimized alert metadata: no field values. Optional severity filter (HIGH = blocked requests)."""
    stmt = select(SecurityEvent).where(SecurityEvent.id > since_id)
    if severity:
        stmt = stmt.where(SecurityEvent.severity == severity)
    rows = db.scalars(stmt.order_by(SecurityEvent.id).limit(50)).all()
    return [{"id": r.id, "ts": r.ts, "rule": r.rule, "severity": r.severity, "response": r.response, "actor": r.actor} for r in rows]


@router.get("/automation/summary")
def automation_summary(hours: int = Query(24, ge=1, le=168), who: str = Depends(automation_auth), db: Session = Depends(get_session)):
    """Aggregate counts for a bounded period. No records, no values."""
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(hours=hours)
    return {
        "window_hours": hours,
        "period_start": start,
        "period_end": end,
        "decisions": dict(db.execute(select(AuditEvent.decision, func.count()).where(AuditEvent.ts >= start).group_by(AuditEvent.decision)).all()),
        "operations": dict(db.execute(select(AuditEvent.operation, func.count()).where(AuditEvent.ts >= start).group_by(AuditEvent.operation)).all()),
        "security_events": dict(db.execute(select(SecurityEvent.severity, func.count()).where(SecurityEvent.ts >= start).group_by(SecurityEvent.severity)).all()),
        "scans": dict(db.execute(select(ScanRun.status, func.count()).where(ScanRun.started_at >= start).group_by(ScanRun.status)).all()),
        "sensitive_fields": sum(1 for f in db.scalars(select(FieldClassification)) if sensitivity_of(f.category) != "LOW"),
        "generated_at": end,
    }


class WorkflowRunIn(BaseModel):
    workflow: str = Field(max_length=64)
    status: str = Field(pattern="^(SUCCESS|FAILED|RETRYING)$")
    attempt: int = Field(1, ge=1, le=10)
    detail: str = Field("", max_length=300)


@router.post("/automation/workflow-runs")
def report_workflow_run(body: WorkflowRunIn, idempotency_key: str | None = Header(default=None, max_length=128),
                        who: str = Depends(automation_auth), db: Session = Depends(get_session)):
    if idempotency_key:
        existing = db.scalar(select(WorkflowRun).where(WorkflowRun.idempotency_key == idempotency_key))
        if existing:
            return {"id": existing.id, "duplicate": True}
    run = WorkflowRun(workflow=body.workflow, status=body.status, attempt=body.attempt, detail=audit.scrub(body.detail), idempotency_key=idempotency_key)
    db.add(run)
    db.commit()
    return {"id": run.id, "duplicate": False}
