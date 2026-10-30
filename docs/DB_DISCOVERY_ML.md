# Database discovery and the ML supplement

Status: **off by default** (`B1_ML_SUPPLEMENT=false`). With the flag off, database discovery on Neon PostgreSQL and SQLite is exactly the original B1 classifier (`app/b1/detect.py`). With it on, the hybrid model can only add *uncertain* evidence to columns the original classifier could not classify.

## Data flow (unchanged except for the supplement step)

1. `targets.py` opens the target read-only (Neon: `BEGIN READ ONLY`; SQLite: `mode=ro` + `PRAGMA query_only`).
2. `discover.scan` reads one bounded random sample per table (`b1_sample_size`, default 200 rows) and keeps it in memory only.
3. For each column, `detect.classify_column` returns a `Detection` (kind, tag, confidence, status, methods, match_ratio, sample_size, rationale).
4. **New, flag-gated:** `supplement.eligible` picks columns with status `none`, a text type, outside `branches`. `supplement.apply` runs the ML detector on up to `B1_ML_SUPPLEMENT_VALUES` distinct text values (40) and may change the Detection (see mapping).
5. The result is upserted into `b1_field_tags` (one row per column, schema unchanged). Overrides are skipped as before.
6. Reads: `discover.fields`, `overview`, `query` (masking), and `/api/b1/fields` consume `kind`/`tag`/`status`/`methods` exactly as before.

Nothing in this chain changed shape. `methods` is a JSON list, so the new value `"ml_ner"` fits without a migration.

## Mapping: detector output -> existing B1 schema

| New detector category | Source | B1 kind | B1 tag | Stored status | Decision |
|---|---|---|---|---|---|
| PERSON | ML model | `FULL_NAME` | `PII_MEDIUM` | `uncertain` (conf 0.6) | Mapped: same meaning |
| LOCATION | ML model | `ADDRESS` | `PII_MEDIUM` | `uncertain` (conf 0.6) | Mapped: same meaning. Not applied to `branches` (business addresses) |
| ORGANIZATION | ML model | none | - | - | **Not stored.** An organisation name is not personal data by itself, and B1 has no organisation kind. Inventing one would change masking and risk for every table |
| EMAIL | rules | `EMAIL` | `PII_MEDIUM` | unchanged (original classifier) | Already handled; the supplement never re-classifies it |
| PHONE | rules | `PHONE` | `PII_MEDIUM` | unchanged | Already handled |
| CARD_NUMBER | rules (Luhn) | `CARD_NUMBER` | `PAYMENT_SENSITIVE` | unchanged | Deterministic validation stays authoritative; the model never sees the decision |
| IP_ADDRESS | rules | none | - | - | Not mapped: no B1 kind |
| GOVERNMENT_ID | rules | none (PAN/AADHAAR/SSN exist but the shape alone is ambiguous) | - | - | Not mapped: the original classifier keeps its own PAN/AADHAAR/SSN logic |
| FINANCIAL, DATE_OF_BIRTH | column name only | - | - | - | Not part of the supplement; the original classifier's name rules stay as they are |

Rules for a conflict, in order:

1. A column the original classifier has already classified (status `confirmed` or `uncertain`) is never changed by the model. The model cannot override it, downgrade it or upgrade its tag.
2. A column with status `none` can gain at most an `uncertain` PERSON/LOCATION suggestion.
3. Two categories tie on the sampled values: no suggestion (the column is ambiguous).
4. The model must label at least 60% of the distinct sampled text values with the category.
5. The model result is never `confirmed`. A test asserts that every ML-supplemented row is uncertain.

## Authorization, masking and overrides

