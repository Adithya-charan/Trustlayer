# TrustLayer: technology stack, start to end

TrustLayer is a privacy-first data-access prototype for financial/insurance (BFSI) data. It discovers sensitive fields, enforces
role- and purpose-based policies on every request, masks or denies what a role may not see, records a value-free audit trail, flags
risky patterns, automates routine work with n8n, and offers a typed and spoken AI operator on top. **All data is synthetic.** It is a
prototype, not a compliance certification.

Versions below are the ones pinned in `backend/requirements.txt`, `frontend/package.json` and `voice_agent/requirements.txt`.

## 1. At a glance

| Layer | Technology |
|---|---|
| Frontend | React 19, Vite 6, Tailwind CSS 3, framer-motion, Radix UI, lucide-react |
| Backend API | Python 3.11, FastAPI, Uvicorn, Pydantic 2 |
| Database | Neon (hosted PostgreSQL) via SQLAlchemy 2 + psycopg 3; Alembic migrations; in-memory SQLite for tests |
| Sensitive-data detection | Microsoft Presidio (spaCy `en_core_web_sm`) plus deterministic column-name and format rules |
| Query safety | SQLGlot (parses SQL; the gateway accepts one narrow `SELECT` shape only) |
| Auth and crypto | JWT (PyJWT, HS256), bcrypt, constant-time secret comparison |
| Automation | n8n 2.45.6 (self-hosted), 3 workflows plus 3 on-demand webhook copies |
| AI reasoning | Groq (`openai/gpt-oss-120b`) through the `groq` SDK 1.7.0 |
| Speech | Sarvam AI (`saaras:v4` speech-to-text, `bulbul:v3` text-to-speech) |
| Real-time audio | LiveKit Cloud; `livekit-api` 1.2.2 (backend), `livekit-client` 2.23 (browser), `livekit-agents` 1.8.10 (worker) |
| Avatar | Tavus (face rendered inside the LiveKit room via `livekit-plugins-tavus`) |
| Voice activity detection | Silero VAD on ONNX Runtime |
| Testing | pytest (backend and agent), ESLint, Vite production build |

## 2. Frontend (`frontend/`)
- **React 19 + Vite 6**: single-page app. Vite's dev server proxies `/api` to the backend on port 8000.
- **Hash router** (`src/lib/router.js`, no router library): public landing page, sign-in, and the dashboard pages. Page visibility mirrors
  the backend's roles, but the server enforces the real permissions.
- **Tailwind CSS 3** with a light "fintech" design system (tokens in `tailwind.config.js`), `clsx` + `tailwind-merge` for class handling.
- **framer-motion** for page transitions and the slide-in chat panel (honours reduced-motion), **Radix UI** (dialog, tabs) for accessible
  primitives, **lucide-react** icons.
- **API client** (`src/lib/api.js`): bearer-token `fetch` wrapper; token kept in `sessionStorage`.
- **Pages**: Overview, Data Discovery, Data Explorer, Access Policies, Users & Access, Audit Center, Voice Assistant, Settings, plus the
  **Voice Command** panel in the top bar (`src/voice/`). Automation (n8n run history) shows only for security-admin and compliance accounts.
- **Assistant UI** (`src/assistant/`): floating "Ask AI" button and right-side chat panel, result cards (security events, scans,
  automation, workflow status), microphone dictation (`MediaRecorder`), spoken replies, and the live-voice stage (LiveKit video of the avatar,
  connection and assistant states).

## 3. Backend (`backend/app/`)
- **FastAPI + Uvicorn**, Pydantic 2 request/response validation, `pydantic-settings` reading `backend/.env`.
- **SQLAlchemy 2** models (11 tables): `User`, `Customer`, `FieldClassification`, `ScanRun`, `AuditEvent`, `SecurityEvent`, `WorkflowRun`,
  `Policy`, `AlertDelivery`, `AuditReport` plus the declarative base. **Alembic** holds 2 migrations.
