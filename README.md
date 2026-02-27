# Kanfei

A self-hosted weather station dashboard and data logger for Davis Instruments stations. Polls a WeatherLink datalogger via serial, logs all sensor data to SQLite, and presents it through a modern, theme-able browser dashboard with real-time updates, AI-powered nowcasting, and spray application advisory.

Supports the full range of classic Davis stations: Vantage Pro 2, Weather Wizard III, Weather Monitor II, Perception II, GroWeather, Energy, and Health.

## Features

- **Real-time dashboard** with SVG gauges for temperature, barometric pressure, wind speed/direction, humidity, rain, and solar/UV on a drag-resize 12-column grid
- **Historical charts** (Highcharts) with selectable sensor, date range, and resolution (raw, 5m, hourly, daily)
- **AI-powered nowcast** using Claude API with NEXRAD radar analysis, nearby station observations (ASOS/AWOS, WU PWS), verification engine, and self-improving knowledge base
- **Spray Advisor** with rule-based go/no-go engine, AI-enhanced recommendations, outcome feedback, and per-product threshold tuning
- **Forecasting**: Zambretti barometric algorithm (local) blended with NWS API data (optional)
- **Astronomy**: sunrise/sunset arc, twilight times (civil/nautical/astronomical), moon phase with illumination
- **Data uploads**: Weather Underground PWS and CWOP/APRS-IS for NWS citizen weather data
- **Database admin**: stats, JSON export, full SQLite backup, sensor data compaction, and tiered purge
- **Usage tracking**: local token aggregation with optional Anthropic Admin API for real-time cost data and budget auto-pause
- **Calculated parameters**: heat index, dew point, wind chill, feels-like composite, equivalent potential temperature (theta-e)
- **Weather backgrounds**: condition-driven gradients with custom image uploads per scene
- **Three themes**: Dark, Light, and Classic Instrumental (brass/cream analog aesthetic)
- **WebSocket push** for live sensor and nowcast updates
- **METAR output** generation (optional)
- **Cross-platform**: runs on Windows 10+, macOS, and Linux

## Quick Start

Prerequisites: **Python 3.10+** and **Node.js 18+**

```bash
git clone https://github.com/cnighswonger/davis-wx.git
cd davis-wx

python station.py setup
python station.py run
```

Open **http://localhost:8000** in your browser.

If no serial port is connected, the server starts in degraded mode — the UI loads and is fully navigable, but sensor readings will show placeholder values.

## Configuration

Setup creates a `.env` file from `.env.example`. Edit it to match your environment:

```bash
# Serial port
# Linux:   /dev/ttyUSB0  or  /dev/ttyS0
# macOS:   /dev/tty.usbserial-XXXX
# Windows: COM3  (check Device Manager -> Ports)
DAVIS_SERIAL_PORT=/dev/ttyUSB0
DAVIS_BAUD_RATE=2400

# Location (required for astronomy, NWS forecasts, and nearby stations)
DAVIS_LATITUDE=40.7128
DAVIS_LONGITUDE=-74.0060
DAVIS_ELEVATION_FT=33

# NWS forecast integration
DAVIS_NWS_ENABLED=true

# UI theme (dark, light, classic)
DAVIS_THEME=dark
```

All settings are also editable from the Settings page in the browser, including AI nowcast configuration, upload services, alerts, and spray advisor.

## Commands

| Command | Description |
|---------|-------------|
| `python station.py setup` | Create venv, install all dependencies, build frontend |
| `python station.py run` | Start production server on port 8000 |
| `python station.py dev` | Start backend (8000) + frontend HMR dev server (3000) |
| `python station.py test` | Run the backend test suite |
| `python station.py status` | Check what's installed and ready |
| `python station.py clean` | Remove venv, node_modules, and build artifacts |

On Linux/macOS, `make` targets are also available (`make setup`, `make dev`, etc.).

## Architecture

```
Browser  <──WebSocket──>  FastAPI web app  <──IPC──>  Logger daemon  <──RS-232──>  WeatherLink
           <──REST API──>  (serves UI +      (TCP)    (serial owner,               (datalogger)
                            reads DB)                  poller, DB writer)
```

The logger daemon owns the serial port and writes sensor data to SQLite. The web application reads the database and communicates with the logger via TCP IPC for hardware commands (reconnect, time sync, config writes).

### Backend (Python / FastAPI)

```
backend/
├── app/
│   ├── protocol/        # Serial driver: CRC-CCITT, LOOP parser, station detection
│   ├── models/          # SQLAlchemy ORM (sensor readings, archive, config, nowcast, spray)
│   ├── services/        # Poller, calculations, forecasts, astronomy, nowcast, CWOP, WU upload
│   ├── api/             # REST endpoints under /api
│   ├── ws/              # WebSocket handler at /ws/live
│   ├── ipc/             # IPC server (logger) and client (web app)
│   ├── output/          # METAR and APRS packet generators
│   ├── config.py        # Pydantic Settings (env vars + .env)
│   └── main.py          # Web app factory, lifespan, static file serving
└── logger_main.py       # Standalone logger daemon (serial, poller, IPC server)
```

### Frontend (React / TypeScript / Vite)

