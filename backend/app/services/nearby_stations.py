"""Fetch current observations from nearby weather stations.

Sources:
  - IEM ASOS/AWOS: Official NWS airport stations via Iowa Environmental Mesonet.
  - WU PWS: Personal weather stations via Weather Underground API.

Both are fetched concurrently, cached for 15 minutes, and combined into a
single sorted-by-distance list for the nowcast analyst.
"""

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# --- Constants ---

IEM_CURRENTS_URL = "https://mesonet.agron.iastate.edu/api/1/currents.json"
NWS_POINTS_URL = "https://api.weather.gov/points"
WU_NEARBY_URL = "https://api.weather.com/v3/location/near"
WU_OBS_URL = "https://api.weather.com/v2/pws/observations/current"
HTTP_TIMEOUT = 15.0
NEARBY_CACHE_TTL = 900  # 15 minutes
KNOTS_TO_MPH = 1.15078

CARDINALS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


# --- Dataclasses ---

@dataclass
class NearbyObservation:
    """A single observation from a nearby weather station."""
    source: str
    station_id: str
    station_name: str
    latitude: float
    longitude: float
    distance_miles: float
    bearing_cardinal: str
    timestamp: str
    temp_f: Optional[float] = None
    dew_point_f: Optional[float] = None
    humidity_pct: Optional[int] = None
    wind_speed_mph: Optional[float] = None
    wind_dir_deg: Optional[int] = None
    wind_gust_mph: Optional[float] = None
    pressure_inhg: Optional[float] = None
    precip_in: Optional[float] = None
    sky_cover: Optional[str] = None
    raw_metar: Optional[str] = None


@dataclass
class NearbyStationsResult:
    """Combined nearby station observations from all sources."""
    stations: list[NearbyObservation] = field(default_factory=list)
    iem_count: int = 0
    wu_count: int = 0
    aprs_count: int = 0
    fetched_at: float = 0.0


# --- Cache ---

@dataclass
class _CacheEntry:
    data: NearbyStationsResult
    expires_at: float

_nearby_cache: dict[str, _CacheEntry] = {}

# State code cache (location doesn't change during runtime).
_state_cache: dict[str, str] = {}


# --- Geo utilities ---

