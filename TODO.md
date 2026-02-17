# Feature Roadmap

## Done
- [x] **Daily High/Low Records** — Query DB for today's min/max temp, peak wind gust, low barometer, max rain rate, etc. Display on dashboard + topbar.

## Planned
- [ ] **Weather Network Upload** — Push data to Weather Underground, CWOP/APRS, or PWSweather on a configurable interval via poller broadcast subscription.
- [ ] **Alerts/Thresholds** — Configurable warnings (freeze, high wind, heavy rain rate) with browser notifications via WebSocket.
- [ ] **Data Export** — CSV download of historical data for a date range as a REST endpoint.
- [ ] **Data Retention** — Background job to downsample old sensor_readings (5s for 7d, 5min for 30d, hourly beyond). Keeps DB performant long-term.
