import datetime as dt

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(32))
    password_hash: Mapped[str] = mapped_column(String(128))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Customer(Base):
    """Synthetic demo customers. Originals are never modified by masking."""

    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(128))
    email: Mapped[str] = mapped_column(String(128))
    phone: Mapped[str] = mapped_column(String(32))
    pan: Mapped[str] = mapped_column(String(16))
    account_number: Mapped[str] = mapped_column(String(24))
    date_of_birth: Mapped[dt.date] = mapped_column(Date)
    city: Mapped[str] = mapped_column(String(64))
    annual_income: Mapped[float] = mapped_column(Float)
    total_liabilities: Mapped[float] = mapped_column(Float)
    dependents: Mapped[int] = mapped_column(Integer)
    existing_cover: Mapped[float] = mapped_column(Float)
    liquid_assets: Mapped[float] = mapped_column(Float)
    education_goal: Mapped[float] = mapped_column(Float)


class FieldClassification(Base):
    __tablename__ = "field_classifications"
    __table_args__ = (UniqueConstraint("table_name", "column_name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    table_name: Mapped[str] = mapped_column(String(64))
    column_name: Mapped[str] = mapped_column(String(64))
    data_type: Mapped[str] = mapped_column(String(32))
    detected_category: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float)
    rationale: Mapped[list] = mapped_column(JSON, default=list)
    override_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_scan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    @property
    def category(self) -> str:
        return self.override_category or self.detected_category


class ScanRun(Base):
    __tablename__ = "scan_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16))  # RUNNING | COMPLETED | FAILED
    triggered_by: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fields_scanned: Mapped[int] = mapped_column(Integer, default=0)
    sensitive_found: Mapped[int] = mapped_column(Integer, default=0)
    presidio_used: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(64), default="customers")
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)


class AuditEvent(Base):
    """Structured audit record. Holds field NAMES and decisions, never values."""

    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), index=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(32))
    operation: Mapped[str] = mapped_column(String(48))
    purpose: Mapped[str] = mapped_column(String(48))
    subject_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fields: Mapped[dict] = mapped_column(JSON, default=dict)  # field -> {category, strategy}
    policy: Mapped[str] = mapped_column(String(96))
    decision: Mapped[str] = mapped_column(String(16))  # ALLOW | PARTIAL | DENY
    reason: Mapped[str] = mapped_column(String(300))
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    risk_signals: Mapped[list] = mapped_column(JSON, default=list)
    risk_response: Mapped[str | None] = mapped_column(String(48), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # structured "why": policy path per field, old -> new for policy changes. Names and strategies only.


class SecurityEvent(Base):
    __tablename__ = "security_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    request_id: Mapped[str] = mapped_column(String(36))
    actor: Mapped[str] = mapped_column(String(64))
    rule: Mapped[str] = mapped_column(String(48))
    severity: Mapped[str] = mapped_column(String(12))
    detail: Mapped[str] = mapped_column(String(300))
    response: Mapped[str] = mapped_column(String(48))


class WorkflowRun(Base):
    """Status reported by n8n. Informational only; not a security boundary."""

    __tablename__ = "workflow_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))  # SUCCESS | FAILED | RETRYING
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    detail: Mapped[str] = mapped_column(String(300), default="")
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Policy(Base):
    """Editable policy rule: (role, purpose, category) -> strategy. Absent or disabled => DENY."""

    __tablename__ = "policies"
    __table_args__ = (UniqueConstraint("role", "purpose", "category"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[str] = mapped_column(String(32))
    purpose: Mapped[str] = mapped_column(String(48))
    category: Mapped[str] = mapped_column(String(32))
    strategy: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[str] = mapped_column(String(64), default="system")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    @property
    def name(self) -> str:
        return f"{self.role}/{self.purpose}/{self.category}"

    @property
    def identifier(self) -> str:
        return f"POL-{self.id:04d}"


class AlertDelivery(Base):
    """Alerts routed by n8n to the development channel (recorded here, not sent externally)."""

    __tablename__ = "alert_deliveries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(Integer, unique=True)  # one alert per security event
    rule: Mapped[str] = mapped_column(String(48))
    severity: Mapped[str] = mapped_column(String(12))
    channel: Mapped[str] = mapped_column(String(32), default="dev-log")
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditReport(Base):
    """Periodic aggregate report stored by the n8n summary workflow."""

    __tablename__ = "audit_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_key: Mapped[str] = mapped_column(String(64), unique=True)
    period_start: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    report: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class B1FieldTag(Base):
    """Classification of one column of a B1 target database (Saffron Bank). Holds tags, confidence and detection method only:
    never sampled values. `override` rows were set by an authorized reviewer and win over automatic detection on re-scan."""

    __tablename__ = "b1_field_tags"
    __table_args__ = (UniqueConstraint("target", "table_name", "column_name", name="uq_b1_field"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target: Mapped[str] = mapped_column(String(32))
    table_name: Mapped[str] = mapped_column(String(64))
    column_name: Mapped[str] = mapped_column(String(64))
    data_type: Mapped[str] = mapped_column(String(64), default="")
    kind: Mapped[str] = mapped_column(String(32))
    tag: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(12))  # confirmed | uncertain | none
    methods: Mapped[list] = mapped_column(JSON, default=list)
    match_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    rationale: Mapped[str] = mapped_column(String(200), default="")
    override: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class B1RolePolicy(Base):
    """Admin-edited masking strategy for every account of one role and one classification kind. Absent row = the built-in default."""

    __tablename__ = "b1_role_policies"
    __table_args__ = (UniqueConstraint("role", "kind", name="uq_b1_role_policy"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(32))
    strategy: Mapped[str] = mapped_column(String(16))
    updated_by: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class B1UserPolicy(Base):
    """Admin-edited masking strategy for ONE user and one classification kind; wins over the role policy and the default."""

    __tablename__ = "b1_user_policies"
    __table_args__ = (UniqueConstraint("username", "kind", name="uq_b1_user_policy"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    strategy: Mapped[str] = mapped_column(String(16))
    updated_by: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
