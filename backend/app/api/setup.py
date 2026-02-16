"""Setup wizard API endpoints.

GET  /api/setup/status       - Check if initial setup is complete
GET  /api/setup/serial-ports - List available serial ports
POST /api/setup/probe        - Test a specific port+baud for a WeatherLink station
POST /api/setup/auto-detect  - Scan all ports for a WeatherLink station
POST /api/setup/complete     - Save config and trigger reconnect
POST /api/setup/reconnect    - Reconnect with current DB config
"""

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..models.database import get_db
from ..models.station_config import StationConfigModel
from ..protocol.serial_port import list_serial_ports
from ..protocol.link_driver import LinkDriver
from ..protocol.constants import STATION_NAMES, StationModel
from ..services.poller import Poller
from .config import get_effective_config

logger = logging.getLogger(__name__)
router = APIRouter()

# Populated by main.py via set_app_refs()
_app_refs: dict = {}


def set_app_refs(refs: dict):
    """Called by main.py to share mutable references to driver/poller/task."""
    _app_refs.update(refs)


# --------------- Request/Response models ---------------

class ProbeRequest(BaseModel):
    port: str
    baud_rate: int


class ProbeResult(BaseModel):
    success: bool
    station_type: str | None = None
    station_code: int | None = None
    error: str | None = None


class AutoDetectResult(BaseModel):
    found: bool
    port: str | None = None
    baud_rate: int | None = None
    station_type: str | None = None
    station_code: int | None = None
    attempts: list[dict] = []


class SetupConfig(BaseModel):
    serial_port: str
    baud_rate: int
    latitude: float
    longitude: float
    elevation: float
    temp_unit: str = "F"
    pressure_unit: str = "inHg"
    wind_unit: str = "mph"
    rain_unit: str = "in"
    metar_enabled: bool = False
    metar_station: str = "XXXX"
    nws_enabled: bool = False


# --------------- Endpoints ---------------

@router.get("/setup/status")
def get_setup_status(db: Session = Depends(get_db)):
    """Check if initial setup has been completed."""
    row = db.query(StationConfigModel).filter_by(key="setup_complete").first()
    return {"setup_complete": row is not None and row.value == "true"}


@router.get("/setup/serial-ports")
def get_serial_ports():
    """List available serial ports on the host machine."""
    return {"ports": list_serial_ports()}


@router.post("/setup/probe")
async def probe_serial_port(req: ProbeRequest):
    """Test a specific port+baud for a WeatherLink station."""
    if req.baud_rate not in (1200, 2400):
        return ProbeResult(success=False, error="Baud rate must be 1200 or 2400")

    # If the main driver already has this port open, return its info
    driver = _app_refs.get("driver")
    if driver is not None and driver.connected and driver.serial.port == req.port:
        return ProbeResult(
            success=True,
            station_type=STATION_NAMES.get(driver.station_model, "Unknown"),
            station_code=driver.station_model.value if driver.station_model else None,
        )

    # Create a temporary driver to probe
    try:
        tmp = LinkDriver(port=req.port, baud_rate=req.baud_rate, timeout=3.0)
        tmp.open()
        try:
            station = await tmp.async_detect_station_type()
            return ProbeResult(
                success=True,
                station_type=STATION_NAMES.get(station, "Unknown"),
                station_code=station.value,
            )
        finally:
            tmp.close()
    except Exception as e:
        return ProbeResult(success=False, error=str(e))


