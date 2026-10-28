"""Persisted policy rules. The code table in rules.py is the reviewed default set used
to seed the database (and as a fallback only when the policies table has no rows at all)."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import Policy
from app.policies.rules import POLICY_TABLE
from app.masking.strategies import STRATEGIES
from app.scanner.classifier import CATEGORIES

CRITICAL = {"GOVERNMENT_ID", "ACCOUNT_IDENTIFIER"}


def validate_rule(role: str, purpose: str, category: str, strategy: str) -> str | None:
    """Returns an error message, or None when the rule is acceptable."""
    from app.policies.rules import PURPOSES, ROLES

    if role not in ROLES:
        return "Unknown role"
    if purpose not in PURPOSES:
        return "Unknown purpose"
    if category not in CATEGORIES:
        return "Unknown category"
    if strategy not in STRATEGIES:
        return "Unknown strategy"
    if strategy == "ALLOW" and category in CRITICAL:
        return "Critical identifiers (government and account IDs) can never be returned in the clear"
    return None


def seed_defaults(db: Session) -> int:
    """Insert the default policy rules if missing. Never overwrites edits."""
    existing = {(p.role, p.purpose, p.category) for p in db.scalars(select(Policy))}
    added = 0
    for (role, purpose), rules in POLICY_TABLE.items():
        for category, strategy in rules.items():
            if (role, purpose, category) not in existing:
                db.add(Policy(role=role, purpose=purpose, category=category, strategy=strategy, updated_by="seed"))
                added += 1
    db.commit()
    return added


def load_table(db: Session) -> dict[tuple[str, str], dict[str, str]]:
    """Enabled rules grouped by (role, purpose). Disabled rules are simply absent => DENY."""
    if not db.scalar(select(func.count()).select_from(Policy)):
        return POLICY_TABLE
    table: dict[tuple[str, str], dict[str, str]] = {}
    for p in db.scalars(select(Policy).where(Policy.enabled.is_(True))):
        table.setdefault((p.role, p.purpose), {})[p.category] = p.strategy
    return table
