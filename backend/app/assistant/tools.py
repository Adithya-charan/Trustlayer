"""The ONLY operations the assistant can perform.

The language model never executes anything: it may only *name* one of these tools with arguments, and the
router validates the name, the arguments (strict schemas, no extra fields) and the caller's permission
before any handler runs. There is deliberately no SQL, shell, HTTP or workflow-execution tool; adding one
requires adding it to TOOLS here, in review. Consequential tools are never run from a model response alone:
they need a separate, signed, single-use confirmation from the signed-in user."""
from dataclasses import dataclass
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api import extra, routes
from app.assistant import audit_qa, n8n
from app.core.config import get_settings
from app.core.security import Actor, limiter
from app.detection import qa, store
from app.policies.engine import has_permission

AUDITORS = {"security_admin", "compliance_officer"}
B1_ADMIN = {"Admin", "security_admin"}
B1_ALL = {"Admin", "Support", "Analyst", "security_admin", "analyst"}
# Server-side mirror of the dashboard's navigation: which roles may open which page.
PAGES: dict[str, set[str] | None] = {
    "overview": B1_ALL, "discovery": B1_ALL, "explorer": B1_ALL, "policies": B1_ALL, "access": B1_ADMIN, "audit": B1_ADMIN,
    "voice": None, "automation": AUDITORS, "settings": None,
}
PAGE_HELP = {
    "overview": "Overview shows live numbers from the connected database: tables, records, sensitive and protected fields, policy rules and audit events.",
    "discovery": "Data Discovery lists each column's detected classification, risk, confidence and how it was detected. Admins can scan and correct a classification.",
    "explorer": "Data Explorer shows each table's columns, types, classification and the masking your role gets, plus sample rows through the masking engine.",
    "policies": "Access Policies shows what each role receives for each kind of data and runs the same query under every identity. Admins can edit a user's policy.",
    "access": "Users & Access lists the accounts, their roles and the masking each one actually receives.",
    "audit": "The Audit Center records every scan, query and policy change with field names and strategies only, never values.",
    "voice": "The Voice Assistant lets you talk to the operator copilot, which can explain pages and report status but never decides access.",
    "automation": "Automation shows the n8n workflows, their last run reports and the stored summary reports.",
    "settings": "Settings is a read-only view of the running configuration. Secrets are never shown.",
}
Page = Literal["overview", "discovery", "explorer", "policies", "access", "audit", "voice", "automation", "settings"]


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(_Args):
    pass


class SecurityEventsArgs(_Args):
    severity: Literal["HIGH", "MEDIUM", "LOW"] | None = None
    limit: int = Field(5, ge=1, le=20)


class ScansArgs(_Args):
    limit: int = Field(5, ge=1, le=10)


class PageArgs(_Args):
    page: Page


class DatasetArgs(_Args):
    question: Literal["summary", "count_category", "highest_risk", "column"] = "summary"
    category: str | None = Field(None, max_length=40)
    column: str | None = Field(None, max_length=80)


@dataclass(frozen=True)
class Ctx:
    db: Session
    actor: Actor


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[_Args]
    permission: str | None  # a key of policies.rules.PERMISSIONS, or None when gated by `allowed` below
    consequential: bool
    run: Callable[[Ctx, Any], dict]
    confirm_text: str = ""
    roles: frozenset[str] | None = None  # extra role gate for tools whose rule lives outside policies.rules.PERMISSIONS (the B1 engine roles)
    available: Callable[[], bool] = lambda: True  # False hides the tool from the model and refuses it, e.g. when n8n triggering is not configured

    def schema(self) -> dict:
        params = self.args.model_json_schema()
        params.pop("title", None)
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": params}}


def _security_events(ctx: Ctx, a: SecurityEventsArgs) -> dict:
    out = extra.risk_events(severity=a.severity, limit=a.limit, offset=0, actor=ctx.actor, db=ctx.db)
    return {"kind": "security_events", "total": out["total"], "by_severity": out["by_severity"], "items": out["items"], "severity": a.severity}


def _recent_scans(ctx: Ctx, a: ScansArgs) -> dict:
    return {"kind": "scans", "items": routes.list_scans(limit=a.limit, actor=ctx.actor, db=ctx.db)}


