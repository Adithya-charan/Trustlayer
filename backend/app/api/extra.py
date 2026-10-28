"""Policy management, metrics, risk, structured access requests, insurance helpers,
automation visibility and settings. All authorization is enforced here, server-side."""
import datetime as dt
import json
import pathlib

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import __version__
from app.api.pipeline import COLUMNS, load_categories, run_query
from app.audit import logger as audit
from app.core.config import get_settings
from app.core.security import Actor, automation_auth, current_actor, limiter, require
from app.database.models import (AlertDelivery, AuditEvent, AuditReport, Customer, FieldClassification, Policy, ScanRun,
                                 SecurityEvent, WorkflowRun)
from app.database.session import db_status, get_session
from app.insurance import calculator
from app.masking.strategies import STRATEGIES, apply_strategy
from app.minimization.service import REQUIRED_INPUTS
from app.policies import engine as policy_engine
from app.policies import store as policy_store
from app.policies.rules import PURPOSES, ROLES
from app.policies.sql_gateway import ParsedQuery
from app.scanner.classifier import CATEGORIES, sensitivity_of

router = APIRouter(prefix="/api")
UTC = dt.timezone.utc


def _aware(ts: dt.datetime) -> dt.datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def _record(db, actor: Actor, operation: str, purpose: str, reason: str, policy: str, fields: dict | None = None, decision: str = "ALLOW"):
    audit.record(db, request_id=audit.new_request_id(), actor=actor.username, role=actor.role, operation=operation, purpose=purpose,
                 fields=fields or {}, policy=policy, decision=decision, reason=reason)


# ================= policies =================
def _policy_out(p: Policy) -> dict:
    return {"id": p.id, "identifier": p.identifier, "name": p.name, "role": p.role, "purpose": p.purpose, "category": p.category,
            "sensitivity": sensitivity_of(p.category), "strategy": p.strategy, "decision": "DENY" if p.strategy == "DENY" else ("ALLOW" if p.strategy == "ALLOW" else "MASK"),
            "enabled": p.enabled, "updated_by": p.updated_by, "updated_at": p.updated_at}


@router.get("/policies/all")
def policies_all(role: str | None = None, purpose: str | None = None, enabled: bool | None = None, actor: Actor = Depends(require("view_all_policies")),
                 db: Session = Depends(get_session)):
    stmt = select(Policy).order_by(Policy.role, Policy.purpose, Policy.id)
    if role:
        stmt = stmt.where(Policy.role == role)
    if purpose:
        stmt = stmt.where(Policy.purpose == purpose)
    if enabled is not None:
        stmt = stmt.where(Policy.enabled.is_(enabled))
    return {"items": [_policy_out(p) for p in db.scalars(stmt)], "roles": list(ROLES), "purposes": list(PURPOSES),
            "categories": list(CATEGORIES), "strategies": [s for s in STRATEGIES],
            "can_manage": policy_engine.has_permission(actor.role, "manage_policies"),
            "note": "Absent or disabled rules mean DENY. Critical identifiers can never be set to ALLOW."}


class PolicyIn(BaseModel):
    role: str
    purpose: str
    category: str
    strategy: str
    enabled: bool = True


class PolicyPatch(BaseModel):
    strategy: str | None = None
    enabled: bool | None = None


@router.post("/policies", status_code=201)
def policy_create(body: PolicyIn, actor: Actor = Depends(require("manage_policies")), db: Session = Depends(get_session)):
    err = policy_store.validate_rule(body.role, body.purpose, body.category, body.strategy)
    if err:
        raise HTTPException(422, err)
    if db.scalar(select(Policy).where(Policy.role == body.role, Policy.purpose == body.purpose, Policy.category == body.category)):
        raise HTTPException(409, "A rule for this role, purpose and category already exists; edit it instead")
    p = Policy(**body.model_dump(), updated_by=actor.username)
    db.add(p)
    db.commit()
    _record(db, actor, "policy_change", "security_admin", f"created {p.identifier} {p.name} -> {p.strategy}", "policy-management")
    return _policy_out(p)


