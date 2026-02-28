"""Background APRS-IS listener for nearby CWOP weather station observations.

Connects to APRS-IS as a read-only client with a geographic range filter,
continuously reads weather packets, and maintains an in-memory cache of the
latest observation per callsign.  The nowcast nearby-stations pipeline reads
from this cache — instant, no blocking.

References:
    http://www.aprs-is.net/connecting.aspx
    http://www.aprs-is.net/javAPRSFilter.aspx
    http://www.aprs.org/doc/APRS101.PDF  (Chapter 12 — Weather)
"""

import asyncio
import logging
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# --- Constants ---

APRS_IS_SERVERS = [
    ("cwop.aprs.net", 14580),
    ("rotate.aprs2.net", 14580),
]
CONNECT_TIMEOUT = 15.0
READ_TIMEOUT = 120.0  # Keepalive comments arrive every ~20-30s
MILES_TO_KM = 1.60934
OBS_MAX_AGE = 1800  # 30 minutes — prune older observations
BACKOFF_INITIAL = 5.0
BACKOFF_MAX = 300.0
PRUNE_INTERVAL = 60  # Prune stale observations every 60 packets

# Tenths-of-hPa → inHg conversion factor.
TENTHS_HPA_TO_INHG = 1.0 / (33.8639 * 10.0)


# --- Dataclass ---

@dataclass
class APRSObservation:
    """A parsed weather observation from an APRS-IS packet."""
    callsign: str
    latitude: float
    longitude: float
    timestamp: float  # time.time() when received
    temp_f: Optional[float] = None
    humidity_pct: Optional[int] = None
    wind_speed_mph: Optional[float] = None
    wind_dir_deg: Optional[int] = None
    wind_gust_mph: Optional[float] = None
    pressure_inhg: Optional[float] = None
    precip_in: Optional[float] = None  # rain since midnight


# --- Module state ---

_observations: dict[str, APRSObservation] = {}
_task: Optional[asyncio.Task] = None
_stop_event: Optional[asyncio.Event] = None
_config: dict = {}  # lat, lon, radius_miles, own_callsign


# --- APRS weather packet parser ---

# Match uncompressed APRS position: DDMM.MMN/DDDMM.MMW
_POS_RE = re.compile(
    r"(\d{2})(\d{2}\.\d{2})([NS])"
    r"(.)"  # symbol table
    r"(\d{3})(\d{2}\.\d{2})([EW])"
)

# Weather data fields after the _ marker.
_WX_FIELD_RE = re.compile(
    r"_(\d{3})/(\d{3})"  # wind dir / speed
    r"(?:g(\d{3}))?"     # gust (optional)
    r"(?:t(-?\d{2,3}))?" # temperature (optional)
    r"(?:r(\d{3}))?"     # rain last hour (optional)
    r"(?:p(\d{3}))?"     # rain 24h (optional)
    r"(?:P(\d{3}))?"     # rain since midnight (optional)
    r"(?:h(\d{2}))?"     # humidity (optional)
    r"(?:b(\d{5}))?"     # barometer (optional)
)


def _parse_aprs_position(payload: str) -> Optional[tuple[float, float, int]]:
    """Extract lat/lon from uncompressed APRS position in payload.

    Returns (lat, lon, offset_after_position) or None.
    """
    m = _POS_RE.search(payload)
    if not m:
        return None

    lat_deg = int(m.group(1))
    lat_min = float(m.group(2))
    lat = lat_deg + lat_min / 60.0
    if m.group(3) == "S":
        lat = -lat

    lon_deg = int(m.group(5))
    lon_min = float(m.group(6))
    lon = lon_deg + lon_min / 60.0
    if m.group(7) == "W":
        lon = -lon

    return lat, lon, m.end()


