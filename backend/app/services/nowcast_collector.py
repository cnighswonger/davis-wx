"""Data collector for AI nowcast — gathers station observations,
model guidance (Open-Meteo HRRR/GFS), NWS forecast, radar imagery,
and local knowledge into a unified snapshot for the Claude analyst.
"""

import base64
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session

from ..models.sensor_reading import SensorReadingModel
from ..models.nowcast import NowcastKnowledge

logger = logging.getLogger(__name__)


def _local_now_iso(station_timezone: str) -> str:
    """Return current time as ISO string in station local tz, or UTC if unavailable."""
    now_utc = datetime.now(timezone.utc)
    if station_timezone:
        try:
            return now_utc.astimezone(ZoneInfo(station_timezone)).isoformat()
        except (KeyError, Exception):
            pass
    return now_utc.isoformat()


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


# IEM RadMap API for NEXRAD radar composites (free, no key).
IEM_RADMAP_URL = "https://mesonet.agron.iastate.edu/GIS/radmap.php"
IEM_RADMAP_TIMEOUT = 20.0
RADAR_IMAGE_WIDTH = 480
RADAR_IMAGE_HEIGHT = 480
RADAR_BBOX_RADIUS = 1.5  # degrees (~100 miles at mid-latitudes)
RADAR_CACHE_TTL = 3600  # 1 hour — keep image available between nowcast cycles

# Product configuration registry — maps product_id to fetch parameters.
# Add entries here for future products (velocity, dual-pol, etc.).
RADAR_PRODUCTS: dict[str, dict[str, Any]] = {
    "nexrad_composite": {
        "label": "NEXRAD Composite Reflectivity",
        "layers": ["nexrad"],
    },
    "nexrad_velocity": {
        "label": "Storm Relative Velocity (nearest NEXRAD)",
        "layers": ["ridge"],
        "requires_site": True,
        "extra_params": {"ridge_product": "N0S"},
    },
}


@dataclass
class RadarImage:
    """A single radar imagery product fetched for the analyst."""
    product_id: str
    label: str
    png_base64: str
    width: int
    height: int
    bbox: tuple[float, float, float, float]  # lon_min, lat_min, lon_max, lat_max
    fetched_at: float
    source_url: str


@dataclass
class _RadarCacheEntry:
    image: RadarImage
    expires_at: float


_radar_cache: dict[str, _RadarCacheEntry] = {}


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
    radar_images: list[RadarImage] = field(default_factory=list)
    nearby_stations: Any = None  # Optional[NearbyStationsResult] — avoid circular import
    nws_alerts: list[dict[str, Any]] = field(default_factory=list)
    spray_schedules: list[dict[str, Any]] = field(default_factory=list)
    spray_outcomes: list[dict[str, Any]] = field(default_factory=list)
    collected_at: str = ""
    location: dict[str, float] = field(default_factory=dict)
    station_timezone: str = ""


