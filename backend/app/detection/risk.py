"""Deterministic risk classification. Inputs: category sensitivity, how much of the column is affected, evidence strength, protection status.
The ML score is NOT an input: confidence says how sure a detector is, risk says how much harm exposure could do.

  score = sensitivity(category)            CARD_NUMBER/GOVERNMENT_ID 4 | FINANCIAL/DATE_OF_BIRTH 3 | PERSON/PHONE/EMAIL/LOCATION/IP_ADDRESS 2 | ORGANIZATION 1
        + exposure                         share of inspected values affected: >=50% +1 | 5-50% 0 | <5% -1
        - 2 if the column is already protected (masked/redacted by policy)
  Critical >= 5, High 4, Medium 2-3, Low <= 1.  Name-only or mixed (suspected) findings are capped at Medium until a human confirms them."""
SENSITIVITY = {"CARD_NUMBER": 4, "GOVERNMENT_ID": 4, "FINANCIAL": 3, "DATE_OF_BIRTH": 3, "PERSON": 2, "PHONE": 2, "EMAIL": 2, "LOCATION": 2, "IP_ADDRESS": 2, "ORGANIZATION": 1}
PROTECTION = {
    "CARD_NUMBER": ("PARTIAL", "Show only the last 4 digits; never store or display the full number outside payment systems."),
    "GOVERNMENT_ID": ("REDACT", "Redact entirely for non-privileged roles; restrict access to those with a stated legal need."),
    "FINANCIAL": ("REDACT", "Restrict to finance roles; show ranges or aggregates to everyone else."),
    "DATE_OF_BIRTH": ("REDACT", "Hide the date; expose age bands if needed."),
    "PERSON": ("PARTIAL", "Show initials or a first name only."),
    "PHONE": ("PARTIAL", "Keep the last 2-4 digits only."),
    "EMAIL": ("PARTIAL", "Mask the local part, keep the domain."),
    "LOCATION": ("PARTIAL", "Generalise to city or region."),
    "IP_ADDRESS": ("HASH", "Replace with a keyed hash so records can still be joined."),
    "ORGANIZATION": ("ALLOW", "Usually business information; review whether it identifies an individual."),
}
LEVELS = ("Low", "Medium", "High", "Critical")


def assess(category: str | None, ratio: float, confirmed: bool, protected: bool = False) -> dict:
    if category not in SENSITIVITY:
        return {"level": "Unclassified", "points": None, "explanation": "No detector matched, so no risk level is assigned. That does not prove the column is safe.", "recommended_protection": None, "protection_note": "Review manually."}
    base = SENSITIVITY[category]
    exposure = 1 if ratio >= 0.5 else 0 if ratio >= 0.05 else -1
    points = base + exposure - (2 if protected else 0)
    level = "Critical" if points >= 5 else "High" if points == 4 else "Medium" if points >= 2 else "Low"
    parts = [f"{category} has base sensitivity {base}", f"{ratio:.0%} of inspected values are affected ({exposure:+d})"]
    if protected:
        parts.append("already protected by policy (-2)")
    if not confirmed and level in ("High", "Critical"):
        level = "Medium"
        parts.append("capped at Medium because the finding is suspected, not confirmed")
    strategy, note = PROTECTION[category]
    return {"level": level, "points": points, "explanation": "; ".join(parts) + f" -> {level}.", "recommended_protection": strategy, "protection_note": note}
