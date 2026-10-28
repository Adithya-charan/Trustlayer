"""ILLUSTRATIVE life-insurance needs calculation (needs-based / DIME-style).

NOT an approved actuarial or regulatory formula. All factors are configurable
assumptions chosen for demonstration. See docs/INSURANCE.md.

    need = income * replacement_years
         + total_liabilities
         + education_goal
         + dependents * per_dependent_buffer
    gap  = max(0, need - existing_cover - liquid_assets * asset_offset_ratio)
"""
from dataclasses import dataclass, asdict

from pydantic import BaseModel, Field, ValidationError


class Assumptions(BaseModel):
    replacement_years: int = Field(10, ge=1, le=30)
    per_dependent_buffer: float = Field(200_000, ge=0, le=5_000_000)
    asset_offset_ratio: float = Field(0.5, ge=0, le=1)


class MinimizedInputs(BaseModel):
    """The only attributes the calculator may receive. No identifiers."""

    model_config = {"extra": "forbid"}
    annual_income: float = Field(ge=0, le=1e10)
    total_liabilities: float = Field(ge=0, le=1e11)
    dependents: int = Field(ge=0, le=20)
    age: int = Field(ge=18, le=80)
    existing_cover: float = Field(ge=0, le=1e11)
    liquid_assets: float = Field(ge=0, le=1e11)
    education_goal: float = Field(ge=0, le=1e11)


class InputError(ValueError):
    pass


def _round(n: float, to: int = 100_000) -> int:
    return int(round(n / to) * to)


def assess(raw_inputs: dict, assumptions: dict | None = None) -> dict:
    try:
        inp = MinimizedInputs(**raw_inputs)
        a = Assumptions(**(assumptions or {}))
    except ValidationError as exc:
        # report which fields failed, never the offending values
        bad = sorted({str(e["loc"][0]) if e["loc"] else "input" for e in exc.errors()})
        raise InputError(f"Invalid or missing inputs: {', '.join(bad)}") from None

    if inp.dependents == 0 and inp.education_goal > 0:
        raise InputError("Inconsistent inputs: education goal set but dependents is 0")
    if inp.age + a.replacement_years > 100:
        raise InputError("Inconsistent inputs: age plus replacement years exceeds 100")

    income_component = inp.annual_income * a.replacement_years
    dependents_component = inp.dependents * a.per_dependent_buffer
    need = income_component + inp.total_liabilities + inp.education_goal + dependents_component
    offsets = inp.existing_cover + inp.liquid_assets * a.asset_offset_ratio
    gap = max(0.0, need - offsets)
    return {
        "illustrative": True,
        "status": "additional_cover_indicated" if gap > 0 else "no_additional_cover_indicated",
        "recommended_additional_cover": _round(gap),
        "components": {  # coarsely rounded (₹1 lakh) to limit how precisely inputs can be inferred; not a guarantee
            "income_replacement": _round(income_component),
            "liabilities": _round(inp.total_liabilities),
            "education_goal": _round(inp.education_goal),
            "dependents_buffer": _round(dependents_component),
            "less_existing_cover_and_assets": -_round(offsets),
        },
        "assumptions": a.model_dump(),
        "disclaimer": "Illustrative demo calculation using configurable assumptions. Not financial advice or an approved insurance formula.",
    }
