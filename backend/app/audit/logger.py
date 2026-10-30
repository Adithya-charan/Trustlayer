"""Audit logging. Records field NAMES, categories, strategies and decisions only.
A guard rejects free-text that looks like raw PAN/account/email/phone data."""
import re
import uuid

from sqlalchemy.orm import Session

from app.database.models import AuditEvent, SecurityEvent

_LEAK = [
    re.compile(r"[A-Z]{5}[0-9]{4}[A-Z]"),
    re.compile(r"\b[0-9]{9,18}\b"),
    re.compile(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", re.I),
]


def scrub(text: str) -> str:
    for rx in _LEAK:
        text = rx.sub("[scrubbed]", text)
    return text[:300]


def _clean(detail: dict | None):
    """Scrubs every string inside the structured detail the same way as the reason, so a value can never be stored through it."""
    if detail is None:
        return None
    if isinstance(detail, dict):
        return {str(k)[:48]: _clean(v) for k, v in detail.items()}
    if isinstance(detail, (list, tuple)):
        return [_clean(v) for v in detail[:40]]
    return scrub(detail) if isinstance(detail, str) else detail


def new_request_id() -> str:
    return str(uuid.uuid4())


def record(db: Session, *, request_id: str, actor: str, role: str, operation: str, purpose: str,
           fields: dict, policy: str, decision: str, reason: str, subject_ref: str | None = None,
           risk_score: int = 0, risk_signals: list | None = None, risk_response: str | None = None, detail: dict | None = None) -> AuditEvent:
    ev = AuditEvent(
        request_id=request_id, actor=actor, role=role, operation=operation, purpose=purpose,
        subject_ref=subject_ref, fields={k: {"category": v["category"], "strategy": v["strategy"]} for k, v in fields.items()},
        policy=policy, decision=decision, reason=scrub(reason), risk_score=risk_score,
        risk_signals=risk_signals or [], risk_response=risk_response, detail=_clean(detail),
    )
    db.add(ev)
    db.commit()
    return ev


def security_event(db: Session, *, request_id: str, actor: str, rule: str, severity: str, detail: str, response: str) -> None:
    db.add(SecurityEvent(request_id=request_id, actor=actor, rule=rule, severity=severity, detail=scrub(detail), response=response))
    db.commit()
