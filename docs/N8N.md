# n8n orchestration (local, self-hosted)

n8n schedules scans, routes alerts and produces summary reports. It is **not** a security boundary: authentication, authorization, risk scoring, policy decisions, masking and insurance logic stay in the TrustLayer backend, which works fully without n8n.

Architecture used for development (all on one machine, nothing public):

| Service | Address |
|---|---|
| Frontend (Vite) | http://localhost:5173 |
| FastAPI backend | http://127.0.0.1:8000 |
| n8n editor | http://localhost:5678 |
| Database | Neon PostgreSQL (from `DATABASE_URL`) |

n8n Cloud, public tunnels and deployment are **out of scope** here. n8n Cloud cannot reach a backend on your computer; using it would be a separate deployment decision.

## How it works

- **Authentication:** every workflow call sends the header `X-TrustLayer-Automation-Key` from an n8n *Header Auth* credential named `TrustLayer Automation Key`. The backend compares it in constant time with `N8N_SHARED_SECRET` (`backend/app/core/security.py`). The key only unlocks `/api/automation/*`; it cannot read customer data, change policies or sign in as a user.
- **Execution record:** each workflow posts a run report to `POST /api/automation/workflow-runs`. The dashboard's **Automation** page shows these (TrustLayer never calls n8n's API and needs no n8n API key). Report text is scrubbed of PAN/account/email-shaped strings.
- **Base URL:** the `baseUrl` field in each workflow's **Config** node (default `http://127.0.0.1:8000`). Use `127.0.0.1`, not `localhost`: Node resolves `localhost` to IPv6 `::1` first and uvicorn listens on IPv4 only, which fails with *"service refused the connection"*. (Alternatively run uvicorn with `--host ::`.)
- **Timeouts and retries:** 60 s timeout per HTTP call. Calls to the backend retry at most **3 times, 5 s apart**; then the error branch runs. n8n cannot exclude status codes from retries, so a 401/403 is also tried 3 times (bounded, never indefinite). 4xx/5xx, invalid JSON and timeouts all take this path; connection refused too.

## Workflows (`n8n/*.workflow.json`)

| File | Schedule | Calls |
|---|---|---|
| `scheduled-scan` | every 24 h (+ manual trigger) | `POST /api/automation/scans`, `POST /api/automation/workflow-runs` |
| `security-alerts` | every 5 min (+ manual) | `GET /api/automation/security-events?severity=HIGH&since_id=`, `POST /api/automation/alerts`, `POST /api/automation/workflow-runs` |
| `summary-report` | every 1 day (+ manual) | `GET /api/automation/summary?hours=`, `POST /api/automation/reports`, `POST /api/automation/workflow-runs` |

### Idempotency (intended behaviour)

| What | Unique per | Effect of a repeat |
|---|---|---|
| Scan | **hour** (`Idempotency-Key: scan-<UTC hour>`) | returns the original scan; one scan row and one audit event |
| Alert | **security event id** (database unique) | `duplicate: true`; the cursor in workflow static data is only an optimisation |
| Report | **UTC day + window** (`report-<date>-<hours>h`) | `report already stored for this period`; one report |
| Run report | **n8n execution id** | a retried POST within one execution is deduplicated; every execution is recorded |

### Failure handling (all three workflows)

1. A failing call retries (max 3), then the error branch posts **one** `FAILED` run report (static text plus execution id; no response bodies, no credentials, no customer data).
2. The workflow then ends in a **Stop and Error** node, so the n8n execution is marked **failed** (not green) and n8n's own failure handling or error workflows can react.
3. Responses are validated: an alerts response that is not a JSON array, or a summary body without the expected fields, is a failure, never "no events" or an empty report. Empty lists are handled explicitly (alerts: "no new high-severity events" success; summary: failure, because the endpoint always returns a populated object).
4. If the backend is down or rejects the key, the failure report itself cannot be delivered; the n8n execution still ends in error. Check n8n's execution list.

### Notifications are development-only

The `security-alerts` workflow records one alert per HIGH-severity event in TrustLayer (`alert_deliveries`, shown on **Risk & Security**) and passes through a no-op `Development notification` node. **A recorded alert is not proof that any real notification was delivered: no email, SMS or chat message is sent.** No external provider is configured.

## Local setup

Prerequisites: Python 3.11, Node 20+ (24 used here), a Neon database, and `backend/.env` configured (see `README.md`).

```bash
# 1. backend (from backend/)
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2. frontend (from frontend/)
npm run dev

# 3. n8n (from anywhere)
npx n8n
```