```
frontend/src/
├── components/
│   ├── gauges/          # TemperatureGauge, BarometerDial, WindCompass,
│   │                    # HumidityGauge, RainGauge, SolarUVGauge
│   ├── charts/          # TrendChart (sparkline), HistoricalChart (area)
│   ├── layout/          # AppShell, Header, Sidebar, Footer
│   └── setup/           # Setup wizard components
├── dashboard/           # DashboardGrid, DashboardTile (12-column drag-resize)
├── pages/               # Dashboard, History, Forecast, Astronomy, Nowcast,
│                        # SprayAdvisor, Settings, About
├── context/             # WeatherDataContext, ThemeContext, WeatherBackgroundContext
├── themes/              # dark, light, classic (CSS custom properties)
├── hooks/               # useWebSocket, useCurrentConditions, useIsMobile
├── api/                 # HTTP client, WebSocket manager, TypeScript types
└── utils/               # Unit conversions, formatting, timezone, constants
```

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/current` | Latest sensor reading + all derived values |
| GET | `/api/history` | Time-series data with aggregation (5m/hourly/daily) |
| GET | `/api/export` | CSV export with date range and resolution |
| GET | `/api/forecast` | Zambretti + NWS blended forecast |
| GET | `/api/astronomy` | Sun/moon times, twilight, moon phase |
| GET | `/api/station` | Station type, connection status, diagnostics |
| GET/PUT | `/api/config` | Read/update configuration |
| GET | `/api/nowcast` | Latest AI nowcast |
| POST | `/api/nowcast/generate` | Trigger a new nowcast |
| GET | `/api/nowcast/knowledge` | Knowledge base entries |
| GET | `/api/nowcast/verifications` | Verification records |
| GET | `/api/spray/products` | Spray product definitions |
| GET | `/api/spray/schedules` | Spray schedules with evaluations |
| GET | `/api/spray/conditions` | Current spray conditions summary |
| GET | `/api/usage/local` | Token usage and cost estimates |
| GET | `/api/usage/status` | Budget and API status |
| GET | `/api/db-admin/stats` | Database row counts and file size |
| GET | `/api/db-admin/export/backup` | Full SQLite database backup |
| POST | `/api/db-admin/compact` | Compact sensor readings to 5-minute averages |
| WS | `/ws/live` | Real-time sensor and nowcast updates |

## Supported Stations

| Station | LOOP Size | Sensors |
|---------|-----------|---------|
| Vantage Pro 2 | 99 bytes | Full suite including solar, UV, ET |
| Weather Wizard III | 15 bytes | Temp (in/out), humidity (in/out), wind, barometer |
| Weather Wizard II | 15 bytes | Same as Wizard III |
| Weather Monitor II | 15 bytes | Same as Wizard III |
| Perception II | 15 bytes | Same as Wizard III |
| GroWeather | 33 bytes | + soil temp, soil moisture, leaf wetness, solar radiation |
| Energy | 27 bytes | + solar radiation, UV index |
| Health | 25 bytes | + UV index |

## Hardware Setup

Connect the Davis WeatherLink datalogger to your computer via a USB-to-serial adapter (or native RS-232 port). The protocol runs at **2400 baud, 8N1** (1200 baud also supported for Wizard/Monitor series).

The application auto-detects the station model on startup by reading the model nibble from the WeatherLink's memory.

## Deployment

### Ubuntu / Debian (.deb package)

```bash
sudo dpkg -i davis-wx_0.1.0~alpha4_all.deb
```

The package installs to `/opt/davis-wx`, creates a `davis` system user, sets up two systemd services (logger daemon + web server), and places a desktop shortcut. Configuration is in `/etc/davis-wx/davis-wx.conf`.

### Manual systemd (Linux)

```bash
python station.py setup
sudo cp debian/davis-wx-logger.service /etc/systemd/system/
sudo cp debian/davis-wx-web.service /etc/systemd/system/
sudo systemctl enable --now davis-wx-logger davis-wx-web
```

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.10+, FastAPI, uvicorn |
| Serial | pyserial (2400 baud, 8N1) |
| Database | SQLAlchemy + SQLite (WAL mode) |
| AI | Anthropic Claude API (Haiku / Sonnet) |
| Astronomy | astral |
| NWS client | httpx (async) |
| Frontend | React 19, TypeScript (strict), Vite |
| Charts | Highcharts |
| Real-time | FastAPI WebSocket |

## About the Name

**Kanfei** (Hebrew: כַּנְפֵי, *kanfei ruach* — "wings of the wind") from Psalm 104:2–3 (KJV):

> *"Who coverest thyself with light as with a garment: who stretchest out the heavens like a curtain: Who layeth the beams of his chambers in the waters: who maketh the clouds his chariot: who walketh upon the wings of the wind."*

## Reference

The `reference/` directory contains the original Davis Instruments SDK materials (circa 1996–1999) documenting the PC-to-WeatherLink serial protocol: technical reference, command set, CRC tables, memory maps, and sample C/VB source code.

## License

Copyright (C) 2026 Chris Nighswonger

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, version 3. See [LICENSE](LICENSE) for the full text.
