"""GET /api/history - Historical time-series data."""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Query, Depends
from sqlalchemy import case, func, Integer
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
    "barometer": "inHg",
    "rain_total": "clicks",
    "heat_index": "F",
    "dew_point": "F",
    "wind_chill": "F",
    "feels_like": "F",
    "theta_e": "K",
    "solar_radiation": "W/m²",
    "uv_index": "",
}

# Raw DB values -> display units conversion divisors
SENSOR_DIVISORS: dict[str, float] = {
    "inside_temp": 10,
    "outside_temp": 10,
    "heat_index": 10,
    "dew_point": 10,
    "wind_chill": 10,
    "feels_like": 10,
    "theta_e": 10,
    "uv_index": 10,
    "barometer": 1000,
}

# Frontend uses display-friendly names; map them to DB column names
SENSOR_ALIASES = {
    "temperature_inside": "inside_temp",
    "temperature_outside": "outside_temp",
    "humidity_inside": "inside_humidity",
    "humidity_outside": "outside_humidity",
    "rain_daily": "rain_total",
    "rain_yearly": "rain_yearly",
    "rain_rate": "rain_total",
}

# Physically reasonable bounds for raw DB values.
# Values outside these ranges indicate a disconnected or faulty sensor
# (e.g. Davis 32767/255/65535 sentinel values).
SENSOR_BOUNDS: dict[str, tuple[int, int]] = {
    "inside_temp": (-400, 1500),       # -40 to 150 °F  (raw × 10)
    "outside_temp": (-400, 1500),
    "heat_index": (-400, 1850),        # -40 to 185 °F  (raw × 10)
    "dew_point": (-400, 1500),         # -40 to 150 °F  (raw × 10)
    "wind_chill": (-1000, 1500),       # -100 to 150 °F (raw × 10)
    "feels_like": (-1000, 1850),       # -100 to 185 °F (raw × 10)
    "theta_e": (2000, 4500),           # 200 to 450 K   (raw × 10)
    "inside_humidity": (1, 100),       # 1 to 100 %
    "outside_humidity": (1, 100),
    "wind_speed": (0, 200),            # 0 to 200 mph
    "wind_direction": (0, 360),        # 0 to 360 °
    "barometer": (25000, 35000),       # 25 to 35 inHg  (raw × 1000)
    "rain_total": (0, 99900),          # 0 to 999 in    (raw clicks)
    "rain_rate": (0, 10000),           # 0 to 100 in/hr (raw clicks/hr)
    "rain_yearly": (0, 99900),
    "solar_radiation": (0, 1800),      # 0 to 1800 W/m²
    "uv_index": (0, 160),             # 0 to 16        (raw × 10)
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
    # Resolve frontend display names to DB column names
    sensor = SENSOR_ALIASES.get(sensor, sensor)

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
    divisor = SENSOR_DIVISORS.get(sensor, 1)
    bounds = SENSOR_BOUNDS.get(sensor)

    if resolution == "raw":
        # Use CASE to null-out readings outside physical bounds (chart gaps)
        value_expr = (
            case((column.between(bounds[0], bounds[1]), column), else_=None)
            if bounds else column
        )
        results = (
            db.query(SensorReadingModel.timestamp, value_expr)
            .filter(SensorReadingModel.timestamp >= start_dt)
            .filter(SensorReadingModel.timestamp <= end_dt)
            .filter(column.isnot(None))
            .order_by(SensorReadingModel.timestamp)
            .all()
        )
        data = [
            {
                "timestamp": r[0].isoformat() + "Z",
                "value": round(r[1] / divisor, 2) if r[1] is not None else None,
            }
            for r in results
        ]
    else:
        # For hourly/daily, return averages (bad values excluded)
        data = _aggregate(db, column, start_dt, end_dt, resolution, divisor, bounds)

    return {
        "sensor": sensor,
        "unit": SENSOR_UNITS.get(sensor, ""),
        "start": start_dt.isoformat() + ("" if start_dt.tzinfo else "Z"),
        "end": end_dt.isoformat() + ("" if end_dt.tzinfo else "Z"),
        "resolution": resolution,
        "points": data,
    }


def _aggregate(db, column, start_dt, end_dt, resolution, divisor=1, bounds=None):
    """Aggregate readings by 5-minute, hourly, or daily buckets."""
    if resolution == "5m":
        # Group by epoch seconds rounded to 300s (5 min) boundaries
        bucket = func.cast(
            func.strftime("%s", SensorReadingModel.timestamp), Integer
        ) / 300
        time_label = func.strftime(
            "%Y-%m-%dT%H:%M:00", SensorReadingModel.timestamp
        )
        group_key = bucket
    elif resolution == "hourly":
        group_key = func.strftime("%Y-%m-%dT%H:00:00", SensorReadingModel.timestamp)
        time_label = group_key
    else:  # daily
        group_key = func.strftime("%Y-%m-%dT00:00:00", SensorReadingModel.timestamp)
        time_label = group_key

    query = (
        db.query(time_label, func.avg(column))
        .filter(SensorReadingModel.timestamp >= start_dt)
        .filter(SensorReadingModel.timestamp <= end_dt)
        .filter(column.isnot(None))
    )
    # Exclude out-of-range values from the average
    if bounds:
        query = query.filter(column.between(bounds[0], bounds[1]))

    results = query.group_by(group_key).order_by(group_key).all()

    return [
        {"timestamp": r[0] + "Z", "value": round(r[1] / divisor, 2) if r[1] is not None else None}
        for r in results
    ]