def parse_aprs_weather(raw_line: str) -> Optional[APRSObservation]:
    """Parse a raw APRS-IS line into an APRSObservation.

    Returns None if the line is not a valid weather packet.
    """
    # Skip server comments.
    if raw_line.startswith("#"):
        return None

    # TNC-2 format: CALLSIGN>PATH:PAYLOAD
    colon = raw_line.find(":")
    if colon < 0:
        return None

    header = raw_line[:colon]
    payload = raw_line[colon + 1:]

    # Extract source callsign (before first > or -).
    gt = header.find(">")
    if gt < 0:
        return None
    callsign = header[:gt].split("-")[0].strip().upper()

    if not callsign:
        return None

    # Data type indicator is the first char of payload.
    if not payload:
        return None
    dtype = payload[0]

    # We handle complete weather reports (@ ! = /) that contain position.
    if dtype not in ("@", "!", "=", "/"):
        # Positionless weather starts with _, but we skip those (no position).
        return None

    # Parse position.
    pos = _parse_aprs_position(payload)
    if pos is None:
        return None
    lat, lon, pos_end = pos

    # Look for weather data marker (_) after position.
    wx_start = payload.find("_", pos_end)
    if wx_start < 0:
        return None

    wx_data = payload[wx_start:]
    m = _WX_FIELD_RE.match(wx_data)
    if not m:
        return None

    wind_dir_raw = m.group(1)
    wind_spd_raw = m.group(2)
    gust_raw = m.group(3)
    temp_raw = m.group(4)
    # rain_hr = m.group(5)  # Not used in NearbyObservation
    # rain_24 = m.group(6)
    rain_mid_raw = m.group(7)
    hum_raw = m.group(8)
    baro_raw = m.group(9)

    # Must have at least temperature to be useful.
    if temp_raw is None:
        return None

    temp_f = float(temp_raw)
    wind_dir = int(wind_dir_raw) if wind_dir_raw != "..." else None
    wind_speed = float(wind_spd_raw) if wind_spd_raw != "..." else None
    wind_gust = float(gust_raw) if gust_raw else None

    humidity = None
    if hum_raw:
        humidity = int(hum_raw)
        if humidity == 0:
            humidity = 100  # APRS convention: 00 = 100%

    pressure_inhg = None
    if baro_raw:
        tenths_hpa = int(baro_raw)
        pressure_inhg = round(tenths_hpa * TENTHS_HPA_TO_INHG, 2)

    precip_in = None
    if rain_mid_raw:
        precip_in = round(int(rain_mid_raw) / 100.0, 2)

    return APRSObservation(
        callsign=callsign,
        latitude=lat,
        longitude=lon,
        timestamp=time.time(),
        temp_f=temp_f,
        humidity_pct=humidity,
        wind_speed_mph=wind_speed,
        wind_dir_deg=wind_dir,
        wind_gust_mph=wind_gust,
        pressure_inhg=pressure_inhg,
        precip_in=precip_in,
    )


# --- Background listener ---

def _prune_stale() -> int:
    """Remove observations older than OBS_MAX_AGE. Returns count removed."""
    cutoff = time.time() - OBS_MAX_AGE
    stale = [k for k, v in _observations.items() if v.timestamp < cutoff]
    for k in stale:
        del _observations[k]
    return len(stale)


