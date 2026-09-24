# Deployment: backend on Railway, frontend on Vercel

No Docker. Railway builds the backend straight from `requirements.txt`
(Railpack) and Vercel builds the Vite frontend.

Config in the repo:
- `backend/railway.json`: start command, `/health` health check, restart policy
- `backend/.python-version`: Python 3.11
- `frontend/vercel.json`: sends every route (`/verify-email`, `/add-patient/…`) to the app

## 1. Backend on Railway

1. **New Project → Deploy from GitHub repo →** `harsadaa-k/MediPass-AI`.
2. **Service → Settings:**
   - **Root Directory:** `/backend`
   - **Config-as-code file path:** `/backend/railway.json` (Railway doesn't look
     inside the root directory for it on its own)
3. **Add a volume** (right-click the service → *Attach volume*), mount path
   **`/data`**. The database and uploaded documents live there, so they survive
   redeploys.
4. **Variables:**

   | Variable | Value |
   |---|---|
   | `MEDIPASS_ENV` | `production` |
   | `MEDIPASS_SECRET_KEY` | a long random string (see below) |
   | `GEMINI_API_KEY` | your (rotated) Gemini key |
   | `MEDIPASS_DATABASE_URL` | `sqlite:////data/medipass.db` (four slashes) |
   | `MEDIPASS_UPLOAD_DIR` | `/data/uploads` |
   | `MEDIPASS_EMAIL_LOG` | `/data/logs/email.log` |
   | `MEDIPASS_SEED_DEMO` | `false` (the demo passwords are public) |
   | `MEDIPASS_SKIP_EMAIL_VERIFICATION` | `false` |
   | `SMTP_SERVER` / `SMTP_PORT` | `smtp.gmail.com` / `587` |
   | `SMTP_USERNAME` / `SMTP_PASSWORD` | the sending Gmail address and its (rotated) app password |
   | `RAILPACK_DEPLOY_APT_PACKAGES` | `tesseract-ocr` (local OCR fallback) |
   | `MEDIPASS_CORS_ORIGINS` | your Vercel address, e.g. `https://medipass-ai.vercel.app` (fill in after step 2) |
   | `MEDIPASS_FRONTEND_URL` | the same Vercel address (links in emails) |

   Random secret: `python -c "import secrets; print(secrets.token_urlsafe(48))"`

5. **Settings → Networking → Generate Domain.** That's the backend URL, e.g.
   `https://medipass-ai-production.up.railway.app`. Check
   `<backend URL>/health` returns `{"status":"ok"}`.

One instance only: SQLite on a volume is single-writer, so don't scale the
service to more replicas.

## 2. Frontend on Vercel

1. **Add New → Project →** import `harsadaa-k/MediPass-AI`.
2. **Root Directory:** `frontend`. The framework (Vite), build command and output
   (`dist`) are detected.
3. **Environment variable:** `VITE_API_URL` = the Railway backend URL (no
   trailing slash). It's built into the app, so **redeploy after changing it**.
4. **Deploy**, then copy the production address (e.g. `https://medipass-ai.vercel.app`).

## 3. Connect them

On Railway set `MEDIPASS_CORS_ORIGINS` and `MEDIPASS_FRONTEND_URL` to the
Vercel address, and let the backend redeploy. Only that address is allowed to
call the API. Vercel *preview* URLs aren't allowed; add them comma-separated
if needed.

## 4. First login and reviewer

- Register normally: the email verification link points to the Vercel address.
- To approve a doctor on the server, use Railway's shell for the service:
  `python review_doctors.py list` / `approve <email> "note" --by "Name"`.
- To see email delivery: `cat /data/logs/email.log` in the same shell.

## Later: Postgres

Set `MEDIPASS_DATABASE_URL` to a Postgres URL
(`postgresql+psycopg2://…`) and add `psycopg2-binary` to `requirements.txt`.
Uploads still need the volume (or object storage via `app/storage.py`).
