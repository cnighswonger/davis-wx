"""GET /api/forecast - Zambretti barometric forecast from recent pressure data."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..models.database import get_db
from ..models.sensor_reading import SensorReadingModel
from ..services.forecast_local import zambretti_forecast

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/forecast")
def get_forecast(db: Session = Depends(get_db)):
    """Return Zambretti local forecast from recent barometric data."""
    now = datetime.now(timezone.utc)

    # Get current pressure and wind direction from latest reading
    latest = (
        db.query(SensorReadingModel)
        .filter(SensorReadingModel.barometer.isnot(None))
        .order_by(SensorReadingModel.timestamp.desc())
        .first()
    )

    if latest is None or latest.barometer is None:
        return {"local": None, "nws": None}

    # Get pressure from ~3 hours ago for trend
    cutoff_3h = datetime.fromtimestamp(
        now.timestamp() - 3 * 3600, tz=timezone.utc
    )
    oldest = (
        db.query(SensorReadingModel)
        .filter(SensorReadingModel.barometer.isnot(None))
        .filter(SensorReadingModel.timestamp >= cutoff_3h)
        .order_by(SensorReadingModel.timestamp)
        .first()
    )

    if oldest is not None and oldest.barometer is not None:
        pressure_change = latest.barometer - oldest.barometer
    else:
        pressure_change = 0

    result = zambretti_forecast(
        pressure_thousandths=latest.barometer,
        pressure_change_3h=pressure_change,
        wind_dir_deg=latest.wind_direction,
        month=now.month,
    )

    return {
        "local": {
            "source": "zambretti",
            "text": result.forecast_text,
            "confidence": round(result.confidence * 100),
            "updated": now.isoformat(),
        },
        "nws": None,
    }