def _start_scan(ctx: Ctx, _: NoArgs) -> dict:
    limiter.check(f"scan:{ctx.actor.username}", 5, 60)
    return {"kind": "scan_started", "scan": routes._do_scan(ctx.db, ctx.actor.username, ctx.actor.role, "customers")}  # noqa: SLF001


def _automation_status(ctx: Ctx, _: NoArgs) -> dict:
    out = extra.automation_workflows(actor=ctx.actor, db=ctx.db)
    keep = ("key", "name", "schedule", "last_status", "last_run_at", "success_count", "failure_count")
    return {"kind": "automation", "workflows": [{k: w[k] for k in keep} for w in out["workflows"]], "editor_url": get_settings().n8n_editor_url}


def _dataset(ctx: Ctx, a: DatasetArgs) -> dict:
    """Facts about the caller's most recent uploaded-dataset analysis, computed by Python from stored findings (no cell values). `reply` is the answer shown;
    the model never supplies numbers."""
    item = store.get(ctx.actor.username)
    if item is None:
        return {"kind": "dataset_answer", "reply": "No dataset has been analysed in this session. Upload a CSV on the Data Discovery page first, then ask again.", "facts": None}
    if a.question == "count_category":
        f = qa.count_category(item, a.category or "")
        if not f["found"]:
            return {"kind": "dataset_answer", "reply": f["message"], "facts": None}
        kind = "exactly" if f["exact"] else "an estimated"
        where = f" in {', '.join(f['columns'])}" if f["columns"] else ""
        return {"kind": "dataset_answer", "reply": f"{f['category']}: {kind} {f['matches']:,} value(s){where} ({f['scope']}). {f['note']}", "facts": f}
    if a.question == "highest_risk":
        top = qa.highest_risk(item)
        reply = "Highest-risk columns: " + "; ".join(f"{c['column']} ({c['category'] or 'unclassified'}, {c['risk']})" for c in top) + "." if top else "No columns were classified."
        return {"kind": "dataset_answer", "reply": reply, "facts": top}
    if a.question == "column":
        info = qa.column_info(item, a.column or "")
        if info is None:
            return {"kind": "dataset_answer", "reply": "That column is not in the analysed dataset.", "facts": None}
        return {"kind": "dataset_answer", "reply": f"{info['column']}: {info['category'] or 'unclassified'} ({info['status']}), risk {info['risk']}. {info['evidence']}. {info['risk_explanation']}", "facts": info}
    sm = qa.summary(item)
    cats = ", ".join(f"{c} {v['value_matches']:,}" for c, v in sm["by_category"].items()) or "none"
    mode = "rules only (ML model unavailable)" if sm["mode"] == "rules_only" else "hybrid rules + ML"
    return {"kind": "dataset_answer", "reply": f"{sm['name']}: {sm['rows']:,} rows, {sm['sensitive_columns']} sensitive and {sm['suspected_columns']} suspected columns, "
            f"highest risk {sm['highest_risk']}. Matches by category: {cats}. Detection mode: {mode}.", "facts": sm}


def _navigate(ctx: Ctx, a: PageArgs) -> dict:
    return {"kind": "navigate", "page": a.page}


def _explain_page(ctx: Ctx, a: PageArgs) -> dict:
    return {"kind": "page_help", "page": a.page, "text": PAGE_HELP[a.page]}


