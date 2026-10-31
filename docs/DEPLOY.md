# Deployment (Vercel + Render + Neon)

| Part | Where | Notes |
|---|---|---|
| Frontend | Vercel, root `frontend` | static Vite build; the browser calls the Render backend directly using `VITE_API_URL` (CORS must allow the Vercel origin) |
| Backend | Render web service, root `backend` | `alembic upgrade head` runs at build time; health check `/api/health` |
| Voice avatar | Render background worker, root `voice_agent` | optional; without it everything works except the live avatar |
| Database | Neon PostgreSQL | Render's disk is ephemeral, so SQLite is not used in production |

`render.yaml` at the repo root describes both Render services. Every secret is `sync: false`: type it into the dashboard, never into git.

## 1. Backend on Render
Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (note `app.main:app`; `app.main` alone fails). Root directory `backend`.
Required: `CORS_ORIGINS=https://trustlayer-eight-mocha.vercel.app` (exact origin, no trailing slash or path; comma-separate several), `APP_ENV=production`, `DATABASE_URL` (`postgresql+psycopg://...`), `JWT_SECRET` (32+ chars), `N8N_SHARED_SECRET` (16+), `DEMO_PASSWORD`.
Optional features: `GROQ_API_KEY`/`GROQ_MODEL` (assistant), `SARVAM_API_KEY` (speech), `LIVEKIT_*`, `TAVUS_*`, `VOICE_AGENT_SECRET` (avatar).
Keep `DETECTION_ML_ENABLED=false` and `B1_ML_SUPPLEMENT=false` on small instances; rule-based detection still runs.
Once, from a machine with `DATABASE_URL` pointed at Neon: `python -m scripts.seed` and `python -m scripts.seed_b1` (users and policies), and `python -m scripts.load_saffron_pg` for the Saffron schema.

## 2. Frontend on Vercel
Root Directory `frontend`, framework Vite, build `npm run build`, output `dist`.
Set `VITE_API_URL=https://trustlayer-87fn.onrender.com` (Production, and Preview if used). Vite inlines it at build time, so **redeploy after changing it** (a new build, not just a restart). The API base is built in one place, `frontend/src/lib/api.js`, as `${VITE_API_URL}/api`; a trailing slash or `/api` on the value is tolerated. Unset, the app calls same-origin `/api`, which is what the local Vite proxy expects.
Do not also add a `/api` rewrite in `vercel.json`: one mechanism only.

## 3. Voice worker (optional)
Background worker, root `voice_agent`, start `python agent.py start`. Same `VOICE_AGENT_SECRET` and provider keys as the backend, plus `TRUSTLAYER_BACKEND_URL=https://<your-api>.onrender.com`.

## Checks before going live
- `GET /api/health` returns `status: ok`, `database.connected: true`, `config_ok: true` (it lists any weak secret by name, never its value).
- Sign in as each role and open Live Activity (Admin) to confirm the audit trail is writing.
- Rotate any key that was ever pasted into chat or a ticket.

## Operational notes
- Logs go to stdout (Render captures them); unhandled errors are logged by type only, never with request data.
- The analytics and rate-limiter caches are per process. With more than one backend instance, each instance caches for at most 5 s (analytics) and rate limits per instance; move the limiter to Redis before scaling out.
- Free Render instances sleep when idle; the first request can take about 30 s.