- The scan itself still requires `b1_scan` (Admin / Security Admin). Nothing about the ML path changes who may scan.
- **Masking follows the stored kind/tag, as for every field.** An ML-supplemented `FULL_NAME` or `ADDRESS` is therefore masked for Support/Analyst/Advisor exactly like a confirmed one. This is a deliberate, conservative change that applies only when the flag is on: a column the model suggests is personal is protected while a person reviews it. Admin still sees raw values.
- Name scrubbing from free text (`query._names`) uses **confirmed** FULL_NAME columns only, so an uncertain suggestion never widens scrubbing.
- Manual overrides (`override=True`) are skipped on rescan exactly as before. A reviewer's classification always wins.
- The Overview "sensitive fields" count includes uncertain fields (as it does for every uncertain field today). Turning the flag on can raise that number; "needs review" also rises.

## What the model sees, and what is logged

- The model reads up to 40 distinct sampled text values per candidate column, in process memory, the same sample the original classifier already reads. No value is sent to Groq, written to a table, or logged. Failures are logged by exception type only (the message can echo input, so it is not logged).
- The scan's audit record stores counts and the mode only (`ML supplement hybrid`, `rules_only`, or `off`). A test checks that sampled values do not appear in the audit reason.

## Fallback

- Model not installed, download failed, out of memory, or inference error: the affected column keeps the original result, the rest of the scan switches to rules-only, and the response says so under `ml_supplement`:
  `{"enabled": true, "mode": "rules_only", "error": "...", "columns_checked": n, "supplemented": m}`.
- `DETECTION_ML_FALLBACK=fail` does **not** apply here: database discovery must never fail because of the model.
- `mode` is `hybrid` only when at least one column reached the model; `no_candidates` means enabled but no column needed it.

## Enable / disable

```
B1_ML_SUPPLEMENT=true     # enable
B1_ML_SUPPLEMENT=false    # disable (default)
```
Restart the backend after changing it. Rescan a database (Admin: Scan database) to apply it; existing rows are rewritten on scan, except reviewed overrides.

## Scope: CSV detection vs database discovery

- **CSV upload** (`backend/app/detection`, `POST /api/b1/upload/analyze`) analyses an uploaded file in memory. It is always hybrid when the model loads, and it has no flag.
- **Database discovery** (`backend/app/b1`, `POST /api/b1/scan`) classifies columns of the connected Neon PostgreSQL or SQLite database. It is governed by `B1_ML_SUPPLEMENT` and is off by default. Its output uses the original B1 kinds and tags.
- The two paths share the detector models and the sampling idea, but not their taxonomy or storage. Results from one are not the other's.

## Verification status (run on the code in this commit)

Real-model comparison on the organizer's SQLite file (`backend/data/saffron_bank.db`), read-only, nothing written to any database. Script: an ad-hoc comparison of `classify_column` with `supplement.apply`, printing only table/column names and kinds. Identifiers: model `urchade/gliner_multi_pii-v1`, threshold 0.5, sample 200 rows per table, up to 40 distinct text values per candidate column, CPU, one run (about 140 s).

| Measure | Result |
|---|---|
| Columns in the database | 120 |
| Columns the model was asked about (unclassified, text type) | 51 |
| Columns supplemented | **3** |
| Supplemented as ADDRESS (uncertain) | `customers.city`, `customers.state`, `international_customers.us_city` |
| Supplemented as FULL_NAME (uncertain) | none |
| Confirmed or uncertain columns changed by the model | **0** |
| `transactions.dr_cr` (earlier false positive) | no longer supplemented |
| `accounts.nominee_rel` (earlier false positive) | no longer supplemented |
| Earlier run before the shape rules | 7 supplemented, including the two false positives above |
| Remaining suspected false positives | none identified by column name; the three columns are address-type by name. Values were not printed, so this is by name only |

Limits of that check: it does not prove the three are right (nobody has labelled the organizer data), it did not re-check the override path (covered below), and the "0 changed" figure comes from the design (only unclassified columns are eligible) plus the synthetic-data tests, not from a second full run over every confirmed column.

Test evidence (`tests/test_b1_ml_supplement.py`, 16 tests, fake model by default; `RUN_ML_TESTS=1` runs the real-model test):