@router.post("/setup/auto-detect")
async def auto_detect_station():
    """Scan all available ports with 2400 and 1200 baud for a WeatherLink station."""
    ports = list_serial_ports()
    attempts: list[dict] = []

    # Check if main driver is already connected
    driver = _app_refs.get("driver")
    if driver is not None and driver.connected and driver.station_model is not None:
        return AutoDetectResult(
            found=True,
            port=driver.serial.port,
            baud_rate=driver.serial.baud_rate,
            station_type=STATION_NAMES.get(driver.station_model, "Unknown"),
            station_code=driver.station_model.value,
            attempts=[],
        )

    for port in ports:
        for baud in (2400, 1200):
            try:
                tmp = LinkDriver(port=port, baud_rate=baud, timeout=3.0)
                tmp.open()
                try:
                    station = await tmp.async_detect_station_type()
                    attempts.append({"port": port, "baud": baud, "result": "found"})
                    return AutoDetectResult(
                        found=True,
                        port=port,
                        baud_rate=baud,
                        station_type=STATION_NAMES.get(station, "Unknown"),
                        station_code=station.value,
                        attempts=attempts,
                    )
                finally:
                    tmp.close()
            except Exception as e:
                attempts.append({"port": port, "baud": baud, "error": str(e)})

    return AutoDetectResult(found=False, attempts=attempts)


@router.post("/setup/complete")
async def complete_setup(config: SetupConfig, db: Session = Depends(get_db)):
    """Save all setup config and trigger reconnect."""
    # Save config to DB
    config_dict = config.model_dump()
    for key, value in config_dict.items():
        existing = db.query(StationConfigModel).filter_by(key=key).first()
        if existing:
            existing.value = str(value)
            existing.updated_at = datetime.now(timezone.utc)
        else:
            db.add(StationConfigModel(
                key=key, value=str(value),
                updated_at=datetime.now(timezone.utc),
            ))

    # Mark setup complete
    existing = db.query(StationConfigModel).filter_by(key="setup_complete").first()
    if existing:
        existing.value = "true"
        existing.updated_at = datetime.now(timezone.utc)
    else:
        db.add(StationConfigModel(
            key="setup_complete", value="true",
            updated_at=datetime.now(timezone.utc),
        ))

    db.commit()
    logger.info("Setup complete — config saved to database")

    # Reconnect with new settings
    result = await _reconnect(config.serial_port, config.baud_rate)
    return {"status": "ok", "reconnect": result}


@router.post("/setup/reconnect")
async def reconnect_endpoint(db: Session = Depends(get_db)):
    """Reconnect using current DB config."""
    cfg = get_effective_config(db)
    result = await _reconnect(str(cfg["serial_port"]), int(cfg["baud_rate"]))
    return result


# --------------- Internal reconnect logic ---------------

async def _reconnect(port: str, baud_rate: int) -> dict:
    """Teardown existing driver/poller, reinitialize with new settings."""
    # Import these here to set the module globals
    from . import station as station_api
    from ..ws.handler import set_driver as ws_set_driver

    # 1. Stop poller
    poller = _app_refs.get("poller")
    poller_task = _app_refs.get("poller_task")
    if poller:
        poller.stop()
    if poller_task:
        poller_task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(poller_task), timeout=6.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass

    # 2. Close existing driver
    driver = _app_refs.get("driver")
    if driver:
        try:
            driver.close()
        except Exception:
            pass

    # 3. Create new driver
    try:
        new_driver = LinkDriver(port=port, baud_rate=baud_rate, timeout=settings.serial_timeout)
        new_driver.open()
        logger.info("Reconnected to %s at %d baud", port, baud_rate)

        station_type = await new_driver.async_detect_station_type()
        logger.info("Station detected: %s", station_type.name)
        await new_driver.async_read_calibration()

        new_poller = Poller(new_driver, poll_interval=settings.poll_interval_sec)
        new_task = asyncio.create_task(new_poller.run())
        logger.info("Poller restarted (%ds interval)", settings.poll_interval_sec)

        # Update global refs
        _app_refs["driver"] = new_driver
        _app_refs["poller"] = new_poller
        _app_refs["poller_task"] = new_task

        station_api.set_poller(new_poller, new_driver)
        ws_set_driver(new_driver)

        return {
            "success": True,
            "station_type": STATION_NAMES.get(station_type, "Unknown"),
        }
    except Exception as e:
        logger.error("Reconnect failed: %s", e)
        _app_refs["driver"] = None
        _app_refs["poller"] = None
        _app_refs["poller_task"] = None
        station_api.set_poller(None, None)
        ws_set_driver(None)
        return {"success": False, "error": str(e)}
