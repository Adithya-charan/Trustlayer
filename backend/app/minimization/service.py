"""Decision-level data minimization for the insurance assessment.

The assessment needs exactly these inputs; everything else about a customer
(name, PAN, account, email, phone, city, id) is never loaded for it."""
import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Customer, FieldClassification
from app.policies import engine as policy_engine
from app.policies import store as policy_store

# input -> (source column, reason shown to the user)
REQUIRED_INPUTS = {
    "annual_income": ("annual_income", "income replacement component"),
    "total_liabilities": ("total_liabilities", "debts that dependants would inherit"),
    "dependents": ("dependents", "scales the dependants buffer"),
    "age": ("date_of_birth", "checks the replacement horizon (age derived, birth date not forwarded)"),
    "existing_cover": ("existing_cover", "offsets the need"),
    "liquid_assets": ("liquid_assets", "offsets the need"),
    "education_goal": ("education_goal", "future education funding goal"),
}
ALL_CUSTOMER_COLUMNS = [c for c in Customer.__table__.columns.keys()]


class MinimizationError(Exception):
    pass


def _age(dob: dt.date, today: dt.date | None = None) -> int:
    today = today or dt.date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def build_payload(db: Session, customer_id: int, role: str, purpose: str, elevated: bool = False) -> tuple[dict, dict]:
    """Returns (payload, report). Fails closed if policy denies any required input."""
    cats = {r.column_name: r.category for r in db.scalars(select(FieldClassification).where(FieldClassification.table_name == "customers"))}
    needed_cols = {src for src, _ in REQUIRED_INPUTS.values()}
    missing = [c for c in needed_cols if c not in cats]
    if missing:
        raise MinimizationError("Fields are not classified yet; run a scan first.")

    pd = policy_engine.evaluate(role, purpose, {c: cats[c] for c in needed_cols}, elevated, policy_store.load_table(db))
    blocked = [c for c in needed_cols if pd.plan[c]["strategy"] == "DENY"]
    if pd.decision == "DENY" or blocked:
        raise MinimizationError("Policy does not permit the inputs required for this assessment.")

    # Load ONLY the needed columns (parameterized, no SELECT *)
    row = db.execute(select(*[getattr(Customer, c) for c in sorted(needed_cols)]).where(Customer.id == customer_id)).mappings().first()
    if row is None:
        raise LookupError("customer not found")

    payload = {}
    for name, (src, _) in REQUIRED_INPUTS.items():
        payload[name] = _age(row[src]) if name == "age" else row[src]

    used = [{"input": n, "why": why, "category": cats[src]} for n, (src, why) in REQUIRED_INPUTS.items()]
    excluded = sorted(set(ALL_CUSTOMER_COLUMNS) - needed_cols)
    return payload, {"inputs_used": used, "attributes_excluded": excluded, "decision": pd}