- **Scanner** (`scanner/`): inspects the schema, classifies columns (government ID, account ID, direct identifier, contact, financial,
  demographic, non-sensitive) using Presidio + rules, with a confidence and rationale; reviewers can override a classification.
- **Policy engine** (`policies/`): role + purpose + classification maps to a strategy; absent or disabled rules mean deny.
- **Masking** (`masking/`): `ALLOW`, `PARTIAL_MASK`, `FULL_MASK`, `REDACT`, `HASH` (keyed), `DENY`. Originals are never modified.
- **SQL gateway** (`policies/sql_gateway.py`, SQLGlot): one `SELECT` on one allow-listed table, AND-ed comparisons, bounded `LIMIT`;
  everything else is rejected.
- **Risk detector** (`risk/`): deterministic rules (repeated restricted access, reconstruction pattern, volume) raise a score and a response
  (elevated masking or block).
- **Audit** (`audit/`): records field names, categories, strategies and decisions only. A scrubber blocks values that look like PAN,
  account numbers or emails.
- **Minimization + insurance** (`minimization/`, `insurance/`): reads only seven needed columns to compute an illustrative cover estimate.
- **Security helpers** (`core/security.py`): JWT issue/verify, role checks, an in-memory sliding-window rate limiter, constant-time
  comparison for the n8n automation key.
- **Seed** (`scripts/seed.py`): creates synthetic customers and the four demo users (security admin, compliance officer, advisor, analyst).

## 4. Automation with n8n (`n8n/`)
- **Three workflows** (scheduled scan, security alerts, audit summary report). Each has a Schedule trigger and a Manual trigger, a
  Config node, HTTP Request nodes authenticated by a Header Auth credential, bounded retries, explicit failure branches, and idempotency
  keys. They report every run to TrustLayer (`workflow_runs`), which the Automation page displays.
- **Orchestration only**: n8n calls `/api/automation/*` with a shared secret; it can read minimized metadata and record runs but cannot read
  customer data or change policy.
- **On-demand copies** (`n8n/on-demand/`, generated by `backend/scripts/make_on_demand_workflows.py`): same logic with one
  header-authenticated Webhook trigger and **no schedule**, so the assistant can start them without enabling a timer. Not published until
  the owner publishes them.
- n8n 2.45.6 is installed from npm in `E:\n8n-local` and keeps its data in `~/.n8n`.

## 5. AI assistant (typed and spoken)
- **Groq**: picks at most one tool from an explicit allow-list (`assistant/tools.py`): security events, recent scans, start scan, automation
  status, three n8n workflow runs, navigate, explain page. It never executes anything and cannot run SQL, shell or free-form HTTP.
  The default model, `openai/gpt-oss-120b`, was chosen after listing the account's available models and testing tool calling
  (`llama-3.3-70b-versatile` returned 404 on the tested account).
- **Command router** (`assistant/service.py`): validates tool name, arguments and the caller's current role; consequential tools return a
  signed, single-use, 5-minute confirmation that only the user's own session can redeem; every attempt is audited.
- **Sarvam** (`assistant/voice.py`): the backend proxies speech-to-text and text-to-speech so the key never reaches the browser.
- **LiveKit + Tavus + agent worker** (`assistant/live.py`, `voice_agent/`): the backend mints a least-privilege room token (microphone
  publish only, 10 minutes) and a 15-minute agent ticket. A separate Python worker (own virtualenv) joins the room, listens with Sarvam,
  asks the backend for the answer, speaks with Sarvam, and renders it through the Tavus avatar. The worker holds no model key and cannot
  confirm anything.
- Full flow and setup: [`docs/VOICE.md`](VOICE.md).

