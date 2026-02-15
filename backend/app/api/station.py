"""GET /api/station - Station type, connection status, diagnostics."""

from fastapi import APIRouter

from ..protocol.constants import STATION_NAMES, StationModel

router = APIRouter()

# These will be set by main.py during startup
_poller = None
_driver = None


def set_poller(poller, driver):
    global _poller, _driver
    _poller = poller
    _driver = driver


@router.get("/station")
def get_station():
    """Return station information and diagnostics."""
    if _driver is None:
        return {
            "type_code": -1,
            "type_name": "Not connected",
            "connected": False,
            "link_revision": "unknown",
            "poll_interval": 0,
        }

    model = _driver.station_model
    stats = _poller.stats if _poller else {}

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
    }
