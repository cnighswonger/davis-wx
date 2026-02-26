"""Data collector for AI nowcast — gathers station observations,
model guidance (Open-Meteo HRRR/GFS), NWS forecast, and local knowledge
into a unified snapshot for the Claude analyst.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from ..models.sensor_reading import SensorReadingModel
from ..models.nowcast import NowcastKnowledge

logger = logging.getLogger(__name__)

# Open-Meteo forecast API (free, no key required).
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_TIMEOUT = 15.0

# Variables to request from HRRR model.
HRRR_HOURLY_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "precipitation",
    "rain",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "cloud_cover",
    "pressure_msl",
]


@dataclass
class StationSnapshot:
    """Current + trend observations from the local station."""
    latest: dict[str, Any]
    trend_3h: list[dict[str, Any]]
    has_data: bool = True


@dataclass
class ModelGuidance:
    """HRRR/GFS point forecast from Open-Meteo."""
    hourly: dict[str, Any]
    model: str = "best_match"
    fetched_at: float = 0.0


@dataclass
class CollectedData:
    """Complete data snapshot for the analyst."""
    station: StationSnapshot
    model_guidance: Optional[ModelGuidance] = None
    nws_summary: Optional[str] = None
    knowledge_entries: list[str] = field(default_factory=list)
    collected_at: str = ""
    location: dict[str, float] = field(default_factory=dict)


def _reading_to_dict(r: SensorReadingModel) -> dict[str, Any]:
    """Convert a SensorReadingModel to a human-readable dict with proper units."""
    return {
        "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        "outside_temp_f": r.outside_temp / 10.0 if r.outside_temp is not None else None,
        "inside_temp_f": r.inside_temp / 10.0 if r.inside_temp is not None else None,
        "outside_humidity_pct": r.outside_humidity,
        "inside_humidity_pct": r.inside_humidity,
        "wind_speed_mph": r.wind_speed,
        "wind_direction_deg": r.wind_direction,
        "barometer_inHg": r.barometer / 1000.0 if r.barometer is not None else None,
        "rain_daily_in": r.rain_total / 100.0 if r.rain_total is not None else None,
        "rain_rate_in_hr": r.rain_rate / 100.0 if r.rain_rate is not None else None,
        "solar_radiation_wm2": r.solar_radiation,
        "uv_index": r.uv_index / 10.0 if r.uv_index is not None else None,
        "dew_point_f": r.dew_point / 10.0 if r.dew_point is not None else None,
        "heat_index_f": r.heat_index / 10.0 if r.heat_index is not None else None,
        "wind_chill_f": r.wind_chill / 10.0 if r.wind_chill is not None else None,
        "pressure_trend": r.pressure_trend,
    }


def gather_station_data(db: Session) -> StationSnapshot:
    """Query latest reading + 3-hour trend from sensor_readings table."""
    latest = (
        db.query(SensorReadingModel)
        .order_by(SensorReadingModel.timestamp.desc())
        .first()
    )
    if latest is None:
        return StationSnapshot(latest={}, trend_3h=[], has_data=False)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=3)
    trend_rows = (
        db.query(SensorReadingModel)
        .filter(SensorReadingModel.timestamp >= cutoff)
        .order_by(SensorReadingModel.timestamp.asc())
        .all()
    )

    # Subsample trend to ~12 points (one per ~15 min) to keep prompt compact.
    step = max(1, len(trend_rows) // 12)
    trend_sampled = [_reading_to_dict(r) for r in trend_rows[::step]]

    return StationSnapshot(
        latest=_reading_to_dict(latest),
        trend_3h=trend_sampled,
    )


async def fetch_model_guidance(
    lat: float, lon: float, horizon_hours: int = 12
) -> Optional[ModelGuidance]:
    """Fetch HRRR/GFS point forecast from Open-Meteo."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(HRRR_HOURLY_VARS),
        "forecast_hours": horizon_hours,
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
    }
    try:
        async with httpx.AsyncClient(timeout=OPEN_METEO_TIMEOUT) as client:
            resp = await client.get(OPEN_METEO_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            return ModelGuidance(
                hourly=data.get("hourly", {}),
                model=data.get("current_weather", {}).get("weathercode", "best_match"),
                fetched_at=time.time(),
            )
    except Exception as exc:
        logger.warning("Open-Meteo HRRR fetch failed: %s", exc)
        return None


def gather_nws_summary(nws_forecast) -> Optional[str]:
    """Extract a concise text summary from an NWSForecast object."""
    if nws_forecast is None or not nws_forecast.periods:
        return None
    # Take first 3 periods and build a compact summary.
    parts = []
    for p in nws_forecast.periods[:3]:
        parts.append(
            f"{p.name}: {p.short_forecast or p.text[:100]}"
            f" (Temp {p.temperature}F, Wind {p.wind}"
            f"{f', Precip {p.precipitation_pct}%' if p.precipitation_pct is not None else ''})"
        )
    return "\n".join(parts)


def gather_knowledge(db: Session) -> list[str]:
    """Load accepted knowledge base entries."""
    entries = (
        db.query(NowcastKnowledge)
        .filter(NowcastKnowledge.status == "accepted")
        .order_by(NowcastKnowledge.created_at.desc())
        .limit(20)
        .all()
    )
    return [f"[{e.category}] {e.content}" for e in entries]


async def collect_all(
    db: Session,
    lat: float,
    lon: float,
    horizon_hours: int = 12,
    nws_forecast=None,
) -> CollectedData:
    """Gather all data sources into a single snapshot for the analyst."""
    station = gather_station_data(db)
    model = await fetch_model_guidance(lat, lon, horizon_hours)
    nws_summary = gather_nws_summary(nws_forecast)
    knowledge = gather_knowledge(db)

    return CollectedData(
        station=station,
        model_guidance=model,
        nws_summary=nws_summary,
        knowledge_entries=knowledge,
        collected_at=datetime.now(timezone.utc).isoformat(),
        location={"latitude": lat, "longitude": lon},
    )
