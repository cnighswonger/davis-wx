# Feature Roadmap

## Done
- [x] **Daily High/Low Records** — Query DB for today's min/max temp, peak wind gust, low barometer, max rain rate, etc. Display on dashboard + topbar.
- [x] **Data Export** — CSV download of historical data for a date range via `GET /api/export`. Download button on History page.
- [x] **Alerts/Thresholds** — Configurable per-sensor alerts with cooldown, toast notifications via WebSocket, Settings page UI.

## Planned
- [ ] **Weather Network Upload** — Push data to Weather Underground, CWOP/APRS, or PWSweather on a configurable interval via poller broadcast subscription.
- [ ] **Data Retention** — Background job to downsample old sensor_readings (5s for 7d, 5min for 30d, hourly beyond). Keeps DB performant long-term.
