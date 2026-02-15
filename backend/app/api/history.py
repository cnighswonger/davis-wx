"""GET /api/history - Historical time-series data."""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Query, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models.database import get_db
from ..models.sensor_reading import SensorReadingModel

router = APIRouter()

# Map sensor names to DB columns
SENSOR_COLUMNS = {
    "inside_temp": SensorReadingModel.inside_temp,
    "outside_temp": SensorReadingModel.outside_temp,
    "inside_humidity": SensorReadingModel.inside_humidity,
    "outside_humidity": SensorReadingModel.outside_humidity,
    "wind_speed": SensorReadingModel.wind_speed,
    "wind_direction": SensorReadingModel.wind_direction,
    "barometer": SensorReadingModel.barometer,
    "rain_total": SensorReadingModel.rain_total,
    "heat_index": SensorReadingModel.heat_index,
    "dew_point": SensorReadingModel.dew_point,
    "wind_chill": SensorReadingModel.wind_chill,
    "feels_like": SensorReadingModel.feels_like,
    "theta_e": SensorReadingModel.theta_e,
    "solar_radiation": SensorReadingModel.solar_radiation,
    "uv_index": SensorReadingModel.uv_index,
}

SENSOR_UNITS = {
    "inside_temp": "F",
    "outside_temp": "F",
    "inside_humidity": "%",
    "outside_humidity": "%",
    "wind_speed": "mph",
    "wind_direction": "°",
    "barometer": "thousandths inHg",
    "rain_total": "clicks",
    "heat_index": "F",
    "dew_point": "F",
    "wind_chill": "F",
    "feels_like": "F",
    "theta_e": "tenths K",
    "solar_radiation": "W/m²",
    "uv_index": "tenths UV",
}


@router.get("/history")
def get_history(
    sensor: str = Query(default="outside_temp", description="Sensor name"),
    start: str = Query(default=None, description="Start time ISO format"),
    end: str = Query(default=None, description="End time ISO format"),
    resolution: str = Query(default="raw", description="raw, hourly, or daily"),
    db: Session = Depends(get_db),
):
    """Return time-series data for a sensor."""
    if sensor not in SENSOR_COLUMNS:
        return {"error": f"Unknown sensor: {sensor}", "available": list(SENSOR_COLUMNS.keys())}

    # Default time range: last 24 hours
    now = datetime.now(timezone.utc)
    if end:
        end_dt = datetime.fromisoformat(end)
    else:
        end_dt = now

    if start:
        start_dt = datetime.fromisoformat(start)
    else:
        start_dt = end_dt - timedelta(hours=24)

    column = SENSOR_COLUMNS[sensor]

    if resolution == "raw":
        results = (
            db.query(SensorReadingModel.timestamp, column)
            .filter(SensorReadingModel.timestamp >= start_dt)
            .filter(SensorReadingModel.timestamp <= end_dt)
            .filter(column.isnot(None))
            .order_by(SensorReadingModel.timestamp)
            .all()
        )
        data = [
            {"timestamp": r[0].isoformat(), "value": r[1]}
            for r in results
        ]
    else:
        # For hourly/daily, return averages
        data = _aggregate(db, column, start_dt, end_dt, resolution)

    return {
        "sensor": sensor,
        "unit": SENSOR_UNITS.get(sensor, ""),
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "resolution": resolution,
        "data": data,
    }


def _aggregate(db, column, start_dt, end_dt, resolution):
    """Aggregate readings by hour or day."""
    # Use SQLite strftime for grouping
    if resolution == "hourly":
        group_fmt = "%Y-%m-%dT%H:00:00"
    else:  # daily
        group_fmt = "%Y-%m-%dT00:00:00"

    time_group = func.strftime(group_fmt, SensorReadingModel.timestamp)

    results = (
        db.query(time_group, func.avg(column))
        .filter(SensorReadingModel.timestamp >= start_dt)
        .filter(SensorReadingModel.timestamp <= end_dt)
        .filter(column.isnot(None))
        .group_by(time_group)
        .order_by(time_group)
        .all()
    )

    return [
        {"timestamp": r[0], "value": round(r[1], 1) if r[1] is not None else None}
        for r in results
    ]
