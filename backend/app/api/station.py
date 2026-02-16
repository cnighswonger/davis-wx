"""GET /api/station - Station type, connection status, diagnostics.
   POST /api/station/sync-time - Sync station clock to computer time.
"""

import logging
from datetime import datetime

from fastapi import APIRouter

from ..protocol.constants import STATION_NAMES, StationModel

logger = logging.getLogger(__name__)
router = APIRouter()

# These will be set by main.py during startup
_poller = None
_driver = None


def set_poller(poller, driver):
    global _poller, _driver
    _poller = poller
    _driver = driver


AUTO_SYNC_THRESHOLD_SECONDS = 5


def _format_station_time(t: dict | None) -> str | None:
    """Format station time dict as a display string."""
    if t is None:
        return None
    time_str = f"{t['hour']:02d}:{t['minute']:02d}:{t['second']:02d}"
    if t.get("year"):
        return f"{time_str} {t['month']:02d}/{t['day']:02d}/{t['year']}"
    return f"{time_str} {t['month']:02d}/{t['day']:02d}"


def _station_time_to_datetime(t: dict) -> datetime:
    """Build a datetime from a station time dict for drift comparison."""
    now = datetime.now()
    year = t.get("year") or now.year
    return datetime(year, t["month"], t["day"], t["hour"], t["minute"], t["second"])


@router.get("/station")
async def get_station():
    """Return station information and diagnostics."""
    if _driver is None:
        return {
            "type_code": -1,
            "type_name": "Not connected",
            "connected": False,
            "link_revision": "unknown",
            "poll_interval": 0,
            "station_time": None,
        }

    model = _driver.station_model
    stats = _poller.stats if _poller else {}

    # Read station clock and auto-sync if drifted
    station_time = None
    if _driver.connected:
        try:
            t = await _driver.async_read_station_time()
            station_time = _format_station_time(t)

            # Auto-sync if drift exceeds threshold
            if t is not None:
                station_dt = _station_time_to_datetime(t)
                drift = abs((datetime.now() - station_dt).total_seconds())
                if drift > AUTO_SYNC_THRESHOLD_SECONDS:
                    logger.info(
                        "Station clock drift %.1fs exceeds %ds threshold, auto-syncing",
                        drift, AUTO_SYNC_THRESHOLD_SECONDS,
                    )
                    now = datetime.now()
                    ok = await _driver.async_write_station_time(now)
                    if ok:
                        station_time = now.strftime("%H:%M:%S %m/%d")
                        logger.info("Auto-sync complete")
                    else:
                        logger.warning("Auto-sync write failed")
        except Exception as e:
            logger.warning("Failed to read station time: %s", e)

    return {
        "type_code": model.value if model else -1,
        "type_name": STATION_NAMES.get(model, "Unknown") if model else "Unknown",
        "connected": _driver.connected,
        "link_revision": "E" if _driver.is_rev_e else "D",
        "poll_interval": _poller.poll_interval if _poller else 0,
        "last_poll": stats.get("last_poll"),
        "uptime_seconds": stats.get("uptime_seconds", 0),
        "crc_errors": stats.get("crc_errors", 0),
        "timeouts": stats.get("timeouts", 0),
        "station_time": station_time,
    }


@router.post("/station/sync-time")
async def sync_station_time():
    """Sync station clock to computer time."""
    if _driver is None or not _driver.connected:
        return {"status": "error", "message": "Station not connected"}

    now = datetime.now()
    try:
        ok = await _driver.async_write_station_time(now)
    except Exception as e:
        logger.error("Station time sync failed: %s", e)
        return {"status": "error", "message": str(e)}

    if ok:
        return {"status": "ok", "synced_to": now.strftime("%H:%M:%S %m/%d/%Y")}
    return {"status": "error", "message": "Write failed (no ACK)"}
