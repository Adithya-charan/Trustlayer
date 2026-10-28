# TrustLayer design notes

## Decision flow

`request → authenticate (JWT) → RBAC permission → SQL gateway parse → field classification lookup → risk assessment → policy decision → execute parameterized query → mask/transform → explanation → audit`

Everything is enforced in the FastAPI backend (`backend/app/api/pipeline.py`). The UI only displays results.

## Classification taxonomy

| Category | Sensitivity |
|---|---|
| GOVERNMENT_ID, ACCOUNT_IDENTIFIER | CRITICAL |
| DIRECT_IDENTIFIER, CONTACT, FINANCIAL | HIGH |
| DEMOGRAPHIC | MEDIUM |
| NON_SENSITIVE | LOW |

Detection signals: column-name patterns, value-format checks on up to 20 sampled rows (PAN, email, phone, account digits, dates), and Presidio entity recognition for text columns. Only ratios and rationale text are stored; raw samples are never persisted or returned. Admins and compliance officers can override a category; overrides persist across re-scans.

## Policy rules (`policies` table; defaults in `rules.py`)

Policies map `(role, purpose)` → `category → strategy`, stored one rule per row (`POL-0001`…) with enabled flag, updated-by and timestamp. Security admins can create, edit, disable and delete rules through the API/dashboard (server-side validation; `ALLOW` is rejected for government and account IDs; every change is audited). Unlisted pairs/categories and disabled rules are denied. `rules.py` holds the reviewed defaults that seed the table and a fallback used only if the table has no rows at all.

| Role / purpose | Identifiers | Contact | Financial | Demographic |
|---|---|---|---|---|
| advisor / insurance_assessment | name REDACT; PAN, account DENY | DENY | PARTIAL (band) | ALLOW |
| advisor / customer_service | name PARTIAL; PAN FULL_MASK; account PARTIAL | PARTIAL | DENY | PARTIAL |
| analyst / analytics | HASH | REDACT | PARTIAL (band) | PARTIAL |
| compliance_officer / audit_review | PARTIAL | FULL_MASK | FULL_MASK | PARTIAL |
| security_admin / security_admin | HASH | REDACT | REDACT | REDACT |

Operation permissions: scan → security_admin; review classification and view audit/security events → security_admin, compliance_officer; insurance assessment → advisor; query/policies/dashboard → all roles.

When risk is elevated, every non-NON_SENSITIVE strategy tightens one step (ALLOW→PARTIAL→FULL_MASK, HASH→REDACT).

## Risk rules (`risk/detector.py`, thresholds in `core/config.py`)

Computed from the actor's own audit events in a 10-minute window (defaults):

| Rule | Fires when | Weight |
|---|---|---|
| REPEATED_RESTRICTED_ACCESS | ≥3 earlier requests touched denied fields | 2 |
| UNUSUAL_VOLUME | ≥30 requests | 2 |
| RECONSTRUCTION_PATTERN | same record requested with ≥4 distinct field sets | 2 |

Score ≥2 → `ELEVATED_MASKING` (security event, MEDIUM); score ≥4 → `BLOCK` (HTTP 429, security event, HIGH). A single signal never blocks. Same history → same outcome. These are heuristics, not a complete anomaly detector, and can false-positive on legitimate heavy use.

## Insurance assessment (illustrative)

Not an approved actuarial formula. Configurable assumptions (bounded, defaults shown):

```
need = annual_income × replacement_years(10)
     + total_liabilities + education_goal
     + dependents × per_dependent_buffer(200,000)
gap  = max(0, need − existing_cover − liquid_assets × asset_offset_ratio(0.5))
```

Inputs forwarded to the calculator are exactly: `annual_income, total_liabilities, dependents, age, existing_cover, liquid_assets, education_goal`. The minimization service queries only those columns (age is derived from date of birth; birth date is not forwarded) and fails closed if policy denies any. The response shows which inputs were used and which attributes were never loaded; components are rounded to ₹1 lakh and exact inputs are not echoed. Validation rejects negative/missing/unknown inputs and inconsistent combinations (education goal without dependents; age + horizon > 100).

## Audit

`audit_events` stores request id, time, actor, role, operation, purpose, field→(category, strategy), policy, decision, reason, risk score/signals/response. A scrubber redacts PAN/account/email-shaped strings from free text. Values are never stored. `GET /api/audit` and security events require auditor roles; users can fetch the trace of their own requests.

## Metrics (`GET /api/metrics/overview?days=`)

Computed on request from persisted rows, in UTC day buckets, with zero-filled days (zeros are real, not placeholders). Auditors see all activity; other roles see only their own decisions, with risk and automation sections marked unavailable. Definitions: *decisions* = `query`, `insurance_assess` and `insurance_estimate` audit events by outcome (ALLOW / PARTIAL = masked / DENY); *scans* = completed and failed scan runs by start time; *security events* by severity; *masking strategies* = counts of field-level strategies in audit events; *automation* = run reports posted by n8n.

## Automation endpoints

Authenticated with the automation key (`X-TrustLayer-Automation-Key`): `POST /api/automation/scans` (idempotent), `GET /api/automation/security-events` (optional `severity`), `GET /api/automation/summary?hours=` (1–168), `POST /api/automation/alerts` (one per security event; severity/rule come from the stored event, not the payload), `POST /api/automation/reports` (unique per period key), `POST /api/automation/workflow-runs`. Dashboard-facing reads (`/api/automation/workflows`, `/api/alerts`, `/api/reports`) require an auditor JWT.

## Risk scenario runner

`POST /api/risk/scenarios/reconstruction` (security admin) runs six reconstruction-style probes through the normal pipeline under a dedicated principal `scenario-<admin>` with the advisor role, so the resulting audit and security events are genuine but the admin's own account is not rate-limited.
