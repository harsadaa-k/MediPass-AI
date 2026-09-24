# Deployment (Railway, no Docker)

Both parts run on Railway in one project (`outstanding-comfort`), built from
this repo by Railway's automatic builder (Railpack):

| Service | Root directory | Address |
|---|---|---|
| **MediPass-AI** (backend, FastAPI) | `/backend` | https://medipass-ai-production.up.railway.app |
| **medipass-frontend** (React/Vite, served as a static site) | `/frontend` | https://medipass-frontend-production.up.railway.app |

Pushing to `main` redeploys both. Railway has deprecated `railway.json`, so the
settings below live on the services (dashboard → service → Settings /
Variables, or `railway api`).

## Backend service settings

- **Start command:** `sh -c 'uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips="*"'`
- **Health check:** `/health` (timeout 120 s). **Restart:** on failure, 5 retries.
- **Replicas: 1.** The database is SQLite on a volume, which is single-writer.
- **Volume** `medipass-ai-volume` mounted at **`/data`**: database, uploads,
  email log. It survives redeploys.
- Python version from `backend/.python-version` (3.11).

**Variables:**

| Variable | Value |
|---|---|
| `MEDIPASS_ENV` | `production` |
| `MEDIPASS_SECRET_KEY` | long random string: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `GEMINI_API_KEY` | Gemini key |
| `SMTP_SERVER` / `SMTP_PORT` | `smtp.gmail.com` / `587` |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | sending Gmail address and its app password |
| `MEDIPASS_DATABASE_URL` | `sqlite:////data/medipass.db` (four slashes) |
| `MEDIPASS_UPLOAD_DIR` | `/data/uploads` |
| `MEDIPASS_EMAIL_LOG` | `/data/logs/email.log` |
| `MEDIPASS_SEED_DEMO` | `false` (the demo passwords are public) |
| `MEDIPASS_SKIP_EMAIL_VERIFICATION` | `false` |
| `MEDIPASS_CORS_ORIGINS` | the frontend address |
| `MEDIPASS_FRONTEND_URL` | the frontend address (links in emails) |
| `RAILPACK_DEPLOY_APT_PACKAGES` | `tesseract-ocr` (local OCR fallback) |
| `MEDIPASS_REVIEWER_EMAILS` | emails that get the **Review doctors** screen, comma-separated |

## Frontend service settings

- Railpack detects Vite, builds it and serves `dist/` as a single-page app, so
  `/login`, `/verify-email` and `/add-patient/…` all load the app.
- **Variable:** `VITE_API_URL` = the backend address, with no trailing slash.
  It's built into the bundle, so **redeploy the frontend after changing it**.
- `frontend/vercel.json` is only used if the frontend is ever hosted on
  Vercel instead.

## Operating it

- **Logs:** `railway logs --service MediPass-AI` (add `--build <id>` for a
  build log); `railway deployment list --service MediPass-AI`.
- **Approve doctors:** log in with a reviewer account → **Review doctors**.
- **Or approve / read the email log on the server:** open the service's
  shell (dashboard → service → Console, or `railway ssh` after adding an SSH
  key), then `python review_doctors.py list` /
  `approve <email> "note" --by "Name"`, or `cat /data/logs/email.log`.
- **Changing the frontend address:** update both `MEDIPASS_CORS_ORIGINS` and
  `MEDIPASS_FRONTEND_URL` on the backend.

## Later: Postgres

Set `MEDIPASS_DATABASE_URL` to a Postgres URL (`postgresql+psycopg2://…`) and
add `psycopg2-binary` to `requirements.txt`. Uploads still need the volume, or
object storage via `app/storage.py`. With Postgres, the backend can run more
than one replica.
