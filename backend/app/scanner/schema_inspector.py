"""Controlled schema + sample inspection. Only allow-listed tables are scanned."""
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.models import Customer, FieldClassification, ScanRun, utcnow
from app.scanner import pii_detector
from app.scanner.classifier import sensitivity_of

SCAN_TARGETS = {"customers": Customer}  # explicit allow-list, no arbitrary table access
SAMPLE_SIZE = 20


def run_scan(db: Session, triggered_by: str, idempotency_key: str | None = None, use_presidio: bool | None = None,
             source: str = "customers", request_id: str | None = None) -> ScanRun:
    if source not in SCAN_TARGETS:
        raise ValueError("unknown data source")
    if use_presidio is None:
        use_presidio = get_settings().use_presidio
    if idempotency_key:
        existing = db.scalar(select(ScanRun).where(ScanRun.idempotency_key == idempotency_key))
        if existing:
            return existing  # repeated event -> same result, no duplicate scan

    scan = ScanRun(status="RUNNING", triggered_by=triggered_by, idempotency_key=idempotency_key, source=source, request_id=request_id)
    db.add(scan)
    db.commit()
    try:
        sensitive = total = 0
        for table_name, model in {source: SCAN_TARGETS[source]}.items():
            columns = inspect(db.get_bind()).get_columns(table_name)
            rows = db.scalars(select(model).limit(SAMPLE_SIZE)).all()
            for col in columns:
                name = col["name"]
                samples = [getattr(r, name, None) for r in rows]
                det = pii_detector.detect_field(name, str(col["type"]), samples, use_presidio)
                rec = db.scalar(
                    select(FieldClassification).where(
                        FieldClassification.table_name == table_name, FieldClassification.column_name == name
                    )
                )
                if rec is None:
                    rec = FieldClassification(table_name=table_name, column_name=name)
                    db.add(rec)
                rec.data_type = str(col["type"])
                rec.detected_category = det.category
                rec.confidence = det.confidence
                rec.rationale = det.rationale
                rec.last_scan_id = scan.id
                total += 1
                if sensitivity_of(rec.category) != "LOW":
                    sensitive += 1
        scan.status = "COMPLETED"
        scan.fields_scanned, scan.sensitive_found = total, sensitive
        scan.presidio_used = use_presidio and pii_detector.get_presidio() is not None
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        scan = db.get(ScanRun, scan.id)
        scan.status = "FAILED"
        scan.error = f"scan failed: {type(exc).__name__}"
    scan.finished_at = utcnow()
    db.commit()
    return scan
