# TrustLayer

**Decision-level data minimization for BFSI.** TrustLayer discovers sensitive columns, classifies them, and returns each requester only what their role needs.
Every decision is explained and audited, with names and strategies only, never data values.

> Prototype on synthetic data. Not a compliance certification. Masking reduces exposure; it does not guarantee anonymity.

## Features

| Area | What it does |
|---|---|
| **Smart masking** | Tags PII and financial columns automatically and masks results by role (Admin sees real values, Support partial masks, Analyst hashes or redaction). Stored data is never changed. |
| **Hybrid PII detection** | Rules plus an optional ML model; CSV upload analysis. |
| **Policies** | Per-role and per-user rules, editable by Admins. Backend-enforced; the browser is never trusted. |
| **Audit Center** | Who, what, where, why and result for every query, denied attempt and policy change. |
| **Assistant** | Chat and live voice avatar (Groq, Sarvam, LiveKit, Tavus). Answers come from the real audit trail, in English and Indian languages. |
| **Automation** | Optional n8n workflows for scans, alerts and reports. |

## Stack

FastAPI · SQLAlchemy · Alembic · Neon PostgreSQL / SQLite · React 19 + Vite + Tailwind · LiveKit Agents · n8n (optional)

## Quick start

```bash
# Backend
cd backend
py -3.11 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
cp .env.example .env            # fill in values; never commit .env
.venv/Scripts/alembic upgrade head
.venv/Scripts/python -m scripts.seed
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Frontend (new terminal)
cd frontend
npm install
npm run dev                     # http://localhost:5173, proxies /api to :8000

# Voice avatar (optional, separate process)
cd voice_agent
.venv/Scripts/python agent.py dev
```

Sign in as `admin_anita`, `support_ravi` or `analyst_kavya` with the `DEMO_PASSWORD` from your `.env`.

## Tests

```bash
cd backend && .venv/Scripts/python -m pytest -q       # isolated in-memory DB, never touches Neon
cd voice_agent && .venv/Scripts/python -m pytest test_agent.py
```

## Documentation

| Topic | File |
|---|---|
| Three-minute demo and voice commands | [docs/DEMO.md](docs/DEMO.md) |
| Masking engine, dataset import, API | [docs/B1.md](docs/B1.md) |
| Audit, "why" and activity history | [docs/AUDIT_AND_ACTIVITY.md](docs/AUDIT_AND_ACTIVITY.md) |
| PII detection and evaluation | [docs/DETECTION.md](docs/DETECTION.md) · [docs/EVALUATION.md](docs/EVALUATION.md) |
| Voice avatar and languages | [docs/VOICE.md](docs/VOICE.md) |
| n8n workflows | [docs/N8N.md](docs/N8N.md) |
| Design | [docs/DESIGN.md](docs/DESIGN.md) |

## Known limitations

- Demo accounts share one password; a real deployment needs an identity provider.
- Rate limiting is in-process; scans are synchronous; audit retention is unmanaged.
- Classification can be wrong, which is why Admins review it.
- Voice needs funded LiveKit, Sarvam and Tavus keys plus the running worker.
- MySQL support is implemented but unverified against a live server.
