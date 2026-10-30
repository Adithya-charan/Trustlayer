# TrustLayer demo (three minutes)

> TrustLayer discovers sensitive financial data, classifies it, applies identity-aware policies at query time, masks or redacts the result without modifying
> the underlying database, and records every important access decision.

**Same database. Same query. Different identity. Different exposure.**

Data: the organizer's Saffron Bank dataset (9 tables, 129,260 records, synthetic). Sign in as `admin_anita` (password = `DEMO_PASSWORD`).
Before you start: backend on :8000, `npm run dev`, and for the live avatar the worker (`voice_agent/.venv/Scripts/python.exe voice_agent/agent.py dev`).

## Script

1. **Overview (20 s).** Point at the real counts: tables, columns scanned, sensitive fields, audit decisions. Say which backend is connected (Neon PostgreSQL, SQLite; MySQL shows "not configured").
2. **Data Discovery (40 s).** Open the page, click **Scan database** if no scan exists. Show confirmed vs uncertain, the "PII hidden inside free text" panel (`support_tickets.ticket_text`, `loan_applications.remarks`, `transactions.narration`), and `loan_applications.col_7` (a meaningless name that holds PANs, found from values).
3. **Same query, different identity (40 s).** Access Policies, **Run for every identity** with `SELECT pan_no, aadhaar_no FROM kyc_records LIMIT 5;`.
   Admin sees real PAN and Aadhaar, Support sees partial masks, Analyst sees hashed PAN and no Aadhaar. The badge under the button proves the stored rows did not change (row count and fingerprint).
4. **Live policy change (40 s).** "Edit a user's policy": Kavya Hegde, kind PAN, change to PARTIAL, **Apply policy change**. The Before and After tables show her same query changing. Then **Reset to default**.
5. **Audit Center (20 s).** The `policy change` event (old to new strategy, by whom), the masked queries, the policy applied (`b1/Analyst/user:analyst_kavya`). Only field names and strategies are stored, never values.
6. **Voice (20 s).** Click **Voice Command** in the top bar and type or speak: "Show high risk PII", "Open audit center".

## Voice Command Control

One command in, one checked action out. Speech goes to the server's speech-to-text, the text is matched against a closed list of intents (no free-form execution), the server checks
your role and audits the decision, and the browser carries out the approved action (open a page, apply a filter). The panel shows **Listening**, **Heard**, **Intent**, **Result**.
Voice never widens access: opened tables and pages go through the same identity, policy and masking path as a click.

| Say (examples; natural phrasing works) | Intent |
|---|---|
| "Show high risk PII", "Show sensitive fields", "Show financial sensitive fields", "Show payment fields", "Show embedded PII" | open Discovery with that filter |
| "Open audit center", "Show recent audit events", "Show denied requests", "Show masked requests", "Show policy changes" | open Audit Center with that filter |
| "Open the cards table", "Open explorer" | open Data Explorer (that table) |
| "Show analyst policies", "Show support policy" | open Access Policies for that role |
| "Show analyst access", "Open Kavya Hegde's access" | open Users & Access |
| "Run the masking demo" | open Access Policies and run the same query for every role |
| "Scan the database" | Admin only; opens Discovery and starts a scan (read-only sampling; the scan endpoint re-checks the role and audits it) |
| "Change Kavya Hegde's PAN policy to partial mask" | Admin only; **asks to confirm** ("Do you want me to apply this?"), applies only on Yes |

Anything that changes policy, users, configuration or data needs an explicit confirmation: the server returns a signed, single-use, two-minute confirmation that only the same signed-in user can redeem.
An ambiguous command never changes anything. An unrecognised command answers: *I couldn't understand that command. Try: "Show high risk PII".*

## Honest limits

- The microphone path depends on the browser's microphone permission and Sarvam speech-to-text; the typed path always works.
- About a third of the Aadhaar values in the organizer's data are already masked in the source (`XXXX XXXX 1234`); they are returned as stored.
- MySQL support is implemented but has not been verified against a live MySQL server.
- Neon is remote: the first request after idle can take several seconds.
