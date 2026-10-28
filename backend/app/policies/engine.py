from dataclasses import dataclass, field

from app.policies.rules import ESCALATION, PERMISSIONS, POLICY_TABLE


@dataclass
class PolicyDecision:
    decision: str  # ALLOW | PARTIAL | DENY
    policy: str
    reason: str
    plan: dict[str, dict] = field(default_factory=dict)  # field -> {strategy, category}
    denied_fields: list[str] = field(default_factory=list)


def has_permission(role: str, operation: str) -> bool:
    return role in PERMISSIONS.get(operation, set())


def evaluate(role: str, purpose: str, fields: dict[str, str], elevated: bool = False, table: dict | None = None) -> PolicyDecision:
    """fields: field name -> effective category. Pure function => reproducible."""
    policy_name = f"{role}/{purpose}"
    rules = (POLICY_TABLE if table is None else table).get((role, purpose))
    if rules is None:
        return PolicyDecision("DENY", policy_name, f"No policy grants role '{role}' the purpose '{purpose}' (default deny).")

    plan: dict[str, dict] = {}
    denied: list[str] = []
    for name, category in fields.items():
        strategy = rules.get(category, "DENY")
        if elevated and category != "NON_SENSITIVE":
            strategy = ESCALATION.get(strategy, "DENY")
        plan[name] = {"strategy": strategy, "category": category}
        if strategy == "DENY":
            denied.append(name)

    if denied and len(denied) == len(fields):
        return PolicyDecision("DENY", policy_name, "All requested fields are denied for this role and purpose.", plan, denied)
    suffix = " Risk was elevated, so masking was tightened one step." if elevated else ""
    if denied:
        return PolicyDecision("PARTIAL", policy_name, f"{len(denied)} field(s) denied by policy; the rest are returned protected.{suffix}", plan, denied)
    transformed = any(p["strategy"] != "ALLOW" for p in plan.values())
    reason = "Fields returned with protection applied per policy." if transformed else "All fields permitted by policy."
    return PolicyDecision("PARTIAL" if transformed else "ALLOW", policy_name, reason + suffix, plan, denied)
