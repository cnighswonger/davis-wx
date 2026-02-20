"""GET /api/history - Historical time-series data."""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Query, Depends
from sqlalchemy import and_, case, func, Integer
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

# Maximum reasonable change between consecutive samples (~10 s apart).
# A reading that differs from BOTH its neighbors by more than this
# threshold is treated as a single-sample spike and nulled out.
# Sensors omitted here (wind, rain, solar) can legitimately spike.
SENSOR_SPIKE_THRESHOLDS: dict[str, int] = {
    "inside_temp": 50,       # 5 °F   (raw × 10)
    "outside_temp": 50,      # 5 °F
    "heat_index": 50,        # 5 °F
    "dew_point": 50,         # 5 °F
    "wind_chill": 50,        # 5 °F
    "feels_like": 50,        # 5 °F
    "theta_e": 50,           # 5 K    (raw × 10)
    "inside_humidity": 15,   # 15 %
    "outside_humidity": 15,  # 15 %
    "barometer": 100,        # 0.1 inHg (raw × 1000)
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
    spike_threshold = SENSOR_SPIKE_THRESHOLDS.get(sensor)

    if resolution == "raw":
        # Build CASE conditions: bounds check, then spike detection
        conditions: list[tuple] = []
        if bounds:
            conditions.append((~column.between(bounds[0], bounds[1]), None))
        if spike_threshold:
            lag_col = func.lag(column, 1).over(order_by=SensorReadingModel.timestamp)
            lead_col = func.lead(column, 1).over(order_by=SensorReadingModel.timestamp)
            conditions.append((
                and_(
                    func.abs(column - lag_col) > spike_threshold,
                    func.abs(column - lead_col) > spike_threshold,
                ),
                None,
            ))
        value_expr = case(*conditions, else_=column) if conditions else column

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
        data = _aggregate(db, column, start_dt, end_dt, resolution, divisor,
                          bounds, spike_threshold)

    # Compute summary stats from the returned points
    if resolution == "raw":
        vals = [pt["value"] for pt in data if pt["value"] is not None]
    else:
        # Use per-bucket min/max for true extremes
        vals_min = [pt["min"] for pt in data if pt["min"] is not None]
        vals_max = [pt["max"] for pt in data if pt["max"] is not None]
        vals_avg = [pt["value"] for pt in data if pt["value"] is not None]
        vals = vals_avg  # for avg/count

    if resolution == "raw":
        summary = {
            "min": min(vals) if vals else None,
            "max": max(vals) if vals else None,
            "avg": round(sum(vals) / len(vals), 2) if vals else None,
            "count": len(vals),
        }
    else:
        summary = {
            "min": min(vals_min) if vals_min else None,
            "max": max(vals_max) if vals_max else None,
            "avg": round(sum(vals_avg) / len(vals_avg), 2) if vals_avg else None,
            "count": len(data),
        }

    return {
        "sensor": sensor,
        "unit": SENSOR_UNITS.get(sensor, ""),
        "start": start_dt.isoformat() + ("" if start_dt.tzinfo else "Z"),
        "end": end_dt.isoformat() + ("" if end_dt.tzinfo else "Z"),
        "resolution": resolution,
        "summary": summary,
        "points": data,
    }


def _aggregate(db, column, start_dt, end_dt, resolution, divisor=1,
               bounds=None, spike_threshold=None):
    """Aggregate readings by 5-minute, hourly, or daily buckets.

    SQLite forbids window functions (LAG/LEAD) inside GROUP BY queries,
    so when spike detection is needed we use a subquery: first compute
    clean values with window functions, then aggregate the result.
    """
    # --- Build clean-value expression (bounds + spike detection) ---
    conditions: list[tuple] = []
    if bounds:
        conditions.append((~column.between(bounds[0], bounds[1]), None))
    if spike_threshold:
        lag_col = func.lag(column, 1).over(order_by=SensorReadingModel.timestamp)
        lead_col = func.lead(column, 1).over(order_by=SensorReadingModel.timestamp)
        conditions.append((
            and_(
                func.abs(column - lag_col) > spike_threshold,
                func.abs(column - lead_col) > spike_threshold,
            ),
            None,
        ))

    need_subquery = spike_threshold is not None

    if need_subquery:
        # Subquery: compute clean values with window functions (no GROUP BY)
        clean_col = case(*conditions, else_=column) if conditions else column
        subq = (
            db.query(
                SensorReadingModel.timestamp.label("ts"),
                clean_col.label("val"),
            )
            .filter(SensorReadingModel.timestamp >= start_dt)
            .filter(SensorReadingModel.timestamp <= end_dt)
            .filter(column.isnot(None))
        ).subquery()

        ts_col = subq.c.ts
        val_col = subq.c.val
    else:
        # No window functions needed — query the table directly
        ts_col = SensorReadingModel.timestamp
        val_col = case(*conditions, else_=column) if conditions else column

    # --- Time bucket grouping ---
    if resolution == "5m":
        bucket = func.cast(func.strftime("%s", ts_col), Integer) / 300
        time_label = func.strftime("%Y-%m-%dT%H:%M:00", ts_col)
        group_key = bucket
    elif resolution == "hourly":
        group_key = func.strftime("%Y-%m-%dT%H:00:00", ts_col)
        time_label = group_key
    else:  # daily
        group_key = func.strftime("%Y-%m-%dT00:00:00", ts_col)
        time_label = group_key

    query = db.query(time_label, func.avg(val_col), func.min(val_col), func.max(val_col))

    if not need_subquery:
        # Apply filters directly (subquery already has them baked in)
        query = (
            query
            .filter(SensorReadingModel.timestamp >= start_dt)
            .filter(SensorReadingModel.timestamp <= end_dt)
            .filter(column.isnot(None))
        )

    results = query.group_by(group_key).order_by(group_key).all()

    return [
        {
            "timestamp": r[0] + "Z",
            "value": round(r[1] / divisor, 2) if r[1] is not None else None,
            "min": round(r[2] / divisor, 2) if r[2] is not None else None,
            "max": round(r[3] / divisor, 2) if r[3] is not None else None,
        }
        for r in results
    ]