@router.patch("/policies/{policy_id}")
def policy_update(policy_id: int, body: PolicyPatch, actor: Actor = Depends(require("manage_policies")), db: Session = Depends(get_session)):
    p = db.get(Policy, policy_id)
    if not p:
        raise HTTPException(404, "Policy not found")
    new_strategy = body.strategy or p.strategy
    err = policy_store.validate_rule(p.role, p.purpose, p.category, new_strategy)
    if err:
        raise HTTPException(422, err)
    changes = []
    if body.strategy and body.strategy != p.strategy:
        changes.append(f"strategy {p.strategy}->{body.strategy}")
        p.strategy = body.strategy
    if body.enabled is not None and body.enabled != p.enabled:
        changes.append("enabled" if body.enabled else "disabled")
        p.enabled = body.enabled
    p.updated_by = actor.username
    db.commit()
    if changes:
        _record(db, actor, "policy_change", "security_admin", f"updated {p.identifier} {p.name}: {', '.join(changes)}", "policy-management")
    return _policy_out(p)


@router.delete("/policies/{policy_id}")
def policy_delete(policy_id: int, actor: Actor = Depends(require("manage_policies")), db: Session = Depends(get_session)):
    p = db.get(Policy, policy_id)
    if not p:
        raise HTTPException(404, "Policy not found")
    ident, name = p.identifier, p.name
    db.delete(p)
    db.commit()
    _record(db, actor, "policy_change", "security_admin", f"deleted {ident} {name}", "policy-management")
    return {"deleted": ident}


# Fixed, fabricated sample originals for the policy demonstrator. They are not read from the database.
SAMPLES = {
    "full_name": "Aarav Sharma", "email": "aarav.sharma@example.test", "phone": "+91 9123456780", "pan": "ABCDE1234F",
    "account_number": "123456789012", "date_of_birth": dt.date(1988, 4, 17), "city": "Pune", "annual_income": 1200000.0,
    "total_liabilities": 350000.0, "dependents": 2, "existing_cover": 500000.0, "liquid_assets": 250000.0, "education_goal": 1500000.0,
    "id": 101,
}


class SimulateIn(BaseModel):
    role: str
    purpose: str
    field: str


@router.post("/policies/simulate")
def policy_simulate(body: SimulateIn, actor: Actor = Depends(require("view_policies")), db: Session = Depends(get_session)):
    if body.role != actor.role and not policy_engine.has_permission(actor.role, "view_all_policies"):
        raise HTTPException(403, "You may only simulate policy for your own role")
    if body.role not in ROLES or body.purpose not in PURPOSES:
        raise HTTPException(422, "Unknown role or purpose")
    cats = load_categories(db)
    if body.field not in SAMPLES or body.field not in cats:
        raise HTTPException(422, "Field is not available for simulation. Run a scan first if fields are missing.")
    category = cats[body.field]
    pd = policy_engine.evaluate(body.role, body.purpose, {body.field: category}, False, policy_store.load_table(db))
    strategy = pd.plan.get(body.field, {}).get("strategy", "DENY")
    original = SAMPLES[body.field]
    output = None if strategy == "DENY" else apply_strategy(strategy, original, category)
    return {"synthetic": True, "field": body.field, "original": original.isoformat() if isinstance(original, dt.date) else original,
            "category": category, "sensitivity": sensitivity_of(category), "role": body.role, "purpose": body.purpose,
            "policy": pd.policy, "strategy": strategy, "output": output, "decision": pd.decision, "explanation": pd.reason,
            "note": "Synthetic example value. Real stored values are never used here and are never modified by masking."}


# ================= metrics =================
def _days(n: int, now: dt.datetime) -> list[str]:
    return [(now - dt.timedelta(days=i)).date().isoformat() for i in range(n - 1, -1, -1)]


