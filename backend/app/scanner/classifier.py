"""Classification taxonomy shared by scanner and policy engine."""

CATEGORIES = (
    "DIRECT_IDENTIFIER",
    "GOVERNMENT_ID",
    "ACCOUNT_IDENTIFIER",
    "CONTACT",
    "FINANCIAL",
    "DEMOGRAPHIC",
    "NON_SENSITIVE",
)

SENSITIVITY = {
    "GOVERNMENT_ID": "CRITICAL",
    "ACCOUNT_IDENTIFIER": "CRITICAL",
    "DIRECT_IDENTIFIER": "HIGH",
    "CONTACT": "HIGH",
    "FINANCIAL": "HIGH",
    "DEMOGRAPHIC": "MEDIUM",
    "NON_SENSITIVE": "LOW",
}


def sensitivity_of(category: str) -> str:
    return SENSITIVITY.get(category, "CRITICAL")  # unknown -> treat as most sensitive