- Flag off reproduces the original classifier's kind and status for every column.
- Flag on changes only `none` columns; every confirmed or uncertain column is unchanged.
- Supplemented rows are `uncertain` and tagged `ml_ner`; none is `confirmed`.
- Ties, values under three characters, and single-word PERSON suggestions are ignored.
- A manual override survives a rescan and is not given the `ml_ner` method.
- A model that is unavailable, or raises an unexpected error, leaves the original results in place and discovery still completes; the error text is not carried into the result.
- The Analyst cannot read a supplemented city in clear; Admin can.
- Overview's `sensitive_fields` and `needs_review` move by exactly the supplemented count.
- The scan audit reason contains the mode and counts only (checked against sampled values).

## Isolated trial (copy of the organizer SQLite database)

Run on a copy of `backend/data/saffron_bank.db` (SHA-256 unchanged before and after), with a separate application database and a backend on port 8002. Neon and the live backend were not touched. Results:

- Flag on: 120 columns, 3 changed, all from unclassified to uncertain ADDRESS (`customers.city`, `customers.state`, `international_customers.us_city`). 0 confirmed or uncertain classifications changed.
- Masking (flag on): Admin ALLOW; Support PARTIAL; Analyst REDACT for the suggested columns, the same as a confirmed name column.
- Public reference lists (partial, lower bound): city 37 of 40 distinct values, state 21 of 22, US city 12 of 16 match. These are plausibility checks, not labels; the data has not been independently labelled.
- Manual override on `customers.state` survived a flag-on rescan. Defect found and fixed: a reviewed field kept the `ml_ner` method from an earlier suggestion; the review now removes only that method.
- Model unavailable: rules-only scan completed, identical to baseline except the reviewer's override.
- Flag off again: identical to the original classifier's baseline except the same override.
- Audit: no sampled value appears in any audit event.

## Manual overrides: creation, modification, clearing

**Create / modify** (`PATCH /api/b1/fields`, Admin or Security Admin): sets a column's kind. The row becomes `confirmed` with `reviewed=true` and the reviewer's name. "Confirmed" means a human decision, never a model result. Changing an existing decision replaces the kind and the reviewer. The superseded `ml_ner` method is removed; other methods stay, and `manual_review` is added. The audit reason records the previous kind and status.

**Masking release** (setting NON_SENSITIVE, or a clear that would restore NON_SENSITIVE over a protected decision): removes masking for every role. The server refuses it unless the request carries `confirm_masking_release: true` (409 `release_confirmation_required`). A refused attempt is audited as DENY. The UI shows a warning dialog before sending the confirmed request. The server check is authoritative; the dialog is only a second guard.

**Clear** (`POST /api/b1/fields/clear`, Admin or Security Admin, body `{target, table, column, confirm_masking_release?}`): removes the manual decision and re-runs the normal detection for that one column, using the same code path as a scan (`discover._detect`), including the ML supplement when enabled.
- It is not forced to NON_SENSITIVE. If detection finds nothing, the column becomes unclassified, as on a fresh scan.
- Preserved: methods that detection produces (for example `column_name`, `value_pattern`). Not preserved: the superseded decision itself. It is recorded only in the audit trail. The schema keeps no copy of pre-override automatic evidence, so the restored evidence is recomputed from the sample, not restored from storage.
- The release guard runs on the same detection result that is then written, so the check and the write cannot disagree (sampling is random).
- A clear with no manual override returns 409 `no_override` and is audited as a no-op. Repeated clears are therefore safe.
- If the table cannot be sampled, the column is classified from its name only and the audit says `sampled=no`.