@router.get("/metrics/overview")
def metrics_overview(days: int = Query(14, ge=1, le=90), actor: Actor = Depends(require("view_dashboard")), db: Session = Depends(get_session)):
    now = dt.datetime.now(UTC)
    since = (now - dt.timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    labels = _days(days, now)
    auditor = policy_engine.has_permission(actor.role, "view_audit")

    fields = db.scalars(select(FieldClassification)).all()
    by_cat: dict[str, int] = {}
    by_sens: dict[str, int] = {}
    for f in fields:
        by_cat[f.category] = by_cat.get(f.category, 0) + 1
        by_sens[sensitivity_of(f.category)] = by_sens.get(sensitivity_of(f.category), 0) + 1

    scans = [s for s in db.scalars(select(ScanRun).where(ScanRun.started_at >= since).order_by(ScanRun.id)) if s.status != "RUNNING"]
    scan_series = {d: {"date": d, "COMPLETED": 0, "FAILED": 0} for d in labels}
    for s in scans:
        scan_series[_aware(s.started_at).date().isoformat()][s.status] += 1 if s.status in ("COMPLETED", "FAILED") else 0

    stmt = select(AuditEvent.ts, AuditEvent.decision, AuditEvent.fields, AuditEvent.operation, AuditEvent.risk_score).where(AuditEvent.ts >= since)
    if not auditor:
        stmt = stmt.where(AuditEvent.actor == actor.username)
    events = db.execute(stmt.limit(20000)).all()
    dec_series = {d: {"date": d, "ALLOW": 0, "PARTIAL": 0, "DENY": 0} for d in labels}
    dec_total = {"ALLOW": 0, "PARTIAL": 0, "DENY": 0}
    strategies: dict[str, int] = {}
    for ts, decision, flds, operation, _risk in events:
        if operation in ("query", "insurance_assess", "insurance_estimate"):
            d = _aware(ts).date().isoformat()
            if decision in dec_total:
                dec_series[d][decision] += 1
                dec_total[decision] += 1
        for v in (flds or {}).values():
            strategies[v["strategy"]] = strategies.get(v["strategy"], 0) + 1

    sev: dict[str, int] = {}
    risk_total = 0
    if auditor:
        for (severity,) in db.execute(select(SecurityEvent.severity).where(SecurityEvent.ts >= since)):
            sev[severity] = sev.get(severity, 0) + 1
            risk_total += 1

    runs, auto_series = {"SUCCESS": 0, "FAILED": 0, "RETRYING": 0}, {d: {"date": d, "SUCCESS": 0, "FAILED": 0} for d in labels}
    if auditor:
        for r in db.scalars(select(WorkflowRun).where(WorkflowRun.ts >= since)):
            runs[r.status] = runs.get(r.status, 0) + 1
            if r.status in ("SUCCESS", "FAILED"):
                auto_series[_aware(r.ts).date().isoformat()][r.status] += 1

    last_scan = db.scalar(select(ScanRun).order_by(ScanRun.id.desc()).limit(1))
    return {
        "range": {"days": days, "since": since, "until": now, "bucket": "day (UTC)"},
        "scope": "all activity" if auditor else "your own activity",
        "source": {"name": "customers (synthetic demo data)", "records": db.scalar(select(func.count()).select_from(Customer)) or 0},
        "fields": {"total": len(fields), "sensitive": sum(1 for f in fields if sensitivity_of(f.category) != "LOW"),
                   "reviewed": sum(1 for f in fields if f.override_category), "by_category": by_cat, "by_sensitivity": by_sens},
        "scans": {"completed": sum(1 for s in scans if s.status == "COMPLETED"), "failed": sum(1 for s in scans if s.status == "FAILED"),
                  "series": list(scan_series.values()),
                  "last": {"id": last_scan.id, "status": last_scan.status, "finished_at": last_scan.finished_at, "triggered_by": last_scan.triggered_by,
                           "sensitive_found": last_scan.sensitive_found, "fields_scanned": last_scan.fields_scanned} if last_scan else None},
        "decisions": {"totals": dec_total, "series": list(dec_series.values()), "events_counted": sum(dec_total.values())},
        "masking": {"strategies_applied": strategies},
        "risk": {"available": auditor, "by_severity": sev, "total": risk_total},
        "automation": {"available": auditor, "by_status": runs, "series": list(auto_series.values())},
    }


# ================= risk =================
@router.get("/risk/events")
def risk_events(severity: str | None = None, limit: int = 25, offset: int = 0, actor: Actor = Depends(require("view_security_events")),
                db: Session = Depends(get_session)):
    limit, offset = max(1, min(limit, 100)), max(0, offset)
    conds = [SecurityEvent.severity == severity] if severity else []
    total = db.scalar(select(func.count()).select_from(SecurityEvent).where(*conds)) or 0
    rows = db.scalars(select(SecurityEvent).where(*conds).order_by(SecurityEvent.id.desc()).offset(offset).limit(limit)).all()
    by_sev = dict(db.execute(select(SecurityEvent.severity, func.count()).group_by(SecurityEvent.severity)).all())
    return {"total": total, "by_severity": by_sev, "items": [{"id": r.id, "ts": r.ts, "actor": r.actor, "rule": r.rule, "severity": r.severity,
            "detail": r.detail, "response": r.response, "request_id": r.request_id} for r in rows]}


@router.get("/risk/evaluations")
def risk_evaluations(limit: int = 25, offset: int = 0, actor: Actor = Depends(require("view_security_events")), db: Session = Depends(get_session)):
    limit, offset = max(1, min(limit, 100)), max(0, offset)
    cond = AuditEvent.risk_score > 0
    total = db.scalar(select(func.count()).select_from(AuditEvent).where(cond)) or 0
    rows = db.scalars(select(AuditEvent).where(cond).order_by(AuditEvent.id.desc()).offset(offset).limit(limit)).all()
    return {"total": total, "items": [{"request_id": r.request_id, "ts": r.ts, "actor": r.actor, "role": r.role, "decision": r.decision,
            "risk_score": r.risk_score, "risk_response": r.risk_response, "risk_signals": r.risk_signals, "reason": r.reason} for r in rows]}


SCENARIO_PROBES = ["pan", "account_number", "email", "phone", "pan, email", "full_name, pan"]


@router.post("/risk/scenarios/reconstruction")
def risk_scenario(actor: Actor = Depends(require("run_risk_scenario")), db: Session = Depends(get_session)):
    """Runs a real reconstruction-style probe sequence through the normal pipeline under a dedicated
    synthetic principal (never the caller's own account), so the effects are genuine audit/security events."""
    limiter.check(f"scenario:{actor.username}", 3, 60)
    bot = Actor(f"scenario-{actor.username}", "advisor")
    steps = []
    for probe in SCENARIO_PROBES:
        cols = [c.strip() for c in probe.split(",")]
        pq = ParsedQuery(table="customers", columns=["id"] + cols, filters=[("id", "=", 1)], limit=1)
        try:
            res = run_query(db, bot, "insurance_assessment", pq)
            outcome, status, rid = "ALLOWED", 200, res["trace"]["request_id"]
            risk = res["trace"]["risk"]
            denied = res["trace"]["denied_fields"]
        except HTTPException as exc:
            status, rid = exc.status_code, (exc.detail or {}).get("request_id") if isinstance(exc.detail, dict) else None
            outcome, denied = ("BLOCKED" if status == 429 else "DENIED"), []
            ev = db.scalar(select(AuditEvent).where(AuditEvent.request_id == rid)) if rid else None
            risk = {"score": ev.risk_score, "response": ev.risk_response, "signals": ev.risk_signals} if ev else {"score": 0, "response": None, "signals": []}
        steps.append({"requested": cols, "outcome": outcome, "http_status": status, "denied_fields": denied, "risk": risk, "request_id": rid})
    _record(db, actor, "risk_scenario", "security_admin", f"ran reconstruction scenario as principal {bot.username}", "risk-scenario")
    return {"principal": bot.username, "steps": steps,
            "note": "Real requests were evaluated by the live risk rules. The principal stays rate-limited for the risk window (default 10 minutes)."}


# ================= structured access request =================
class AccessIn(BaseModel):
    purpose: str
    fields: list[str] = Field(min_length=1, max_length=20)
    customer_id: int | None = Field(None, ge=1)
    limit: int = Field(10, ge=1, le=50)


@router.post("/access/evaluate")
def access_evaluate(body: AccessIn, actor: Actor = Depends(require("query")), db: Session = Depends(get_session)):
    """Role always comes from the authenticated token, never from the payload."""
    limiter.check(f"query:{actor.username}", 60, 60)
    if body.purpose not in PURPOSES:
        raise HTTPException(422, "Unknown purpose")
    bad = [f for f in body.fields if f not in COLUMNS]
    if bad:
        raise HTTPException(422, "Unknown field requested")
    pq = ParsedQuery(table="customers", columns=list(dict.fromkeys(body.fields)), limit=body.limit,
                     filters=[("id", "=", body.customer_id)] if body.customer_id else [])
    return run_query(db, actor, body.purpose, pq)


@router.get("/access/schema")
def access_schema(actor: Actor = Depends(require("query")), db: Session = Depends(get_session)):
    cats = load_categories(db)
    return {"fields": [{"name": c, "category": cats.get(c), "sensitivity": sensitivity_of(cats[c]) if c in cats else None} for c in COLUMNS],
            "purposes": [p for p in PURPOSES if (actor.role, p) in policy_store.load_table(db)], "role": actor.role}


# ================= insurance helpers =================
@router.get("/insurance/config")
def insurance_config(actor: Actor = Depends(require("insurance_assess"))):
    props = calculator.Assumptions.model_json_schema()["properties"]
    return {"illustrative": True,
            "assumptions": {k: {"default": v.get("default"), "min": v.get("minimum"), "max": v.get("maximum")} for k, v in props.items()},
            "inputs": [{"input": k, "why": why} for k, (_, why) in REQUIRED_INPUTS.items()],
            "formula": ["need = annual_income x replacement_years + total_liabilities + education_goal + dependents x per_dependent_buffer",
                        "gap = max(0, need - existing_cover - liquid_assets x asset_offset_ratio)"],
            "disclaimer": "Illustrative estimate only. Not an approved insurance formula, financial advice, or an insurance quote."}


@router.get("/insurance/customers")
def insurance_customers(actor: Actor = Depends(require("insurance_assess")), db: Session = Depends(get_session)):
    """Identifiers only: no names or other attributes are returned."""
    ids = db.scalars(select(Customer.id).order_by(Customer.id).limit(50)).all()
    return [{"id": i, "label": f"Synthetic customer #{i}"} for i in ids]


class EstimateIn(BaseModel):
    inputs: dict
    assumptions: dict | None = None


@router.post("/insurance/estimate")
def insurance_estimate(body: EstimateIn, actor: Actor = Depends(require("insurance_assess")), db: Session = Depends(get_session)):
    """What-if calculation on user-supplied inputs (no stored customer data is read)."""
    limiter.check(f"assess:{actor.username}", 30, 60)
    request_id = audit.new_request_id()
    try:
        result = calculator.assess(body.inputs, body.assumptions)
    except calculator.InputError as exc:
        audit.record(db, request_id=request_id, actor=actor.username, role=actor.role, operation="insurance_estimate", purpose="insurance_assessment",
                     fields={}, policy=f"{actor.role}/insurance_assessment", decision="DENY", reason=str(exc))
        raise HTTPException(422, {"message": str(exc), "request_id": request_id}) from None
    audit.record(db, request_id=request_id, actor=actor.username, role=actor.role, operation="insurance_estimate", purpose="insurance_assessment",
                 fields={k: {"category": "USER_SUPPLIED", "strategy": "ALLOW"} for k in body.inputs}, policy=f"{actor.role}/insurance_assessment",
                 decision="ALLOW", reason="what-if estimate on user-supplied inputs")
    return {"request_id": request_id, "result": result}


# ================= automation visibility =================
N8N_DIR = pathlib.Path(__file__).resolve().parents[3] / "n8n"
WORKFLOWS = [
    ("scheduled-scan", "Scheduled data scan", "scheduled-scan.workflow.json"),
    ("security-alerts", "Security alerts", "security-alerts.workflow.json"),
    ("summary-report", "Audit summary report", "summary-report.workflow.json"),
]


def _schedule_text(filename: str) -> str:
    try:
        wf = json.loads((N8N_DIR / filename).read_text(encoding="utf-8"))
        node = next(n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.scheduleTrigger")
        rule = node["parameters"]["rule"]["interval"][0]
        field = rule["field"]
        n = rule[field + "Interval"]
        return f"Every {field[:-1]}" if n == 1 else f"Every {n} {field}"
    except Exception:  # noqa: BLE001
        return "unknown (workflow file not readable)"


@router.get("/automation/workflows")
def automation_workflows(actor: Actor = Depends(require("view_automation")), db: Session = Depends(get_session)):
    out = []
    for key, title, filename in WORKFLOWS:
        runs = db.scalars(select(WorkflowRun).where(WorkflowRun.workflow == key).order_by(WorkflowRun.id.desc()).limit(10)).all()
        counts = dict(db.execute(select(WorkflowRun.status, func.count()).where(WorkflowRun.workflow == key).group_by(WorkflowRun.status)).all())
        out.append({"key": key, "name": title, "file": f"n8n/{filename}", "schedule": _schedule_text(filename),
                    "last_status": runs[0].status if runs else None, "last_run_at": runs[0].ts if runs else None,
                    "success_count": counts.get("SUCCESS", 0), "failure_count": counts.get("FAILED", 0),
                    "recent_runs": [{"id": r.id, "status": r.status, "attempt": r.attempt, "detail": r.detail, "ts": r.ts} for r in runs]})
    s = get_settings()
    return {"workflows": out, "editor_url": s.n8n_editor_url,
            "source": "Status comes from run reports that each workflow posts to TrustLayer (workflow_runs). If n8n has not run a workflow, nothing is shown for it."}


@router.get("/alerts")
def alerts_list(limit: int = 20, actor: Actor = Depends(require("view_security_events")), db: Session = Depends(get_session)):
    rows = db.scalars(select(AlertDelivery).order_by(AlertDelivery.id.desc()).limit(max(1, min(limit, 100)))).all()
    return {"channel_note": "Development channel: alerts are recorded in TrustLayer, not sent to email, SMS or chat.",
            "items": [{"id": r.id, "event_id": r.event_id, "rule": r.rule, "severity": r.severity, "channel": r.channel, "ts": r.ts} for r in rows]}


@router.get("/reports")
def reports_list(limit: int = 10, actor: Actor = Depends(require("view_audit")), db: Session = Depends(get_session)):
    rows = db.scalars(select(AuditReport).order_by(AuditReport.id.desc()).limit(max(1, min(limit, 50)))).all()
    return [{"id": r.id, "period_key": r.period_key, "period_start": r.period_start, "period_end": r.period_end, "report": r.report, "created_at": r.created_at} for r in rows]


class AlertIn(BaseModel):
    event_id: int = Field(ge=1)
    channel: str = Field("dev-log", pattern="^dev-log$")


@router.post("/automation/alerts")
def automation_alert(body: AlertIn, who: str = Depends(automation_auth), db: Session = Depends(get_session)):
    ev = db.get(SecurityEvent, body.event_id)
    if not ev:
        raise HTTPException(404, "Security event not found")
    existing = db.scalar(select(AlertDelivery).where(AlertDelivery.event_id == body.event_id))
    if existing:
        return {"id": existing.id, "duplicate": True}
    row = AlertDelivery(event_id=ev.id, rule=ev.rule, severity=ev.severity, channel=body.channel)  # rule/severity from the stored event, not the payload
    db.add(row)
    db.commit()
    return {"id": row.id, "duplicate": False}


class ReportIn(BaseModel):
    period_key: str = Field(max_length=64)
    period_start: dt.datetime
    period_end: dt.datetime
    report: dict


@router.post("/automation/reports")
def automation_report(body: ReportIn, who: str = Depends(automation_auth), db: Session = Depends(get_session)):
    if len(json.dumps(body.report, default=str)) > 4000:
        raise HTTPException(422, "Report too large")
    existing = db.scalar(select(AuditReport).where(AuditReport.period_key == body.period_key))
    if existing:
        return {"id": existing.id, "duplicate": True}
    row = AuditReport(period_key=body.period_key, period_start=body.period_start, period_end=body.period_end, report=body.report)
    db.add(row)
    db.commit()
    return {"id": row.id, "duplicate": False}


# ================= settings (read-only, no secrets) =================
@router.get("/settings")
def settings_view(actor: Actor = Depends(require("view_dashboard"))):
    s = get_settings()
    return {"environment": s.app_env, "version": __version__, "database": db_status(), "session_minutes": s.jwt_ttl_minutes,
            "presidio_enabled": s.use_presidio, "n8n_editor_url": s.n8n_editor_url, "config_ok": not s.config_problems(),
            "risk": {"window_minutes": s.risk_window_minutes, "denied_field_threshold": s.risk_denied_field_threshold,
                     "distinct_subsets_threshold": s.risk_distinct_subsets_threshold, "volume_threshold": s.risk_volume_threshold,
                     "elevated_score": s.risk_elevated_score, "block_score": s.risk_block_score},
            "retention": "Audit events are retained until manually purged (prototype assumption).",
            "read_only": "Settings are read-only here; change them in backend/.env."}