def _workflow_runner(key: str) -> Callable[[Ctx, Any], dict]:
    return lambda ctx, _: n8n.trigger(key, ctx.actor.username)


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("list_security_events", "Show recent security events, optionally filtered by severity (HIGH, MEDIUM, LOW).", SecurityEventsArgs,
         "view_security_events", False, _security_events),
    Tool("list_recent_scans", "Show the most recent sensitive-data scans and their results.", ScansArgs, "view_dashboard", False, _recent_scans),
    Tool("start_sensitive_data_scan", "Start a sensitive-data scan of the customers data source. Changes state, so the user must confirm.",
         NoArgs, "scan", True, _start_scan, confirm_text="Start a sensitive-data scan of the customers data source now?"),
    Tool("get_automation_status", "Show the status of the three n8n automation workflows from their stored run reports. Read-only.",
         NoArgs, "view_automation", False, _automation_status),
    Tool("run_scan_workflow", "Run the approved n8n sensitive-data scan workflow now. Changes state, so the user must confirm.", NoArgs, "run_workflow", True,
         _workflow_runner("scheduled-scan"), confirm_text="Run the n8n sensitive-data scan workflow now?", available=n8n.ready),
    Tool("run_security_alert_workflow", "Run the approved n8n security-alert workflow now. Changes state, so the user must confirm.", NoArgs, "run_workflow", True,
         _workflow_runner("security-alerts"), confirm_text="Run the n8n security-alert workflow now?", available=n8n.ready),
    Tool("generate_audit_summary", "Run the approved n8n audit-summary workflow now to produce an aggregate report. Changes state, so the user must confirm.", NoArgs, "run_workflow", True,
         _workflow_runner("summary-report"), confirm_text="Run the n8n audit summary workflow now?", available=n8n.ready),
    Tool("ask_about_dataset", "Use for ANY question about the uploaded CSV dataset or its PII findings, e.g. 'how many email addresses were detected', 'what sensitive data is in this dataset', 'which column is riskiest', 'why is column X sensitive'. question=summary, count_category (with category such as EMAIL, PHONE, "
         "CARD_NUMBER, IP_ADDRESS, PERSON, LOCATION, ORGANIZATION), highest_risk, or column (with column name). Numbers are computed by the backend; never guess them.",
         DatasetArgs, None, False, _dataset, roles=frozenset(B1_ADMIN)),
    Tool("recent_policy_changes", "Use for questions about masking-policy changes: 'recently changed policies', 'what changed recently', 'the last 3 policy changes', 'who changed the PAN policy', 'what did the Admin change'. "
         "Set limit to the number the user asked for (default 3). Optional user (a person's name, matches who was changed or who changed it) and kind (e.g. PAN, AADHAAR). Data comes from the audit trail.",
         audit_qa.PolicyChangesArgs, None, False, lambda ctx, a: audit_qa.policy_changes(ctx.db, ctx.actor, a), roles=frozenset(B1_ADMIN)),
    Tool("access_history", "Use for questions about who accessed or tried to access what: 'recent activity', 'what did Kavya access', 'her last 3 activities', 'denied attempts', 'who tried restricted data', "
         "'why was Kavya's Aadhaar denied', 'most recent denied request', 'recent security events', 'access history'. Set limit to the number asked. decision=DENY for denied or blocked; MASK for masked results. "
         "operation: denied (blocked access attempts), access (queries plus denied attempts: use this for 'access attempts', 'access history', 'what did X access'), policy_change, login, review, scan. after_change_of=PAN (or another data kind) answers 'what happened after the PAN policy was changed'. field filters on a column or data type such as PAN or Aadhaar. user is a person's name. "
         "Non-admin users only see their own activity.",
         audit_qa.ActivityArgs, None, False, lambda ctx, a: audit_qa.access_history(ctx.db, ctx.actor, a), roles=frozenset(B1_ALL)),
    Tool("followup_on_last_answer", "Use ONLY when the user refers to the previous answer: 'who made the first one', 'why was it changed', 'when did that happen', 'what policy applied to the second'. "
         "aspect: who, when, why, policy, result or details. index is the item number in the previous list (default 1; 'it' or 'that' = 1).",
         audit_qa.FollowupArgs, None, False, lambda ctx, a: audit_qa.followup(ctx.db, ctx.actor, a), roles=frozenset(B1_ALL)),
    Tool("navigate_to_page", "Open a dashboard page for the user.", PageArgs, None, False, _navigate),
    Tool("explain_page", "Explain what a dashboard page is for.", PageArgs, None, False, _explain_page),
]}


def page_allowed(role: str, page: str) -> bool:
    roles = PAGES.get(page, set())
    return page in PAGES and (roles is None or role in roles)


def permitted(tool: Tool, actor: Actor, args: Any = None) -> bool:
    if tool.permission is not None and not has_permission(actor.role, tool.permission):
        return False
    if tool.roles is not None and actor.role not in tool.roles:
        return False
    page = getattr(args, "page", None)
    return page is None or page_allowed(actor.role, page)


def tools_for(actor: Actor) -> list[Tool]:
    """What the model is allowed to see: only tools this role may use. The router re-checks on every call."""
    return [t for t in TOOLS.values() if t.available() and (t.permission is None or has_permission(actor.role, t.permission)) and (t.roles is None or actor.role in t.roles)]
