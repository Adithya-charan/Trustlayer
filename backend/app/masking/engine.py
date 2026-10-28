from app.masking.strategies import apply_strategy


def mask_row(row: dict, plan: dict[str, dict]) -> dict:
    """plan: field -> {"strategy": ..., "category": ...}. DENY fields and fields
    missing from the plan are omitted (default-deny)."""
    out = {}
    for field, value in row.items():
        p = plan.get(field)
        if not p or p["strategy"] == "DENY":
            continue
        out[field] = apply_strategy(p["strategy"], value, p.get("category"))
    return out
