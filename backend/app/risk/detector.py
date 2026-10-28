"""Deterministic, explainable risk rules over the actor's recent audit trail.

Each rule emits a weighted signal. One weak signal never triggers action:
  score >= risk_elevated_score -> tighten masking one step (ELEVATED_MASKING)
  score >= risk_block_score    -> deny the request + security alert (BLOCK)
Thresholds are configurable (Settings). Same history => same outcome."""
import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.database.models import AuditEvent


@dataclass
class RiskAssessment:
    score: int = 0
    signals: list[dict] = field(default_factory=list)
    response: str | None = None  # None | ELEVATED_MASKING | BLOCK

    @property
    def elevated(self) -> bool:
        return self.response in ("ELEVATED_MASKING", "BLOCK")


def assess_risk(db: Session, actor: str, current_fields: list[str], current_subject: str | None,
                settings: Settings, now: dt.datetime | None = None) -> RiskAssessment:
    now = now or dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(minutes=settings.risk_window_minutes)
    recent = db.scalars(select(AuditEvent).where(AuditEvent.actor == actor, AuditEvent.ts >= since)).all()
    out = RiskAssessment()

    # R1: repeated attempts at fields policy denies
    denied_attempts = sum(1 for e in recent if e.decision in ("DENY", "PARTIAL") and any(f["strategy"] == "DENY" for f in e.fields.values()))
    if denied_attempts >= settings.risk_denied_field_threshold:
        out.signals.append({"rule": "REPEATED_RESTRICTED_ACCESS", "weight": 2,
                            "detail": f"{denied_attempts} requests touching denied fields in {settings.risk_window_minutes} min"})

    # R2: request volume
    if len(recent) >= settings.risk_volume_threshold:
        out.signals.append({"rule": "UNUSUAL_VOLUME", "weight": 2,
                            "detail": f"{len(recent)} requests in {settings.risk_window_minutes} min"})

    # R3: reconstruction pattern - same subject probed with many different field subsets
    if current_subject:
        subsets = {tuple(sorted(e.fields)) for e in recent if e.subject_ref == current_subject}
        subsets.add(tuple(sorted(current_fields)))
        if len(subsets) >= settings.risk_distinct_subsets_threshold:
            out.signals.append({"rule": "RECONSTRUCTION_PATTERN", "weight": 2,
                                "detail": f"same record requested with {len(subsets)} different field combinations"})

    out.score = sum(s["weight"] for s in out.signals)
    if out.score >= settings.risk_block_score:
        out.response = "BLOCK"
    elif out.score >= settings.risk_elevated_score:
        out.response = "ELEVATED_MASKING"
    return out