def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in miles between two lat/lon points."""
    R = 3958.8  # Earth radius in miles
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _bearing_cardinal(lat1: float, lon1: float, lat2: float, lon2: float) -> str:
    """8-point cardinal direction from point 1 to point 2."""
    dlon = math.radians(lon2 - lon1)
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    x = math.sin(dlon) * math.cos(rlat2)
    y = math.cos(rlat1) * math.sin(rlat2) - math.sin(rlat1) * math.cos(rlat2) * math.cos(dlon)
    bearing = (math.degrees(math.atan2(x, y)) + 360) % 360
    idx = round(bearing / 45) % 8
    return CARDINALS[idx]


# --- State resolution ---

async def _resolve_state(lat: float, lon: float) -> Optional[str]:
    """Resolve 2-letter US state code from coordinates via NWS points API.

    Cached permanently (location doesn't change).
    """
    key = f"{lat:.2f},{lon:.2f}"
    if key in _state_cache:
        return _state_cache[key]

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(
                f"{NWS_POINTS_URL}/{lat:.4f},{lon:.4f}",
                headers={"User-Agent": "DavisWxStation/1.0 (weather@localhost)"},
            )
            resp.raise_for_status()
            data = resp.json()
            state = data["properties"]["relativeLocation"]["properties"]["state"]
            _state_cache[key] = state
            logger.info("Resolved state for %.2f,%.2f: %s", lat, lon, state)
            return state
    except Exception as exc:
        logger.warning("Failed to resolve state from NWS: %s", exc)
        return None


# --- IEM ASOS fetch ---

async def _fetch_iem_nearby(
    lat: float,
    lon: float,
    state: str,
    radius_miles: int,
    max_stations: int,
) -> list[NearbyObservation]:
    """Fetch current ASOS/AWOS observations from IEM for the given state,
    then filter by distance from the station location."""
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(
                IEM_CURRENTS_URL,
                params={"network": f"{state}_ASOS"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("IEM ASOS fetch failed: %s", exc)
        return []

    stations_data = data.get("data", [])
    results: list[NearbyObservation] = []

    for s in stations_data:
        # Skip stations without temperature data (likely offline).
        if s.get("tmpf") is None:
            continue

        slat = s.get("lat")
        slon = s.get("lon")
        if slat is None or slon is None:
            continue

        dist = _haversine_miles(lat, lon, slat, slon)
        if dist > radius_miles or dist < 0.5:  # Skip own station if present
            continue

        sknt = s.get("sknt")
        gust = s.get("gust")

        results.append(NearbyObservation(
            source="iem_asos",
            station_id=s.get("station", "?"),
            station_name=s.get("name", "").replace("_", " ").title(),
            latitude=slat,
            longitude=slon,
            distance_miles=round(dist, 1),
            bearing_cardinal=_bearing_cardinal(lat, lon, slat, slon),
            timestamp=s.get("utc_valid", ""),
            temp_f=s.get("tmpf"),
            dew_point_f=s.get("dwpf"),
            humidity_pct=round(s["relh"]) if s.get("relh") is not None else None,
            wind_speed_mph=round(sknt * KNOTS_TO_MPH, 1) if sknt is not None else None,
            wind_dir_deg=int(s["drct"]) if s.get("drct") is not None else None,
            wind_gust_mph=round(gust * KNOTS_TO_MPH, 1) if gust is not None else None,
            pressure_inhg=s.get("alti"),
            precip_in=s.get("pday"),
            sky_cover=s.get("skyc1"),
            raw_metar=s.get("raw"),
        ))

    results.sort(key=lambda o: o.distance_miles)
    results = results[:max_stations]

    if results:
        logger.info(
            "Fetched %d IEM ASOS stations within %d miles",
            len(results), radius_miles,
        )

    return results


# --- WU PWS fetch ---

async def _fetch_wu_nearby(
    lat: float,
    lon: float,
    api_key: str,
    radius_miles: int,
    max_stations: int,
) -> list[NearbyObservation]:
    """Fetch current observations from nearby WU personal weather stations.

    Two-step process:
      1. v3/location/near — discover nearby station IDs (with distance).
      2. v2/pws/observations/current per station — fetch actual observations.
    Observations are fetched concurrently to minimise latency.
    """
    if not api_key:
        return []

    # Step 1: discover nearby stations.
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(
                WU_NEARBY_URL,
                params={
                    "geocode": f"{lat},{lon}",
                    "product": "pws",
                    "format": "json",
                    "apiKey": api_key,
                },
            )
            resp.raise_for_status()
            nearby_data = resp.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401:
            logger.warning("WU PWS nearby lookup failed: invalid API key")
        else:
            logger.warning("WU PWS nearby lookup failed: HTTP %d", exc.response.status_code)
        return []
    except Exception as exc:
        logger.warning("WU PWS nearby lookup failed: %s", exc)
        return []

    loc = nearby_data.get("location", {})
    station_ids = loc.get("stationId", [])
    distances = loc.get("distanceMi", [])
    names = loc.get("stationName", [])
    lats = loc.get("latitude", [])
    lons = loc.get("longitude", [])
    qc_statuses = loc.get("qcStatus", [])

    if not station_ids:
        return []

    # Filter to within radius and take only stations with good QC, up to max.
    candidates: list[tuple[int, str]] = []
    for i, sid in enumerate(station_ids):
        dist = distances[i] if i < len(distances) else 999
        qc = qc_statuses[i] if i < len(qc_statuses) else -1
        if dist <= radius_miles and dist > 0.1 and qc >= 0:
            candidates.append((i, sid))
        if len(candidates) >= max_stations:
            break

    if not candidates:
        return []

    # Step 2: fetch current observations concurrently.
    async def _fetch_one(session: httpx.AsyncClient, idx: int, sid: str) -> Optional[NearbyObservation]:
        try:
            r = await session.get(
                WU_OBS_URL,
                params={
                    "stationId": sid,
                    "format": "json",
                    "units": "e",
                    "numericPrecision": "decimal",
                    "apiKey": api_key,
                },
            )
            r.raise_for_status()
            obs_list = r.json().get("observations", [])
            if not obs_list:
                return None
            obs = obs_list[0]
        except Exception:
            return None

        slat = obs.get("lat", lats[idx] if idx < len(lats) else None)
        slon = obs.get("lon", lons[idx] if idx < len(lons) else None)
        if slat is None or slon is None:
            return None

        dist = distances[idx] if idx < len(distances) else _haversine_miles(lat, lon, slat, slon)
        imp: dict[str, Any] = obs.get("imperial", {})
        hum = obs.get("humidity")

        return NearbyObservation(
            source="wu_pws",
            station_id=obs.get("stationID", sid),
            station_name=obs.get("neighborhood", names[idx] if idx < len(names) else sid),
            latitude=slat,
            longitude=slon,
            distance_miles=round(dist, 1),
            bearing_cardinal=_bearing_cardinal(lat, lon, slat, slon),
            timestamp=obs.get("obsTimeUtc", ""),
            temp_f=imp.get("temp"),
            dew_point_f=imp.get("dewpt"),
            humidity_pct=round(hum) if hum is not None else None,
            wind_speed_mph=imp.get("windSpeed"),
            wind_dir_deg=obs.get("winddir"),
            wind_gust_mph=imp.get("windGust"),
            pressure_inhg=imp.get("pressure"),
            precip_in=imp.get("precipTotal"),
            sky_cover=None,
            raw_metar=None,
        )

    results: list[NearbyObservation] = []
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        tasks = [_fetch_one(client, idx, sid) for idx, sid in candidates]
        fetched = await asyncio.gather(*tasks, return_exceptions=True)
        for item in fetched:
            if isinstance(item, NearbyObservation):
                results.append(item)

    results.sort(key=lambda o: o.distance_miles)

    if results:
        logger.info(
            "Fetched %d WU PWS stations within %d miles",
            len(results), radius_miles,
        )

    return results


# --- Combined orchestrator ---

def _fetch_aprs_nearby(
    lat: float,
    lon: float,
    radius_miles: int,
    max_stations: int,
) -> list[NearbyObservation]:
    """Read CWOP/APRS-IS observations from the in-memory collector cache.

    Returns NearbyObservation objects sorted nearest-first.
    This is instant (no network I/O) — reads from the background listener cache.
    """
    from . import aprs_collector

    aprs_obs = aprs_collector.get_observations(lat, lon, radius_miles, max_stations)
    results: list[NearbyObservation] = []

    for obs in aprs_obs:
        dist = _haversine_miles(lat, lon, obs.latitude, obs.longitude)
        results.append(NearbyObservation(
            source="cwop_aprs",
            station_id=obs.callsign,
            station_name=obs.callsign,
            latitude=obs.latitude,
            longitude=obs.longitude,
            distance_miles=round(dist, 1),
            bearing_cardinal=_bearing_cardinal(lat, lon, obs.latitude, obs.longitude),
            timestamp=datetime.fromtimestamp(obs.timestamp, tz=timezone.utc).isoformat(),
            temp_f=obs.temp_f,
            humidity_pct=obs.humidity_pct,
            wind_speed_mph=obs.wind_speed_mph,
            wind_dir_deg=obs.wind_dir_deg,
            wind_gust_mph=obs.wind_gust_mph,
            pressure_inhg=obs.pressure_inhg,
            precip_in=obs.precip_in,
        ))

    if results:
        logger.info(
            "Fetched %d CWOP/APRS stations within %d miles",
            len(results), radius_miles,
        )

    return results


async def fetch_nearby_stations(
    lat: float,
    lon: float,
    radius_miles: int = 25,
    max_iem: int = 5,
    max_wu: int = 5,
    wu_api_key: str = "",
    iem_enabled: bool = True,
    wu_enabled: bool = True,
    aprs_enabled: bool = False,
    max_aprs: int = 10,
) -> NearbyStationsResult:
    """Fetch nearby station data from all enabled sources, with caching.

    Each source is fetched independently and concurrently. If one fails,
    the other still returns results. Results are cached for 15 minutes.
    """
    cache_key = f"{lat:.2f},{lon:.2f}"
    cached = _nearby_cache.get(cache_key)
    if cached is not None and time.time() < cached.expires_at:
        return cached.data

    iem_stations: list[NearbyObservation] = []
    wu_stations: list[NearbyObservation] = []
    aprs_stations: list[NearbyObservation] = []

    tasks: list[asyncio.Task] = []
    task_labels: list[str] = []

    if iem_enabled:
        state = await _resolve_state(lat, lon)
        if state:
            tasks.append(asyncio.create_task(
                _fetch_iem_nearby(lat, lon, state, radius_miles, max_iem)
            ))
            task_labels.append("iem")

    if wu_enabled and wu_api_key:
        tasks.append(asyncio.create_task(
            _fetch_wu_nearby(lat, lon, wu_api_key, radius_miles, max_wu)
        ))
        task_labels.append("wu")

    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for label, result in zip(task_labels, results):
            if isinstance(result, Exception):
                logger.warning("Nearby %s fetch raised: %s", label, result)
                continue
            if label == "iem":
                iem_stations = result
            elif label == "wu":
                wu_stations = result

    # APRS fetch is synchronous (reads from in-memory cache), no task needed.
    if aprs_enabled:
        try:
            aprs_stations = _fetch_aprs_nearby(lat, lon, radius_miles, max_aprs)
        except Exception as exc:
            logger.warning("Nearby APRS fetch raised: %s", exc)

    combined = iem_stations + wu_stations + aprs_stations
    combined.sort(key=lambda o: o.distance_miles)

    data = NearbyStationsResult(
        stations=combined,
        iem_count=len(iem_stations),
        wu_count=len(wu_stations),
        aprs_count=len(aprs_stations),
        fetched_at=time.time(),
    )

    _nearby_cache[cache_key] = _CacheEntry(
        data=data,
        expires_at=time.time() + NEARBY_CACHE_TTL,
    )

    return data