## 5b. B1 data-protection engine (`backend/app/b1/`, `frontend/src/pages/`)
- **Target** (`targets.py`): one SQLAlchemy engine for the organizer's Saffron Bank dataset in **Neon PostgreSQL** (schema `saffron_bank`), READ ONLY transactions, live health check (connected, schema found, table count, `transaction_read_only`). SQLite was removed as a backend.
- **Detection** (`detect.py`, `discover.py`): column-name rules, regex value patterns, a Luhn check for cards and a free-text scan; stores tags, confidence and methods
  in `b1_field_tags` (one additive Alembic migration), never sampled values.
- **Masking** (`mask.py`, `query.py`): Admin real, Support partial, Analyst redaction or keyed hashes (HMAC-SHA256); names known from the database are scrubbed from
  free text. Queries are a validated structured request (or one `SELECT` parsed with **sqlglot**), with allow-listed identifiers and bound parameters.
- **Tooling**: `scripts/load_saffron_pg.py` (safe, schema-isolated import), `scripts/seed_b1.py`, `scripts/verify_b1_backends.py`. See `docs/B1.md`.

## 6. Configuration and secrets
All secrets live in `backend/.env` (ignored by git). Variable **names**: `DATABASE_URL`, `JWT_SECRET`, `N8N_SHARED_SECRET`,
`DEMO_PASSWORD`, `CORS_ORIGINS`, `GROQ_API_KEY`, `GROQ_MODEL`, `SARVAM_API_KEY`, `SARVAM_LANGUAGE`, `SARVAM_TTS_SPEAKER`, `LIVEKIT_URL`,
`LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `TAVUS_API_KEY`, `TAVUS_FACE_ID`, `TAVUS_PAL_ID`, `VOICE_AGENT_SECRET`, `N8N_WEBHOOK_BASE_URL`,
`N8N_TRIGGER_SECRET`. `backend/.env.example` documents them with empty values.

## 7. Testing and tooling
- **pytest**: 143 backend tests (policy engine, masking, SQL gateway, risk, audit, auth, n8n workflow files, assistant, voice, live sessions,
  on-demand workflows) on an isolated in-memory SQLite database; provider variables are blanked so tests never touch real services.
  6 offline tests for the voice agent bridge.
- `hypothesis` is listed in `requirements.txt` but no test currently imports it.
- **ESLint 9** and the **Vite build** for the frontend.
- **Runtime**: Python 3.11, Node 24, Windows. Backend venv at `backend/.venv`, agent venv at `voice_agent/.venv`.

## 8. How the project grew
1. **Foundation**: FastAPI backend, Neon PostgreSQL, scanner, policy engine, masking, SQL gateway, risk, audit, JWT roles, React dashboard,
   three n8n workflows (single initial commit, `c70630f`).
2. **Redesign**: light fintech UI, public landing page, accessibility fixes, shared UI primitives.
3. **n8n verification**: local n8n, imported workflows, credential and header fixes, run reports, idempotency keys with timestamps.
4. **AI operator**: Groq command router with an approved-tool list and confirmations, right-side chat panel.
5. **Speech**: Sarvam speech-to-text and text-to-speech behind the backend, mic and spoken replies in the panel.
6. **Live voice**: LiveKit room + agent worker + Tavus avatar, n8n on-demand workflows, Voice Assistant page.

## 9. What is verified and what is not
- **Verified**: 143 backend tests and 6 agent tests pass; frontend builds; LiveKit credentials are accepted; Tavus face and pal exist; Groq
  chat, tool routing, security-event cards and the confirm-before-scan flow worked in the browser; no secret appears in the repo, git history
  or anything the browser downloads.
- **Not verified live**: Sarvam (the account returned HTTP 402, no credit), the agent joining a real room, the Tavus avatar speaking, the
  on-demand n8n webhooks against real n8n, and the Voice Assistant page on screen.
- **Known limits**: synthetic data and a single-process prototype (in-memory rate limiter and confirmation store); not a compliance
  certification; n8n Cloud cannot reach a backend on localhost.