**Feature flag and model**
- `B1_ML_SUPPLEMENT=false`: a clear uses the original classifier only.
- `B1_ML_SUPPLEMENT=true`, model working: a clear can restore the supplement (uncertain ADDRESS / FULL_NAME, `ml_ner`).
- `B1_ML_SUPPLEMENT=true`, model unavailable: the clear completes rules-only and reports it (`ml_supplement.mode = rules_only`, with the error type). It never fails because of the model.
- Rescans skip reviewed rows, so the flag or model state cannot change a manual decision until it is cleared.

**Authorization and audit guarantees**
- Server-side: every write (set, release, clear) requires `b1_review` (Admin, Security Admin). Analyst, Support, Advisor and Compliance get 403, and the attempt is audited (`b1_review`, DENY, with names only).
- Audit reasons contain table and column names, kinds, statuses, method names, the reviewer and the mode. They never contain sampled values, passwords or credentials. Tests check this across set, refused release, clear, repeated clear and refused clear.
- Masking after a decision follows the stored kind and tag, for every role, as for any other field.

**Masking-release risks (read before trialling)**
- A NON_SENSITIVE decision, or a clear that falls back to NON_SENSITIVE, releases the column to Support and Analyst at once. Masking is not restored by a later re-classification unless a reviewer sets it again.
- Clearing a protected decision does **not** make the column safe. The release check exists because detection can find nothing in a column that still holds personal data (for example, a free-text or code column).
- Two-person approval is **not** implemented. The existing architecture has no pending-change entity: a reviewer's change takes effect immediately and only the audit trail records it. With a single admin, one account can release masking for every role with one confirmed request. The confirmation dialog and the server `confirm_masking_release` flag guard against mistakes, not against a malicious or compromised admin. A trial must therefore name who may hold the Admin role, and the audit trail must be read after the trial.

### Proposed second-approver design (not built)

Scope: only masking-releasing changes (NON_SENSITIVE set, or a clear that restores NON_SENSITIVE over a protected decision). Everything else stays immediate.

- **Persistence**: a new table `b1_pending_changes` (id, target, table_name, column_name, action `set|clear`, proposed_kind, requested_by, requested_at, status `pending|approved|rejected|expired`, decided_by, decided_at, decision_note). One open row per column (unique on target, table, column where status = pending). The classification row `b1_field_tags` is **not** touched while a change is pending, so masking stays as it was.
- **Authorization**: requesting requires `b1_review`. Approving or rejecting requires `b1_review` and `decided_by != requested_by`, enforced on the server. A deployment with only one reviewer cannot release masking; that is intended, and the single-admin mode must be an explicit, audited setting, not the default.
- **Endpoints**: the existing PATCH and clear routes return 202 `release_pending` with the pending id instead of applying a release. New `POST /api/b1/changes/{id}/approve` and `/reject`, and `GET /api/b1/changes?status=pending`. The approval applies the change through the existing `discover.override` / `discover.clear_override` code, so the detection logic is not duplicated. The clear is re-evaluated at approval time, so the release check sees fresh data, not the sample taken at request time.
- **Audit**: new events `b1_release_requested`, `b1_release_approved`, `b1_release_rejected`, each with requester, approver, table.column, proposed and previous kind. Names and kinds only, as today.
- **Expiry**: a pending change expires after a fixed time (for example 7 days) so a stale request cannot be approved against a changed table.
- **Migration and compatibility**: one Alembic revision that creates `b1_pending_changes`; no change to `b1_field_tags`. Existing clients that send `confirm_masking_release` get 202 instead of 200, so the Discovery dialog needs a "pending approval" state and an approver list. Overrides that do not release masking are unaffected.

## Known limitations and trial requirements