def _reading_to_dict(
    r: SensorReadingModel, tz: ZoneInfo | None = None,
) -> dict[str, Any]:
    """Convert a SensorReadingModel to a human-readable dict with proper units.

    If *tz* is provided, timestamps are converted from UTC to that timezone
    so Claude sees local times matching the station clock.
    """
    ts = None
    if r.timestamp:
        utc_dt = r.timestamp.replace(tzinfo=timezone.utc) if r.timestamp.tzinfo is None else r.timestamp
        if tz is not None:
            ts = utc_dt.astimezone(tz).isoformat()
        else:
            ts = utc_dt.isoformat()
    return {
        "timestamp": ts,
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


def gather_station_data(
    db: Session, station_timezone: str = "",
) -> StationSnapshot:
    """Query latest reading + 3-hour trend from sensor_readings table."""
    latest = (
        db.query(SensorReadingModel)
        .order_by(SensorReadingModel.timestamp.desc())
        .first()
    )
    if latest is None:
        return StationSnapshot(latest={}, trend_3h=[], has_data=False)

    # Resolve timezone for timestamp conversion (UTC → local).
    tz: ZoneInfo | None = None
    if station_timezone:
        try:
            tz = ZoneInfo(station_timezone)
        except (KeyError, Exception):
            logger.warning("Invalid station_timezone %r, timestamps stay UTC", station_timezone)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=3)
    trend_rows = (
        db.query(SensorReadingModel)
        .filter(SensorReadingModel.timestamp >= cutoff)
        .order_by(SensorReadingModel.timestamp.asc())
        .all()
    )

    # Subsample trend to ~12 points (one per ~15 min) to keep prompt compact.
    step = max(1, len(trend_rows) // 12)
    trend_sampled = [_reading_to_dict(r, tz) for r in trend_rows[::step]]

    return StationSnapshot(
        latest=_reading_to_dict(latest, tz),
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


def _compute_bbox(
    lat: float, lon: float, radius_deg: float = RADAR_BBOX_RADIUS,
) -> tuple[float, float, float, float]:
    """Compute bounding box centered on station. Returns (lon_min, lat_min, lon_max, lat_max)."""
    return (
        round(lon - radius_deg, 4),
        round(lat - radius_deg, 4),
        round(lon + radius_deg, 4),
        round(lat + radius_deg, 4),
    )


async def fetch_radar_image(
    lat: float,
    lon: float,
    product_id: str = "nexrad_composite",
    layers: list[str] | None = None,
    extra_params: dict[str, str] | None = None,
) -> Optional[RadarImage]:
    """Fetch a radar image from the IEM RadMap API.

    Returns RadarImage on success, None on failure (logged, never raises).
    """
    cached = _radar_cache.get(product_id)
    if cached is not None and time.time() < cached.expires_at:
        logger.debug("Radar cache hit for %s", product_id)
        return cached.image

    if layers is None:
        layers = ["nexrad"]

    bbox = _compute_bbox(lat, lon)
    label = RADAR_PRODUCTS.get(product_id, {}).get("label", product_id)

    param_tuples = [
        ("bbox", f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"),
        ("width", str(RADAR_IMAGE_WIDTH)),
        ("height", str(RADAR_IMAGE_HEIGHT)),
    ]
    for layer in layers:
        param_tuples.append(("layers[]", layer))
    if extra_params:
        for k, v in extra_params.items():
            param_tuples.append((k, v))

    try:
        async with httpx.AsyncClient(timeout=IEM_RADMAP_TIMEOUT) as client:
            resp = await client.get(IEM_RADMAP_URL, params=param_tuples)
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")
            if "image" not in content_type:
                logger.warning("Radar %s: non-image content-type: %s", product_id, content_type)
                return None

            png_b64 = base64.b64encode(resp.content).decode("ascii")
            image = RadarImage(
                product_id=product_id,
                label=label,
                png_base64=png_b64,
                width=RADAR_IMAGE_WIDTH,
                height=RADAR_IMAGE_HEIGHT,
                bbox=bbox,
                fetched_at=time.time(),
                source_url=str(resp.url),
            )
            _radar_cache[product_id] = _RadarCacheEntry(
                image=image, expires_at=time.time() + RADAR_CACHE_TTL,
            )
            logger.info("Radar image fetched: %s (%d bytes)", product_id, len(resp.content))
            return image

    except Exception as exc:
        logger.warning("Radar fetch failed for %s: %s", product_id, exc)
        return None


async def fetch_radar_images(
    lat: float, lon: float, radar_station: str = "",
) -> list[RadarImage]:
    """Fetch all configured radar products. Returns only successful fetches."""
    images = []
    for pid, cfg in RADAR_PRODUCTS.items():
        # Products requiring a specific NEXRAD site (e.g. velocity)
        # are skipped when no radar station is available.
        if cfg.get("requires_site") and not radar_station:
            logger.debug("Skipping %s — no radar station resolved", pid)
            continue

        extra = dict(cfg.get("extra_params") or {})
        if cfg.get("requires_site") and radar_station:
            extra["ridge_radar"] = radar_station

        img = await fetch_radar_image(
            lat=lat, lon=lon, product_id=pid,
            layers=cfg.get("layers"),
            extra_params=extra or None,
        )
        if img is not None:
            images.append(img)
    return images


def get_cached_radar(product_id: str = "nexrad_composite") -> Optional[RadarImage]:
    """Return a cached radar image if available (for the API endpoint)."""
    cached = _radar_cache.get(product_id)
    if cached is not None and time.time() < cached.expires_at:
        return cached.image
    return None


def gather_spray_schedules(db: Session) -> list[dict[str, Any]]:
    """Load upcoming spray schedules with product constraints for AI analysis."""
    from ..models.spray import SpraySchedule, SprayProduct

    schedules = (
        db.query(SpraySchedule)
        .filter(SpraySchedule.status.in_(["pending", "go", "no_go"]))
        .order_by(SpraySchedule.planned_date.asc())
        .limit(10)
        .all()
    )
    results = []
    for s in schedules:
        product = db.query(SprayProduct).filter_by(id=s.product_id).first()
        if product is None:
            continue
        results.append({
            "schedule_id": s.id,
            "product_name": product.name,
            "category": product.category,
            "planned_date": s.planned_date,
            "planned_start": s.planned_start,
            "planned_end": s.planned_end,
            "status": s.status,
            "constraints": {
                "rain_free_hours": product.rain_free_hours,
                "max_wind_mph": product.max_wind_mph,
                "min_temp_f": product.min_temp_f,
                "max_temp_f": product.max_temp_f,
                "min_humidity_pct": product.min_humidity_pct,
                "max_humidity_pct": product.max_humidity_pct,
            },
            "notes": s.notes,
        })
    return results


def gather_spray_outcomes(db: Session) -> list[dict[str, Any]]:
    """Load recent spray outcomes with product info for AI context."""
    from ..models.spray import SprayOutcome, SpraySchedule, SprayProduct

    rows = (
        db.query(SprayOutcome, SprayProduct.name, SprayProduct.category)
        .join(SpraySchedule, SprayOutcome.schedule_id == SpraySchedule.id)
        .join(SprayProduct, SpraySchedule.product_id == SprayProduct.id)
        .order_by(SprayOutcome.logged_at.desc())
        .limit(20)
        .all()
    )
    results = []
    for o, product_name, category in rows:
        results.append({
            "product_name": product_name,
            "category": category,
            "effectiveness": o.effectiveness,
            "actual_wind_mph": o.actual_wind_mph,
            "actual_temp_f": o.actual_temp_f,
            "actual_rain_hours": o.actual_rain_hours,
            "drift_observed": bool(o.drift_observed),
            "product_efficacy": o.product_efficacy,
            "notes": o.notes,
            "logged_at": o.logged_at.isoformat() if o.logged_at else None,
        })
    return results


async def collect_all(
    db: Session,
    lat: float,
    lon: float,
    horizon_hours: int = 12,
    nws_forecast=None,
    station_timezone: str = "",
    radar_enabled: bool = True,
    nearby_iem_enabled: bool = False,
    nearby_wu_enabled: bool = False,
    nearby_radius: int = 25,
    nearby_max_iem: int = 5,
    nearby_max_wu: int = 5,
    nearby_aprs_enabled: bool = False,
    nearby_max_aprs: int = 10,
    wu_api_key: str = "",
    spray_ai_enabled: bool = False,
) -> CollectedData:
    """Gather all data sources into a single snapshot for the analyst."""
    station = gather_station_data(db, station_timezone)
    model = await fetch_model_guidance(lat, lon, horizon_hours)
    nws_summary = gather_nws_summary(nws_forecast)
    knowledge = gather_knowledge(db)
    # Resolve nearest NEXRAD site for velocity imagery.
    radar_station = ""
    if radar_enabled:
        from .forecast_nws import resolve_radar_station
        radar_station = await resolve_radar_station(lat, lon) or ""
    radar_images = await fetch_radar_images(lat, lon, radar_station) if radar_enabled else []

    # Fetch nearby station observations if either source is enabled.
    nearby = None
    if nearby_iem_enabled or nearby_wu_enabled or nearby_aprs_enabled:
        from .nearby_stations import fetch_nearby_stations
        nearby = await fetch_nearby_stations(
            lat=lat,
            lon=lon,
            radius_miles=nearby_radius,
            max_iem=nearby_max_iem,
            max_wu=nearby_max_wu,
            wu_api_key=wu_api_key,
            iem_enabled=nearby_iem_enabled,
            wu_enabled=nearby_wu_enabled,
            aprs_enabled=nearby_aprs_enabled,
            max_aprs=nearby_max_aprs,
        )

    # Fetch active NWS alerts (short cache, always enabled when location is set).
    nws_alerts: list[dict[str, Any]] = []
    if lat and lon:
        from .alerts_nws import fetch_nws_active_alerts
        from dataclasses import asdict
        alert_data = await fetch_nws_active_alerts(lat, lon)
        if alert_data:
            nws_alerts = [asdict(a) for a in alert_data.alerts]

    # Gather spray schedules and outcome history when AI spray advisory is enabled.
    spray = gather_spray_schedules(db) if spray_ai_enabled else []
    spray_history = gather_spray_outcomes(db) if spray_ai_enabled else []

    return CollectedData(
        station=station,
        model_guidance=model,
        nws_summary=nws_summary,
        knowledge_entries=knowledge,
        radar_images=radar_images,
        nearby_stations=nearby,
        nws_alerts=nws_alerts,
        spray_schedules=spray,
        spray_outcomes=spray_history,
        collected_at=_local_now_iso(station_timezone),
        location={"latitude": lat, "longitude": lon},
        station_timezone=station_timezone,
    )