async def _listen_loop(
    lat: float,
    lon: float,
    radius_km: int,
    own_callsign: str,
    stop: asyncio.Event,
) -> None:
    """Persistent connection loop with auto-reconnect and backoff."""
    backoff = BACKOFF_INITIAL
    packet_count = 0

    while not stop.is_set():
        for host, port in APRS_IS_SERVERS:
            if stop.is_set():
                return
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=CONNECT_TIMEOUT,
                )
            except (OSError, asyncio.TimeoutError) as exc:
                logger.warning("APRS-IS connect to %s:%d failed: %s", host, port, exc)
                continue

            try:
                # Read server banner.
                banner = await asyncio.wait_for(reader.readline(), timeout=CONNECT_TIMEOUT)
                logger.debug("APRS-IS banner: %s", banner.decode(errors="replace").strip())

                # Send read-only login with filter.
                login = (
                    f"user N0CALL pass -1 vers davis-wx 1.0 "
                    f"filter r/{lat:.4f}/{lon:.4f}/{radius_km} t/w\r\n"
                )
                writer.write(login.encode())
                await writer.drain()

                # Read login acknowledgement.
                ack = await asyncio.wait_for(reader.readline(), timeout=CONNECT_TIMEOUT)
                ack_text = ack.decode(errors="replace").strip()
                logger.info("APRS-IS connected to %s:%d — %s", host, port, ack_text)

                backoff = BACKOFF_INITIAL  # Reset on successful connect.

                # Read packets until disconnect or stop.
                while not stop.is_set():
                    try:
                        raw = await asyncio.wait_for(
                            reader.readline(), timeout=READ_TIMEOUT,
                        )
                    except asyncio.TimeoutError:
                        # No data in READ_TIMEOUT — server may have dropped us.
                        logger.warning("APRS-IS read timeout, reconnecting")
                        break

                    if not raw:
                        logger.warning("APRS-IS connection closed by server")
                        break

                    line = raw.decode(errors="replace").strip()
                    if not line or line.startswith("#"):
                        continue  # Server comment / keepalive.

                    obs = parse_aprs_weather(line)
                    if obs is None:
                        continue

                    # Skip own station.
                    if own_callsign and obs.callsign == own_callsign:
                        continue

                    _observations[obs.callsign] = obs
                    packet_count += 1

                    # Periodic prune.
                    if packet_count % PRUNE_INTERVAL == 0:
                        removed = _prune_stale()
                        if removed:
                            logger.debug(
                                "APRS cache pruned %d stale, %d active",
                                removed, len(_observations),
                            )

            except Exception as exc:
                logger.warning("APRS-IS error on %s:%d: %s", host, port, exc)
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

            # If we get here, connection was lost — try next server.

        # All servers failed this round — backoff before retry.
        if not stop.is_set():
            logger.info("APRS-IS reconnecting in %.0fs", backoff)
            try:
                await asyncio.wait_for(stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, BACKOFF_MAX)


# --- Public API ---

async def start(
    lat: float,
    lon: float,
    radius_miles: int,
    own_callsign: str = "",
) -> None:
    """Start the background APRS-IS listener."""
    global _task, _stop_event, _config

    # Stop any existing listener first.
    await stop()

    radius_km = int(math.ceil(radius_miles * MILES_TO_KM))
    own_call = own_callsign.strip().upper()

    _config = {
        "lat": lat, "lon": lon,
        "radius_miles": radius_miles, "own_callsign": own_call,
    }

    _stop_event = asyncio.Event()
    _task = asyncio.create_task(
        _listen_loop(lat, lon, radius_km, own_call, _stop_event),
        name="aprs-collector",
    )
    logger.info(
        "APRS collector started (%.4f, %.4f, %d mi / %d km, exclude=%s)",
        lat, lon, radius_miles, radius_km, own_call or "none",
    )


async def stop() -> None:
    """Stop the background listener and clear observations."""
    global _task, _stop_event

    if _stop_event is not None:
        _stop_event.set()
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
        _task = None
    _stop_event = None
    _observations.clear()
    logger.info("APRS collector stopped")


def is_running() -> bool:
    """Check if the collector task is active."""
    return _task is not None and not _task.done()


def get_observations(
    lat: float,
    lon: float,
    radius_miles: int,
    max_stations: int,
) -> list[APRSObservation]:
    """Return current observations filtered by distance, sorted nearest-first.

    Reads from in-memory cache — instant, never blocks.
    """
    from .nearby_stations import _haversine_miles

    _prune_stale()
    results: list[tuple[float, APRSObservation]] = []

    for obs in _observations.values():
        dist = _haversine_miles(lat, lon, obs.latitude, obs.longitude)
        if dist <= radius_miles and dist > 0.5:
            results.append((dist, obs))

    results.sort(key=lambda x: x[0])
    return [obs for _, obs in results[:max_stations]]