- No frontend test runner exists in the repository. The dialogs were checked by the production build only; the interactive flow was **not** exercised in a browser in this round (the sign-in needs the demo password, which was not entered). A human reviewer must walk through it before trial.
- One full backend run ended once with a native process crash (a stack dump, not a test failure); three reruns of the same suite were clean. The cause is **unresolved**: no Windows fault event and no saved crash output exist. To capture it next time, run `PYTHONFAULTHANDLER=1 .venv/Scripts/python.exe -X faulthandler -m pytest -q -p no:cacheprovider > run.txt 2>&1` and keep `run.txt`; the top of the dump names the faulting thread and library (the ML stack, torch or tokenizers, is the first place to look, but that is a guess, not a finding).
- Pre-override automatic evidence is not stored, so a clear recomputes it (see above).
- There is no way to clear an override by mass action; each column is cleared individually.
- Overrides are human decisions, not verification. A reviewer who sets NON_SENSITIVE is trusted; the audit is the only check afterwards.
- Trial requirements: run on an isolated copy of the database and an isolated application database; the flag starts `false`; a human reviews each supplemented column and each release; the Neon run needs explicit approval.

## Masking and Overview: expected behaviour changes when the flag is on

- **Masking** follows the stored kind and tag (`query._tags`), not the status. Built-in policy (`mask.default_strategy`): Admin ALLOW (raw); Support PARTIAL; Analyst REDACT for both `FULL_NAME` and `ADDRESS`; any other role (for example advisor, compliance officer) is refused by `normalize_role` and fails closed. Admin-edited policies still apply first (`mask.strategy_for`).
- Consequence: a city the model suggests is hidden from Analyst and partly shown to Support, even though the classification is only uncertain. This is intentional (conservative), and it is the main behaviour change of the flag.
- Name scrubbing in free text (`query._names`) still uses confirmed FULL_NAME columns only, so an uncertain suggestion does not widen scrubbing.
- **Overview**: `sensitive_fields` counts every non-NON_SENSITIVE row, uncertain or not, and `needs_review` counts uncertain rows that are not overrides. Both rise with the flag; the UI labels them as needing review.
- No status is ever shown as "confirmed" because of the model.

## Neon PostgreSQL test readiness

The opt-in tests in `tests/test_b1_pg.py` are gated by `B1_PG_TEST_URL` and skipped otherwise. Assessment (inspected, not run):

- **Application database:** the `client` fixture points the application's session at an in-memory SQLite database, so `b1_field_tags`, audit rows and users written during the test stay in memory. The Neon URL is used only for the Target (the data being classified).
- **Neon access:** read-only (`BEGIN READ ONLY`, `SHOW transaction_read_only` checked). The test reads at most 200 sampled rows per table into memory, the same as the production scan. No write is issued against Neon.
- **Cleanup:** `targets.reset()`, `ml.reset()`, the `B1_ML_SUPPLEMENT` variable and the settings cache are restored at the end.
- **Sensitive data:** the sampled Neon values reach the local model (in process). They are not sent to Groq or any external service. Only the model download (once, from Hugging Face) is outbound.
- **Not isolated from production content:** the test reads real Saffron rows (synthetic, but the organizer's dataset in Neon). A run is therefore a read of that database, which needs approval per run.
- **Status:** not run live. It needs an explicit go-ahead and a `B1_PG_TEST_URL` supplied by you at run time.

## Configuration

- `B1_ML_SUPPLEMENT` defaults to `false` in code and in `.env.example`.
- An invalid value (for example `maybe`) or an empty value stops the application at startup (pydantic `ValidationError`). The supplement is never enabled by a bad value. Use `false` rather than leaving the line blank.
- Enable or disable: set `B1_ML_SUPPLEMENT=true` or `false` in `backend/.env`, restart the backend, then run **Scan database** (Admin or Security Admin). Existing rows are rewritten on the next scan, except reviewed overrides.

## Remaining gaps (deliberately not done)

- ORGANIZATION, IP_ADDRESS and GOVERNMENT_ID are detected by the new engine but have no B1 mapping (see table).
- The new engine's CSV path (`app/detection`) and database discovery still use separate code. Unifying them would change the B1 taxonomy, so it is left for a separate decision.
- The model's score is not stored; the B1 confidence for a supplemented column is a fixed 0.6, not a probability.
