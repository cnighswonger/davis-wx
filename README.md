# Davis Weather Station

A cross-platform application that polls a Davis Instruments weather station via a WeatherLink datalogger, logs all sensor data to SQLite, and presents it through a modern, theme-able browser dashboard with real-time updates.

Supports the full range of classic Davis stations: Weather Wizard III, Weather Wizard II, Weather Monitor II, Perception II, GroWeather, Energy, and Health.

## Features

- **Real-time dashboard** with SVG gauges for temperature, barometric pressure, wind speed/direction, humidity, rain, and solar/UV
- **Historical charts** (Highcharts) with selectable sensor, date range, and resolution
- **Calculated parameters**: heat index, dew point, wind chill, feels-like composite, equivalent potential temperature (theta-e)
- **Forecasting**: Zambretti barometric algorithm (local) blended with NWS API data (optional)
- **Astronomy**: sunrise/sunset arc, twilight times (civil/nautical/astronomical), moon phase with illumination
- **Three themes**: Dark, Light, and Classic Instrumental (brass/cream analog aesthetic)
- **WebSocket push** for live sensor updates without polling
- **METAR output** generation (optional)
- **Cross-platform**: runs on Windows 10+, macOS, and Linux from a single setup script

## Quick Start

Prerequisites: **Python 3.10+** and **Node.js 18+**

```bash
git clone https://github.com/cnighswonger/davis-wx.git
cd davis-wx

python station.py setup
python station.py run
```

Open **http://localhost:8000** in your browser.

If no serial port is connected, the server starts in demo mode — the UI loads and is fully navigable, but sensor readings will show placeholder values.

## Configuration

Setup creates a `.env` file from `.env.example`. Edit it to match your environment:

```bash
# Serial port
# Linux:   /dev/ttyUSB0  or  /dev/ttyS0
# macOS:   /dev/tty.usbserial-XXXX
# Windows: COM3  (check Device Manager -> Ports)
DAVIS_SERIAL_PORT=/dev/ttyUSB0
DAVIS_BAUD_RATE=2400

# Location (required for astronomy and NWS forecasts)
DAVIS_LATITUDE=40.7128
DAVIS_LONGITUDE=-74.0060
DAVIS_ELEVATION_FT=33

# NWS forecast integration
DAVIS_NWS_ENABLED=true

# METAR output
DAVIS_METAR_ENABLED=false
DAVIS_METAR_STATION_ID=KJFK

# UI theme (dark, light, classic)
DAVIS_THEME=dark
```

All settings are also editable from the Settings page in the browser.

## Commands

| Command | Description |
|---------|-------------|
| `python station.py setup` | Create venv, install all dependencies, build frontend |
| `python station.py run` | Start production server on port 8000 |
| `python station.py dev` | Start backend (8000) + frontend HMR dev server (3000) |
| `python station.py test` | Run the backend test suite (50 tests) |
| `python station.py status` | Check what's installed and ready |
| `python station.py clean` | Remove venv, node_modules, and build artifacts |

On Linux/macOS, `make` targets are also available (`make setup`, `make dev`, etc.).

## Architecture

```
Browser  <──WebSocket──>  FastAPI  <──RS-232──>  WeatherLink  <──>  Station
           <──REST API──>  (Python)               (datalogger)
```

### Backend (Python / FastAPI)

```
backend/app/
├── protocol/        # Serial driver: CRC-CCITT, LOOP parser, station detection
├── models/          # SQLAlchemy ORM (sensor_readings, archive, config, forecasts)
├── services/        # Polling loop, calculations, pressure trend, forecasts, astronomy
├── api/             # REST endpoints under /api
├── ws/              # WebSocket handler at /ws/live
├── output/          # METAR generator, APRS stub
├── schemas/         # Pydantic request/response models
├── config.py        # Pydantic Settings (env vars + .env)
└── main.py          # App factory, lifespan, static file serving
```

### Frontend (React / TypeScript / Vite)

```
frontend/src/
├── components/
│   ├── gauges/      # TemperatureGauge, BarometerDial, WindCompass,
│   │                # HumidityGauge, RainGauge, SolarUVGauge
│   ├── charts/      # TrendChart (sparkline), HistoricalChart (area)
│   ├── panels/      # CurrentConditions, StationStatus
│   └── layout/      # AppShell, Header, Sidebar, Footer
├── pages/           # Dashboard, History, Forecast, Astronomy, Settings
├── context/         # WeatherDataContext, ThemeContext
├── themes/          # dark, light, classic (CSS custom properties)
├── hooks/           # useWebSocket, useCurrentConditions, useHistoricalData
├── api/             # HTTP client, WebSocket manager, TypeScript types
└── utils/           # Unit conversions, formatting, constants
```

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/current` | Latest sensor reading + all derived values |
| GET | `/api/history` | Time-series data with aggregation |
| GET | `/api/forecast` | Zambretti + NWS blended forecast |
| GET | `/api/astronomy` | Sun/moon times, twilight, moon phase |
| GET | `/api/station` | Station type, connection status, diagnostics |
| GET | `/api/config` | Current configuration |
| PUT | `/api/config` | Update configuration |
| GET | `/api/metar` | METAR-formatted output string |
| GET | `/api/aprs` | APRS packet (format stub) |
| WS | `/ws/live` | Real-time sensor updates |

## Supported Stations

| Station | LOOP Size | Sensors |
|---------|-----------|---------|
| Weather Wizard III | 15 bytes | Temp (in/out), humidity (in/out), wind, barometer |
| Weather Wizard II | 15 bytes | Same as Wizard III |
| Weather Monitor II | 15 bytes | Same as Wizard III |
| Perception II | 15 bytes | Same as Wizard III |
| GroWeather | 33 bytes | + soil temp, soil moisture, leaf wetness, solar radiation |
| Energy | 27 bytes | + solar radiation, UV index |
| Health | 25 bytes | + UV index |

## Hardware Setup

Connect the Davis WeatherLink datalogger to your computer via a USB-to-serial adapter (or native RS-232 port). The protocol runs at **2400 baud, 8N1** (1200 baud also supported).

The application auto-detects the station model on startup by reading the model nibble from the WeatherLink's memory.

## Deployment

### Ubuntu / Debian (.deb installer)

Download the latest release from [Releases](https://github.com/cnighswonger/davis-wx/releases), extract, and run:

```bash
tar xzf davis-wx_*.tar.gz
./install.sh
```

The installer handles all dependencies, creates systemd services, and places a desktop shortcut. Requires an internet connection during install for Python packages.

### Docker

```bash
docker compose up -d
```

The `docker-compose.yml` passes through `/dev/ttyUSB0` and persists the database via a named volume.

### Manual systemd (Linux)

```bash
sudo cp davis-wx.service /etc/systemd/system/
sudo systemctl enable --now davis-wx
```

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.10+, FastAPI, uvicorn |
| Serial | pyserial (2400 baud, 8N1) |
| Database | SQLAlchemy + SQLite |
| Migrations | Alembic |
| Astronomy | astral |
| NWS client | httpx (async) |
| Frontend | React 19, TypeScript (strict), Vite |
| Charts | Highcharts |
| Real-time | FastAPI WebSocket |

## Reference

The `reference/` directory contains the original Davis Instruments SDK materials (circa 1996-1999) documenting the PC-to-WeatherLink serial protocol: technical reference, command set, CRC tables, memory maps, and sample C/VB source code.

## License

Copyright (C) 2026 Chris Nighswonger

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, version 3. See [LICENSE](LICENSE) for the full text.
