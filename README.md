# TrustLayer

Decision-level data minimization for BFSI: discover sensitive fields, classify them, and return each requester only what their role and declared purpose need, protected by an explicit policy, with every decision explained and audited. Includes an illustrative life-insurance needs assessment that runs on minimized inputs.

**Prototype using synthetic data only.** Not a compliance certification. Masking reduces exposure but does not guarantee anonymity or prevent all leakage.

## Stack

FastAPI · Pydantic · SQLAlchemy · Alembic · Neon PostgreSQL (psycopg 3) · SQLGlot (parser only) · Presidio + deterministic rules · React 19 + Vite + Tailwind 3 + Radix + Framer Motion + Lucide (JavaScript, no TypeScript) · n8n for orchestration.

Versions actually used while building: Python 3.11, Node 24, npm 11 (see `backend/requirements.txt` and `frontend/package.json`).

## Setup

### 1. Backend

```bash
cd backend
py -3.11 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
cp .env.example .env     # then edit .env
```

Edit `backend/.env` (git-ignored). `DATABASE_URL` is your Neon connection string (Neon dashboard → Connect). A plain `postgresql://…` URL is accepted; the driver is selected automatically. Set long random `JWT_SECRET`, `N8N_SHARED_SECRET`, and a `DEMO_PASSWORD` for the synthetic demo users. Never commit `.env`.

```bash
.venv/Scripts/alembic upgrade head          # create tables
.venv/Scripts/python -m scripts.seed        # synthetic users + 12 customers (idempotent)
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

API docs: http://127.0.0.1:8000/api/docs

### 2. Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /api to :8000
npm run build      # production build
```

### 3. Tests

```bash
cd backend
.venv/Scripts/python -m pytest -q
```

Tests run on an isolated in-memory SQLite database and never touch Neon (`conftest.py` overrides `DATABASE_URL`). Presidio is disabled in tests for speed.

### 4. n8n (optional orchestration, local only)

```bash
npx n8n      # editor at http://localhost:5678 (first start: create a local owner account)
```

Import the three files in `n8n/`, create the `TrustLayer Automation Key` Header Auth credential (value = `N8N_SHARED_SECRET` from `backend/.env`), keep `baseUrl` at `http://127.0.0.1:8000` (not `localhost`; see the doc for why), and run each workflow manually. Import steps, schedule testing, troubleshooting, the idempotency rules, and exactly what was and was not verified are in [docs/N8N.md](docs/N8N.md). n8n Cloud cannot reach a local backend and is not used.

## Dashboard

Sidebar sections (visibility follows role; the server enforces permissions independently):

| Section | Who | Backed by |
|---|---|---|
| Overview | all (scoped to own activity for non-auditors) | `/api/metrics/overview`, `/api/scans`, `/api/audit`, `/api/automation/workflows` |
| Data Discovery | all view; admin scans; admin/compliance review | `/api/sources`, `/api/scans`, `/api/fields`, `/api/fields/{id}` |
| Policies & Masking | all view; admin edits | `/api/policies/all`, `POST/PATCH/DELETE /api/policies`, `/api/policies/simulate` |
| Access Console | all | `/api/access/evaluate`, `/api/query` |
| Risk & Security | admin, compliance | `/api/risk/events`, `/api/risk/evaluations`, `/api/risk/scenarios/reconstruction`, `/api/alerts` |
| Audit Trail | admin, compliance (others see own requests) | `/api/audit` (server-side filters and pagination) |
| Insurance Needs | advisor | `/api/insurance/config`, `/customers`, `/assess`, `/estimate` |
| Automation | admin, compliance | `/api/automation/workflows`, `/api/reports` |
| Settings | all (read-only, no secrets) | `/api/settings` |

Every number comes from persisted records. Empty data shows an empty state; failed requests show the error with a retry button, never substitute data. There is no global search or other control that does nothing; the bell badge counts real HIGH-severity security events.

## Demo script (synthetic data)

Demo accounts (password = your `DEMO_PASSWORD`): `sec.admin`, `compliance1`, `advisor1`, `analyst1`.

1. Sign in as `sec.admin` → **Data Discovery → Scan now**. Open a field for evidence, per-role policy outcomes and related audit events; correct a classification if needed.
2. **Policies & Masking**: use the demonstrator (synthetic original → classification → policy → output), then edit a rule and see the next request change.
3. Sign in as `advisor1` → **Access Console**, purpose `insurance_assessment`: PAN is withheld, name redacted, income is a band. Open **Inspect decision**.
4. **Insurance Needs** → pick a synthetic customer or enter what-if values → calculate. See inputs used and attributes never loaded.
5. As `sec.admin` → **Risk & Security → Run scenario**: real reconstruction-style probes run under a dedicated synthetic principal, are allowed, then blocked, and appear as security events. `compliance1` sees them under **Audit Trail** and **Risk & Security**.
6. Import and run the n8n workflows ([docs/N8N.md](docs/N8N.md)); **Automation** shows the real run history.

## What is supported

- **Data source:** the synthetic `customers` table in the app database (explicit allow-list; no arbitrary table scanning).
- **SQL gateway** (`POST /api/query`): single `SELECT cols|* FROM customers [WHERE col op literal AND …] [ORDER BY col] [LIMIT ≤50]`. Joins, subqueries, CTEs, UNION, GROUP BY, functions, expressions, aliases, comments and multiple statements are rejected. User SQL is parsed, never executed; a parameterized query is rebuilt from the validated AST. Filtering/sorting on any column that is not returned in the clear (ALLOW) is refused, to stop value inference.
- **Policies** are rows in the `policies` table (seeded from the reviewed defaults in `backend/app/policies/rules.py`), editable by security admins with validation (critical IDs can never be `ALLOW`). Absent or disabled rules mean deny. Every change is audited.
- **Strategies:** `FULL_MASK` (fixed `********`), `PARTIAL_MASK` (last 4 for IDs/phones, initials for names, `a***@domain` for emails, year for dates, ranges for numbers), `REDACT`, `HASH` (keyed HMAC-SHA256 prefix), `DENY` (field omitted). Originals are never modified.
- Details: [docs/DESIGN.md](docs/DESIGN.md).

## Known limitations

- Single-process in-memory rate limiter; risk windows are computed from the audit table. No distributed rate limiting.
- Role/permission mapping (`PERMISSIONS`) is code; only the (role, purpose, category) → strategy rules are editable.
- Scans are synchronous (the request waits). There is no background job queue.
- Against a remote Neon database from far away each query costs a network round trip (~0.35 s measured here), so multi-query pages take 1–3 s. Colocating the backend with the database removes most of this.
- Risk scenario runs six real requests and takes ~30 s on a remote database.
- Alerts go to a development channel only (recorded in TrustLayer); no email/SMS/chat provider is configured.
- Classification uses name heuristics + patterns + Presidio on 20 sampled rows; it can be wrong, hence the review step.
- The insurance calculation is **illustrative**, not an approved formula.
- Numeric "partial mask" returns coarse bands; small bands can still leak order-of-magnitude information.
- Audit retention is unmanaged (kept until purged manually).
- n8n workflows are optional and not a security boundary; `docs/N8N.md` lists what was verified (including failure modes and schedules) and what was not (the daily schedules at their real interval, n8n restarts, the editor UI flow).
- Presidio's first scan takes ~15 s (model load) against Neon.
- The demo login uses a shared demo password for synthetic accounts; real deployments would need an identity provider.
- Rotate any credential that has been pasted into chat or shared outside `.env`.