First start of n8n asks you to create a **local owner account** in the editor at http://localhost:5678. Do that yourself; nothing here bypasses it.

Then in the n8n editor:

1. **Credentials → Create → Header Auth**: name `TrustLayer Automation Key`, header name `X-TrustLayer-Automation-Key`, value = `N8N_SHARED_SECRET` from `backend/.env` (placeholder in examples: `YOUR_AUTOMATION_KEY`).
2. **Workflows → Import from file** for each `n8n/*.workflow.json`. Open an HTTP node and select the credential if it is not linked automatically (a fresh instance resolved it by name in testing).
3. Check `baseUrl` in each **Config** node (`http://127.0.0.1:8000`).

### Run manually

Open a workflow and press **Execute workflow** (the *Manual test* trigger). Expected: all nodes green, last node `Report success` / `Report alerts` / `Report no new events`.

### Verify the database records

Log in as `sec.admin` (password `YOUR_DEMO_PASSWORD`, the `DEMO_PASSWORD` in `backend/.env`) and use the dashboard **Automation**, **Risk & Security** and **Audit Trail** pages, or call the API:

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login -H 'Content-Type: application/json' -d '{"username":"sec.admin","password":"YOUR_DEMO_PASSWORD"}' | python -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl -s http://127.0.0.1:8000/api/automation/workflows -H "Authorization: Bearer $TOKEN"   # run history per workflow
curl -s http://127.0.0.1:8000/api/alerts            -H "Authorization: Bearer $TOKEN"   # recorded alerts
curl -s http://127.0.0.1:8000/api/reports           -H "Authorization: Bearer $TOKEN"   # stored summary reports
curl -s "http://127.0.0.1:8000/api/audit?actor=n8n-automation" -H "Authorization: Bearer $TOKEN"   # scans started by n8n
```

To get real HIGH events for the alerts workflow, run **Risk & Security → Run scenario** (security admin).

### Enable and test schedules

Schedules only fire for **published (active)** workflows while n8n is running. In the editor, toggle the workflow to *Published*. To check quickly without waiting a day, temporarily set the Schedule node to every 1 minute, publish, watch the executions list (mode "trigger") and the Automation page, then set it back.

### Troubleshooting

| Symptom | Cause / fix |
|---|---|
| *The service refused the connection* | `baseUrl` uses `localhost` (IPv6) or the backend is not running. Use `http://127.0.0.1:8000`; check `curl http://127.0.0.1:8000/api/health`. |
| `401 Invalid automation credentials` (3 attempts, then failed run) | Credential value differs from `N8N_SHARED_SECRET`, or the credential is not selected on the HTTP node. Restart the backend after editing `.env`. |
| `429` from `/api/automation/scans` | More than 20 automation scans per minute; retried 3 times then fails. Wait a minute. |
| Execution failed but no run appears on the Automation page | The backend was unreachable or rejected the key, so the failure report could not be posted. Use n8n's execution list. |
| Alerts workflow always "no new events" | No HIGH events exist (run the risk scenario), or the cursor has passed them; a published workflow remembers its cursor, backend uniqueness prevents duplicates either way. |
| *Task Broker's port 5679 is already in use* (CLI runs) | Another n8n is running. Set `N8N_RUNNERS_BROKER_PORT` to a free port or stop the other instance. |

## What was tested (n8n 2.45.5 installed locally, real backend, Neon, synthetic data)

All runs used a scratch n8n data folder (not your own n8n) via n8n's CLI (`import:workflow`, `execute`, `publish:workflow`) and the n8n server (`start`). A fault-injecting proxy in front of the backend produced the failure cases. The workflow editor UI itself was not driven.

| Check | Result |
|---|---|
| Fresh n8n instance imports the three repo JSON files, credential resolves by name | passed |
| Scan, alerts, report happy paths | passed (alerts: real HIGH events; repeat run: *no new events*) |
| Backend health / n8n reaches `127.0.0.1:8000` | passed |
| Valid key accepted; wrong key rejected (all 3 workflows) | passed: 401 ×3, execution failed, neither the real nor the fake key appeared in n8n output |
| 500, 503, 429, 401, 403 on the main endpoint | passed: exactly 3 attempts then one `FAILED` report, execution failed. Scan endpoint: 500, 503, 429, 401, 403. Events endpoint: 503. Summary endpoint: 503. Report store: 503 and 401. Alert recording: 500 |
| Connection refused | passed: 3 attempts, execution failed (no report possible) |
| Request timeout (test copy with 5 s timeout, endpoint hangs) | passed: 3 attempts then `FAILED` report |
| Invalid JSON / HTML / empty body (all three workflows) | passed: reported `FAILED`; HTML events no longer read as "no events"; empty summary no longer silent |
| Alert recording fails for 12 events | passed: bounded (3 tries per event), a single failure report |
| Duplicate protection: repeated scan (same hour), repeated report (same day), repeated alerts, cursor lost | passed: one scan, one report, alert rows unchanged |
| Scheduled triggers | passed: scan copy (1 min) fired 5 times in `trigger` mode producing 1 scan; the alerts workflow with its **real 5-minute interval** fired on schedule |
| Run reports contain no secrets or customer PII | passed (all 57 details recorded at that point were checked against the secrets and every synthetic PAN/email/phone/account/name) |
| Static workflow checks (`tests/test_n8n_workflows.py`) and endpoint tests | passed |

