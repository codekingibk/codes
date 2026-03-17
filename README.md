# Codes

A Flask web app for VIP, Correct Score, Draw, VVIP package viewing, admin user management, and live soccer data integration using EasySoccerData.

## Fast Start (Windows)

### Option 1: PowerShell (recommended)

1. Open PowerShell in this folder.
2. Run:

```powershell
./start.ps1
```

If script execution is blocked, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
./start.ps1
```

### Option 2: Double-click launcher

Double-click `start.bat`.

## Manual Start

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

## Access

- Local: http://127.0.0.1:5000
- Admin login key is generated/stored in the database and shown in startup logs.

## Main Features

- VIP, Correct Score, Draw, and VVIP data dashboards
- Admin: create users, reset keys, view all games
- Notifications and historical/winning game views
- Live Soccer Center powered by EasySoccerData

## Notifications

- Users can enable alerts from the dashboard with `Enable Website Notifications`.
- Click `Allow Browser Alerts` to grant browser permission.
- Admins can send broadcast notifications from the dashboard (`Admin Notification Broadcast`).

## Deploy on Render

This repo includes `render.yaml`, `Procfile`, and `wsgi.py`.

1. Push this project to GitHub.
2. In Render, create a new Web Service from the repo.
3. Render will detect `render.yaml` automatically.
4. Confirm settings:
	- Build Command: `pip install -r requirements.txt`
	- Start Command: `gunicorn wsgi:app`
5. Deploy.

Environment and persistence:

- `PYTHON_VERSION=3.11.9`
- `SECRET_KEY=<a-strong-random-secret>`
- `DATABASE_URL` is automatically wired from the managed database in `render.yaml`.

Important:

- Render free filesystem is ephemeral. If you do not use Postgres (or a persistent disk), users will be lost on restart.
- This repo now defines a managed Render Postgres database in `render.yaml` (`codes-db`) to prevent data loss.

### One-time migration of local users to Render Postgres

After deploying with `DATABASE_URL` set to Render Postgres, run:

```bash
python migrate_users.py
```

This migrates users and notifications from local SQLite (`database/users.db`) into the configured database.

### Self ping / keepalive

This project includes built-in self-ping support:

- `ENABLE_SELF_PING=true`
- `SELF_PING_INTERVAL_SECONDS=600`
- `SELF_PING_URL` (optional; auto-uses `RENDER_EXTERNAL_URL` when available)

Health endpoint used by keepalive: `GET /healthz`

Important limitation:

- Render free web services can still spin down due to platform policy. Self-ping helps activity checks, but it is not a guaranteed always-on solution on free tier.
- For reliable always-on uptime, use a paid Render instance or an external uptime monitor/cron hitting `/healthz`.

## Deploy on PXXL (Docker-based)

If your PXXL project supports Docker deployments:

1. Push this repo to GitHub.
2. Create a new app in PXXL from the repo.
3. Choose Docker deployment mode.
4. It will use:
	- `Dockerfile`
	- `.dockerignore`
5. Expose port `10000` (already configured in the image command).

If your PXXL setup is not Docker-based, use:

- Install command: `pip install -r requirements.txt`
- Start command: `gunicorn wsgi:app --bind 0.0.0.0:$PORT`
- Env vars: `SECRET_KEY` and `DATABASE_URL` (point to persistent Postgres)

## Notes

- EasySoccerData is in early development; source reliability may vary by provider.
- The app defaults to Sofascore for live soccer feed and falls back when needed.
# codes
