"""GET /api/current - Latest sensor reading with derived values."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..models.database import get_db
from ..models.sensor_reading import SensorReadingModel
from ..protocol.constants import STATION_NAMES, StationModel

router = APIRouter()

CARDINAL_DIRECTIONS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def _cardinal(degrees: int | None) -> str | None:
    if degrees is None:
        return None
    idx = round(degrees / 22.5) % 16
    return CARDINAL_DIRECTIONS[idx]


def _temp_f(tenths: int | None) -> float | None:
    return tenths / 10.0 if tenths is not None else None


def _bar_inhg(thousandths: int | None) -> float | None:
    return thousandths / 1000.0 if thousandths is not None else None


@router.get("/current")
def get_current(db: Session = Depends(get_db)):
    """Return the most recent sensor reading plus all derived values."""
    reading = (
        db.query(SensorReadingModel)
        .order_by(SensorReadingModel.timestamp.desc())
        .first()
    )

    if reading is None:
        return {"error": "No data available", "timestamp": datetime.now(timezone.utc).isoformat()}

    try:
        station_name = STATION_NAMES.get(StationModel(reading.station_type), "Unknown")
    except ValueError:
        station_name = "Unknown"

    return {
        "timestamp": reading.timestamp.isoformat() if reading.timestamp else None,
        "station_type": station_name,
        "temperature": {
            "inside": {"value": _temp_f(reading.inside_temp), "unit": "F"},
            "outside": {"value": _temp_f(reading.outside_temp), "unit": "F"},
        },
        "humidity": {
            "inside": {"value": reading.inside_humidity, "unit": "%"},
            "outside": {"value": reading.outside_humidity, "unit": "%"},
        },
        "wind": {
            "speed": {"value": reading.wind_speed, "unit": "mph"},
            "direction": {"value": reading.wind_direction, "unit": "°"},
            "cardinal": _cardinal(reading.wind_direction),
        },
        "barometer": {
            "value": _bar_inhg(reading.barometer),
            "unit": "inHg",
            "trend": reading.pressure_trend,
        },
        "rain": {
            "daily": (
                {"value": round(reading.rain_total * 0.01, 2), "unit": "in"}
                if reading.rain_total is not None else None
            ),
            "yearly": (
                {"value": round(reading.rain_yearly * 0.01, 2), "unit": "in"}
                if reading.rain_yearly is not None else None
            ),
            "rate": (
                {"value": round(reading.rain_rate / 10.0, 2), "unit": "in/hr"}
                if reading.rain_rate is not None else None
            ),
        },
        "derived": {
            "heat_index": {"value": _temp_f(reading.heat_index), "unit": "F"},
            "dew_point": {"value": _temp_f(reading.dew_point), "unit": "F"},
            "wind_chill": {"value": _temp_f(reading.wind_chill), "unit": "F"},
            "feels_like": {"value": _temp_f(reading.feels_like), "unit": "F"},
            "theta_e": {"value": reading.theta_e / 10.0 if reading.theta_e is not None else None, "unit": "K"},
        },
        "solar_radiation": (
            {"value": reading.solar_radiation, "unit": "W/m²"}
            if reading.solar_radiation is not None else None
        ),
        "uv_index": (
            {"value": reading.uv_index / 10.0 if reading.uv_index is not None else None, "unit": ""}
            if reading.uv_index is not None else None
        ),
    }
