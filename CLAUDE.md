# Project: Davis Weather Station Web UI

Web dashboard and logger daemon for Davis weather stations (Vantage Pro, Weather Monitor II, etc.). Serial communication via a custom protocol driver, with a FastAPI backend and React/TypeScript frontend.

## Repository Structure

- `backend/` — Python FastAPI app + logger daemon
  - `app/api/` — REST API endpoints
  - `app/protocol/` — Davis serial protocol driver (link layer, memory map, constants)
  - `app/services/` — Background services (poller, archive sync, upload services)
  - `app/ipc/` — IPC server/client for logger daemon communication
  - `app/output/` — Output format generators (APRS, METAR)
  - `logger_main.py` — Standalone logger daemon (serial owner, poller, IPC server)
  - `main.py` — FastAPI web application entry point
- `frontend/` — React + TypeScript + Vite
  - `src/pages/` — Page components (Dashboard, History, Settings, etc.)
- `debian/` — Debian packaging (two systemd services)
- `reference/` — Davis technical reference docs

## Git Workflow

- **Development branch**: `dev/wx-app` (local) — all development work happens here; tracks `origin/main`
- **Debian packaging branch**: `deb` — for Debian package builds; cherry-pick from dev/wx-app
- **Main branch**: `origin/main` — receives pushes from dev/wx-app; will become stable-only after post-beta release
- Always commit to `dev/wx-app` and push to `origin/main` unless explicitly told otherwise

## Build

- Frontend: `cd frontend && npm run build`
- Backend: Python 3.11+, dependencies in `backend/requirements.txt`
- Debian package: `dpkg-buildpackage -us -uc -b` from repo root

## Key Patterns

- Config stored in `station_config` SQLite table; defaults in `backend/app/api/config.py` `_DEFAULTS` dict
- Upload services (WU, CWOP) reload config from DB each cycle — Settings UI changes take effect immediately
- Logger daemon owns the serial port; web app communicates via IPC (TCP JSON messages)
- Hardware config (archive/sample periods) cached at connect time to avoid serial contention
