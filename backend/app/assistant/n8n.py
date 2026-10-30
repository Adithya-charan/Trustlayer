"""Starts the approved on-demand n8n workflows through a header-authenticated production webhook.

Boundaries: the URL is base + a FIXED path per approved workflow (nothing from the user or the model reaches it); the secret
is attached here on the server; n8n answering 200 means "started", never "succeeded". Completion is reported by the workflow's own
run report (workflow_runs), which `run_status` reads. The browser never sees the base URL, the secret or any n8n credential."""
import datetime as dt
import logging

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import limiter
from app.database.models import WorkflowRun

log = logging.getLogger("trustlayer.n8n")
UTC = dt.timezone.utc
TRIGGER_HEADER = "X-TrustLayer-Trigger-Key"

# key (as stored in workflow_runs) -> (label, fixed on-demand webhook path)
APPROVED = {
    "scheduled-scan": ("sensitive-data scan workflow", "trustlayer-on-demand-scan"),
    "security-alerts": ("security-alert workflow", "trustlayer-on-demand-alerts"),
    "summary-report": ("audit summary workflow", "trustlayer-on-demand-summary"),
}


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def ready() -> bool:
    return get_settings().n8n_trigger_ready


def http_client() -> httpx.Client:
    """The one place the trigger secret is attached. Tests replace this to inject a mock transport."""
    s = get_settings()
    return httpx.Client(timeout=s.n8n_trigger_timeout_seconds, headers={TRIGGER_HEADER: s.n8n_trigger_secret})


def trigger(key: str, requested_by: str) -> dict:
    if key not in APPROVED:
        raise _error(400, "workflow_not_approved", "That workflow is not approved for on-demand runs.")
    if not ready():
        raise _error(503, "workflow_not_configured", "On-demand workflows are not configured on the server (N8N_WEBHOOK_BASE_URL / N8N_TRIGGER_SECRET).")
    label, path = APPROVED[key]
    limiter.check(f"workflow:{key}", 1, 20)  # a second trigger within 20 s is almost certainly a duplicate
    url = f"{get_settings().n8n_webhook_base_url}/{path}"
    started = dt.datetime.now(UTC)
    try:
        with http_client() as c:
            r = c.post(url, json={"requested_by": requested_by, "source": "trustlayer-assistant"})
    except httpx.HTTPError as exc:
        log.warning("n8n trigger failed: %s", type(exc).__name__)
        raise _error(502, "workflow_unavailable", f"Could not reach n8n to start the {label}. Check that n8n is running.") from None
    if r.status_code in (401, 403):
        raise _error(503, "workflow_not_configured", f"n8n rejected the trigger credential for the {label}. Check N8N_TRIGGER_SECRET and the n8n Header Auth credential.")
    if r.status_code == 404:
        raise _error(409, "workflow_not_published", f"n8n has no production webhook for the {label}. The on-demand workflow must be imported and published first.")
    if r.status_code >= 300:
        log.warning("n8n trigger returned %s", r.status_code)
        raise _error(502, "workflow_unavailable", f"n8n did not accept the request to start the {label} (HTTP {r.status_code}).")
    return {"kind": "workflow_triggered", "workflow": key, "name": label, "triggered_at": started,
            "accepted_by_n8n": True, "completed": None,
            "note": "n8n accepted the request. The workflow is running; its result is reported separately."}


def run_status(db: Session, key: str, since: dt.datetime | None) -> dict:
    """What the workflow itself reported to TrustLayer after `since`. `pending` means no report has arrived yet; it is not a failure."""
    if key not in APPROVED:
        raise _error(400, "workflow_not_approved", "Unknown workflow.")
    stmt = select(WorkflowRun).where(WorkflowRun.workflow == key).order_by(WorkflowRun.id.desc()).limit(1)
    last = db.scalar(stmt)
    ts = last.ts if last is not None else None
    if ts is not None and ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    fresh = bool(last and (since is None or (ts and ts >= since)))
    if not fresh:
        return {"workflow": key, "state": "pending", "detail": "No run report has arrived since the workflow was started."}
    return {"workflow": key, "state": "SUCCESS" if last.status == "SUCCESS" else last.status, "reported_at": ts, "detail": last.detail}
