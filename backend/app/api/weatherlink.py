"""WeatherLink hardware configuration API endpoints.

GET  /api/weatherlink/config        - Read current hardware settings
POST /api/weatherlink/config        - Write settings to hardware
POST /api/weatherlink/clear-rain-daily   - Clear daily rain accumulator
POST /api/weatherlink/clear-rain-yearly  - Clear yearly rain accumulator
POST /api/weatherlink/force-archive      - Force immediate archive write
"""

import logging

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from ..protocol.link_driver import CalibrationOffsets

logger = logging.getLogger(__name__)
router = APIRouter()

_driver = None


def set_driver(driver):
    global _driver
    _driver = driver


# --------------- Request/Response models ---------------

class CalibrationConfig(BaseModel):
    inside_temp: int = 0
    outside_temp: int = 0
    barometer: int = 0
    outside_humidity: int = 0
    rain_cal: int = 100


class WeatherLinkConfigResponse(BaseModel):
    archive_period: Optional[int] = None
    sample_period: Optional[int] = None
    calibration: CalibrationConfig


class WeatherLinkConfigUpdate(BaseModel):
    archive_period: Optional[int] = None
    sample_period: Optional[int] = None
    calibration: Optional[CalibrationConfig] = None


# --------------- Endpoints ---------------

@router.get("/weatherlink/config")
async def get_weatherlink_config():
    """Read current hardware settings from the WeatherLink."""
    if _driver is None or not _driver.connected:
        return {"error": "Not connected to station"}

    archive_period = await _driver.async_read_archive_period()
    sample_period = await _driver.async_read_sample_period()
    cal = _driver.calibration

    return WeatherLinkConfigResponse(
        archive_period=archive_period,
        sample_period=sample_period,
        calibration=CalibrationConfig(
            inside_temp=cal.inside_temp,
            outside_temp=cal.outside_temp,
            barometer=cal.barometer,
            outside_humidity=cal.outside_hum,
            rain_cal=cal.rain_cal,
        ),
    )


@router.post("/weatherlink/config")
async def update_weatherlink_config(config: WeatherLinkConfigUpdate):
    """Write settings to the WeatherLink hardware."""
    if _driver is None or not _driver.connected:
        return {"error": "Not connected to station"}

    results = {}

    if config.archive_period is not None:
        try:
            ok = await _driver.async_set_archive_period(config.archive_period)
            results["archive_period"] = "ok" if ok else "failed"
        except ValueError as e:
            results["archive_period"] = str(e)

    if config.sample_period is not None:
        try:
            ok = await _driver.async_set_sample_period(config.sample_period)
            results["sample_period"] = "ok" if ok else "failed"
        except ValueError as e:
            results["sample_period"] = str(e)

    if config.calibration is not None:
        offsets = CalibrationOffsets(
            inside_temp=config.calibration.inside_temp,
            outside_temp=config.calibration.outside_temp,
            barometer=config.calibration.barometer,
            outside_hum=config.calibration.outside_humidity,
            rain_cal=config.calibration.rain_cal,
        )
        ok = await _driver.async_write_calibration(offsets)
        results["calibration"] = "ok" if ok else "failed"

    # Re-read current state to return
    archive_period = await _driver.async_read_archive_period()
    sample_period = await _driver.async_read_sample_period()
    cal = _driver.calibration

    return {
        "results": results,
        "config": WeatherLinkConfigResponse(
            archive_period=archive_period,
            sample_period=sample_period,
            calibration=CalibrationConfig(
                inside_temp=cal.inside_temp,
                outside_temp=cal.outside_temp,
                barometer=cal.barometer,
                outside_humidity=cal.outside_hum,
                rain_cal=cal.rain_cal,
            ),
        ),
    }


@router.post("/weatherlink/clear-rain-daily")
async def clear_rain_daily():
    """Clear the daily rain accumulator."""
    if _driver is None or not _driver.connected:
        return {"error": "Not connected to station"}

    ok = await _driver.async_clear_rain_daily()
    return {"success": ok}


@router.post("/weatherlink/clear-rain-yearly")
async def clear_rain_yearly():
    """Clear the yearly rain accumulator."""
    if _driver is None or not _driver.connected:
        return {"error": "Not connected to station"}

    ok = await _driver.async_clear_rain_yearly()
    return {"success": ok}


@router.post("/weatherlink/force-archive")
async def force_archive():
    """Force the WeatherLink to write an archive record now."""
    if _driver is None or not _driver.connected:
        return {"error": "Not connected to station"}

    ok = await _driver.async_force_archive()
    return {"success": ok}
