"""Explicit, reviewable policy table: (role, purpose) -> {category: strategy}.
Anything not listed is DENY (default-deny). See docs/POLICIES.md."""

ROLES = ("security_admin", "compliance_officer", "advisor", "analyst")
PURPOSES = ("insurance_assessment", "customer_service", "audit_review", "analytics", "security_admin")

_NONSENS = {"NON_SENSITIVE": "ALLOW"}

POLICY_TABLE: dict[tuple[str, str], dict[str, str]] = {
    ("advisor", "insurance_assessment"): {
        **_NONSENS,
        "DIRECT_IDENTIFIER": "REDACT",
        "FINANCIAL": "PARTIAL_MASK",  # bands only; the assessment service gets minimized exact inputs internally
        "DEMOGRAPHIC": "ALLOW",
    },
    ("advisor", "customer_service"): {
        **_NONSENS,
        "DIRECT_IDENTIFIER": "PARTIAL_MASK",
        "CONTACT": "PARTIAL_MASK",
        "GOVERNMENT_ID": "FULL_MASK",
        "ACCOUNT_IDENTIFIER": "PARTIAL_MASK",
        "DEMOGRAPHIC": "PARTIAL_MASK",
    },
    ("analyst", "analytics"): {
        **_NONSENS,
        "DIRECT_IDENTIFIER": "HASH",
        "GOVERNMENT_ID": "HASH",
        "ACCOUNT_IDENTIFIER": "HASH",
        "CONTACT": "REDACT",
        "FINANCIAL": "PARTIAL_MASK",
        "DEMOGRAPHIC": "PARTIAL_MASK",
    },
    ("compliance_officer", "audit_review"): {
        **_NONSENS,
        "DIRECT_IDENTIFIER": "PARTIAL_MASK",
        "GOVERNMENT_ID": "PARTIAL_MASK",
        "ACCOUNT_IDENTIFIER": "PARTIAL_MASK",
        "CONTACT": "FULL_MASK",
        "FINANCIAL": "FULL_MASK",
        "DEMOGRAPHIC": "PARTIAL_MASK",
    },
    ("security_admin", "security_admin"): {
        **_NONSENS,
        "DIRECT_IDENTIFIER": "HASH",
        "GOVERNMENT_ID": "HASH",
        "ACCOUNT_IDENTIFIER": "HASH",
        "CONTACT": "REDACT",
        "FINANCIAL": "REDACT",
        "DEMOGRAPHIC": "REDACT",
    },
}

# Which roles may call which operation (backend-enforced RBAC)
PERMISSIONS: dict[str, set[str]] = {
    "query": {"security_admin", "compliance_officer", "advisor", "analyst"},
    "insurance_assess": {"advisor"},
    "scan": {"security_admin"},
    "review_field": {"security_admin", "compliance_officer"},
    "view_audit": {"security_admin", "compliance_officer"},
    "view_security_events": {"security_admin", "compliance_officer"},
    "view_policies": {"security_admin", "compliance_officer", "advisor", "analyst"},
    "view_dashboard": {"security_admin", "compliance_officer", "advisor", "analyst"},
    "view_all_policies": {"security_admin", "compliance_officer"},
    "manage_policies": {"security_admin"},
    "run_risk_scenario": {"security_admin"},
    "run_workflow": {"security_admin"},
    # B1 data-protection engine. Roles: Admin / Support / Analyst (organizer sample users); security_admin acts as Admin, "analyst" as Analyst.
    "b1_query": {"Admin", "Support", "Analyst", "security_admin", "analyst"},
    "b1_scan": {"Admin", "security_admin"},
    "b1_review": {"Admin", "security_admin"},
    "b1_compare": {"Admin", "security_admin"},
    "b1_policy": {"Admin", "security_admin"},  # edit masking policies, read users and overview
    "view_automation": {"security_admin", "compliance_officer"},
}

# Tightening applied when risk is elevated (one step stricter)
ESCALATION = {"ALLOW": "PARTIAL_MASK", "PARTIAL_MASK": "FULL_MASK", "HASH": "REDACT", "FULL_MASK": "FULL_MASK", "REDACT": "REDACT", "DENY": "DENY"}