### Defects found and fixed during this verification

1. Alerts: a non-JSON (HTML) response from the events endpoint was reported as **SUCCESS: no new events**. Now validated and reported as `FAILED`.
2. Alerts: when the events endpoint failed, **both** a `SUCCESS` and a `FAILED` report were posted for the same execution (`alwaysOutputData` also fires on errors). Fetch nodes now use full-response mode (always one item).
3. Summary: an empty body silently ended the run with no report; an HTML body built and tried to store a junk report. Now validated first and reported as `FAILED`.
4. Every failure branch ended **green** in n8n. A `Stop and Error` node now marks the execution failed.
5. Alert recording failures posted one failure report per event (12 posts). Now one.

Old rows from before these fixes remain in the history (for example alerts executions 13, 23 and 26 show both a `SUCCESS` and a `FAILED` report).

### Not verified

- **Daily schedules** of `scheduled-scan` (24 h) and `summary-report` (1 day) firing at their real intervals: only the shortened scan copy and the real 5-minute alerts schedule were observed.
- Behaviour across an n8n restart (cursor persistence) and n8n's own error workflows.
- The n8n editor UI flow (owner setup, manual credential selection), and your own n8n instance on :5678: it was not modified.
- Sending real notifications (intentionally not implemented).
- Time-zone handling (idempotency keys use UTC).

### Security notes

- No secrets are in the workflow JSON (only the credential *name*); this is asserted by a test.
- The Neon connection string was pasted into a chat earlier in this project: **rotate that database password** (Neon console), update `backend/.env`, and keep `.env` out of git. Treat the demo `JWT_SECRET`, `N8N_SHARED_SECRET` and `DEMO_PASSWORD` values as development placeholders; replace them before sharing the app.
- Keep the backend bound to `127.0.0.1`. Exposing it publicly would also expose the login endpoint and demo accounts.

## n8n Cloud workspace (trustlayer-n8n.app.n8n.cloud), as of 2026-10-30

| Workflow | ID | Trigger | State |
|---|---|---|---|
| TrustLayer - Scheduled scan | `s3YQlAYMUj2aVACO` | daily 02:00 (fixed: an "every 24 hours" interval is rejected by n8n) | unpublished |
| TrustLayer - Security alerts | `803XRsGOd1PrvwAG` | every 5 minutes | unpublished |
| TrustLayer - Audit summary report | `RH43n7fGJMk187Qs` | daily | unpublished |
| TrustLayer - Scheduled scan (on demand) | `QP8iouEYz5LEh7td` | webhook `trustlayer-on-demand-scan` (header auth) | unpublished |
| TrustLayer - Security alerts (on demand) | `5g8EuHRGJ4kPFB8L` | webhook `trustlayer-on-demand-alerts` (header auth) | unpublished |
| TrustLayer - Audit summary report (on demand) | `6Yt1GLN8u2jLos5m` | webhook `trustlayer-on-demand-summary` (header auth) | unpublished |

None of them can run end to end yet. Before publishing:
1. n8n Cloud cannot reach `localhost`: set `Config.baseUrl` in each workflow to a public https URL that reaches the TrustLayer backend.
2. Create two credentials in n8n and attach them to the HTTP Request and Webhook nodes: **TrustLayer Automation Key** (the custom auth the
   HTTP nodes use, carrying `N8N_SHARED_SECRET`) and **TrustLayer Trigger Key** (Header Auth, header `X-TrustLayer-Trigger-Key`, value `N8N_TRIGGER_SECRET`).
3. In `backend/.env` set `N8N_WEBHOOK_BASE_URL=https://trustlayer-n8n.app.n8n.cloud/webhook` so the assistant calls the cloud webhooks.
Only the on-demand scan's branching was tested, with pinned (simulated) HTTP responses.
