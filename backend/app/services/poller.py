"""Async polling loop for Davis WeatherLink LOOP command.

Periodically polls the station, parses data, computes derived values,
stores to database, and broadcasts via a configurable callback.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Optional

from sqlalchemy import func

from ..protocol.link_driver import LinkDriver
from ..protocol.station_types import SensorReading
from ..protocol.constants import StationModel, STATION_NAMES
from ..services.calculations import (
    heat_index,
    dew_point,
    wind_chill,
    feels_like,
    equivalent_potential_temperature,
)
from ..services.pressure_trend import analyze_pressure_trend
from ..models.database import SessionLocal
from ..models.sensor_reading import SensorReadingModel

CARDINAL_DIRECTIONS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]

logger = logging.getLogger(__name__)


class Poller:
    """Manages the LOOP polling lifecycle."""

    def __init__(self, driver: LinkDriver, poll_interval: int = 10):
        self.driver = driver
        self.poll_interval = poll_interval
        self._running = False
        self._last_poll: Optional[datetime] = None
        self._last_rain_total: Optional[int] = None
        self._last_rain_tip_time: Optional[datetime] = None
        self._rain_rate_in_per_hr: float = 0.0
        self._crc_errors = 0
        self._timeouts = 0
        self._start_time = time.time()
        self._broadcast_callback: (
            Callable[[dict[str, Any]], Coroutine[Any, Any, Any]] | None
        ) = None

    @property
    def stats(self) -> dict:
        return {
            "last_poll": self._last_poll.isoformat() if self._last_poll else None,
            "crc_errors": self._crc_errors,
            "timeouts": self._timeouts,
            "uptime_seconds": int(time.time() - self._start_time),
        }

    async def run(self) -> None:
        """Main polling loop. Runs until cancelled."""
        self._running = True
        self._start_time = time.time()
        logger.info("Poller starting with %ds interval", self.poll_interval)

        while self._running:
            try:
                logger.debug("Sending LOOP poll...")
                reading = await self.driver.async_poll_loop()
                if reading is not None:
                    self._last_poll = datetime.now(timezone.utc)
                    logger.info(
                        "LOOP OK: outside_temp=%s wind=%s baro=%s",
                        reading.outside_temp, reading.wind_speed, reading.barometer,
                    )
                    await self._process_reading(reading)
                else:
                    self._timeouts += 1
                    logger.warning("LOOP poll returned no data (timeout #%d)", self._timeouts)
            except asyncio.CancelledError:
                break
            except Exception as e:
                if not self._running:
                    break
                logger.error("Polling error: %s", e, exc_info=True)
                self._timeouts += 1

            try:
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break

    def set_broadcast_callback(
        self,
        callback: Callable[[dict[str, Any]], Coroutine[Any, Any, Any]],
    ) -> None:
        """Set the async callback invoked after each reading.

        In the logger daemon this is IPCServer.broadcast_to_subscribers.
        """
        self._broadcast_callback = callback

    def stop(self) -> None:
        self._running = False
        self.driver.request_stop()

    async def _process_reading(self, reading: SensorReading) -> None:
        """Compute derived values, store to DB, broadcast to WS clients."""
        # Compute rain_rate from bucket tips for stations that don't provide it.
        # Uses time-between-tips with decay: rate holds steady until the next
        # expected tip is overdue, then decays toward 0.  After 15 min with no
        # tip, rate drops to 0 (rain stopped).
        if reading.rain_rate is None and reading.rain_total is not None:
            now = datetime.now(timezone.utc)

            if self._last_rain_total is not None:
                clicks_delta = reading.rain_total - self._last_rain_total
                if clicks_delta < 0:
                    clicks_delta = 0  # counter wrapped or reset

                if clicks_delta > 0 and self._last_rain_tip_time is not None:
                    # Bucket tipped — rate from time since last tip
                    elapsed_hr = (now - self._last_rain_tip_time).total_seconds() / 3600
                    if elapsed_hr > 0:
                        self._rain_rate_in_per_hr = (clicks_delta * 0.01) / elapsed_hr
                    self._last_rain_tip_time = now
                elif clicks_delta > 0:
                    # First tip since startup — record time, no rate yet
                    self._last_rain_tip_time = now
                elif self._last_rain_tip_time is not None:
                    # No new tips — decay: can't be raining faster than
                    # 0.01 / time_waiting or a tip would have occurred
                    elapsed_s = (now - self._last_rain_tip_time).total_seconds()
                    if elapsed_s > 900:  # 15 min timeout
                        self._rain_rate_in_per_hr = 0.0
                    else:
                        elapsed_hr = elapsed_s / 3600
                        if elapsed_hr > 0:
                            self._rain_rate_in_per_hr = min(
                                self._rain_rate_in_per_hr,
                                0.01 / elapsed_hr,
                            )

            # Convert to native unit (tenths of in/hr)
            reading.rain_rate = round(self._rain_rate_in_per_hr * 10)
            self._last_rain_total = reading.rain_total

        # Read yearly rain from station processor memory (separate WRD command)
        if self.driver.station_model is not None:
            try:
                yearly = await self.driver.async_read_rain_yearly()
                if yearly is not None:
                    reading.rain_yearly = yearly
            except Exception:
                pass  # non-critical — leave as None

        # Compute derived values
        hi = None
        dp = None
        wc = None
        fl = None
        theta = None
        trend = None

        if reading.outside_temp is not None and reading.outside_humidity is not None:
            hi = heat_index(reading.outside_temp, reading.outside_humidity)
            dp = dew_point(reading.outside_temp, reading.outside_humidity)

            if reading.barometer is not None:
                theta = equivalent_potential_temperature(
                    reading.outside_temp, reading.outside_humidity, reading.barometer
                )

        if reading.outside_temp is not None and reading.wind_speed is not None:
            wc = wind_chill(reading.outside_temp, reading.wind_speed)

        if (reading.outside_temp is not None
                and reading.outside_humidity is not None
                and reading.wind_speed is not None):
            fl = feels_like(
                reading.outside_temp, reading.outside_humidity, reading.wind_speed
            )

        # Pressure trend from recent history
        trend = await self._get_pressure_trend()

        # Store to database
        db = SessionLocal()
        try:
            model = SensorReadingModel(
                timestamp=datetime.now(timezone.utc),
                station_type=self.driver.station_model.value if self.driver.station_model else 0,
                inside_temp=reading.inside_temp,
                outside_temp=reading.outside_temp,
                inside_humidity=reading.inside_humidity,
                outside_humidity=reading.outside_humidity,
                wind_speed=reading.wind_speed,
                wind_direction=reading.wind_direction,
                barometer=reading.barometer,
                rain_total=reading.rain_total,
                rain_rate=reading.rain_rate,
                rain_yearly=reading.rain_yearly,
                solar_radiation=reading.solar_radiation,
                uv_index=reading.uv_index,
                heat_index=hi,
                dew_point=dp,
                wind_chill=wc,
                feels_like=fl,
                theta_e=theta,
                pressure_trend=trend,
            )
            db.add(model)
            db.commit()

            # Query daily extremes while session is open
            extremes = self._get_daily_extremes(db)
        finally:
            db.close()

        # Broadcast to subscribers (IPC clients / WebSocket relay)
        if self._broadcast_callback:
            await self._broadcast_callback({
                "type": "sensor_update",
                "data": self._reading_to_dict(reading, hi, dp, wc, fl, theta, trend, extremes),
            })

    async def _get_pressure_trend(self) -> Optional[str]:
        """Query last 3 hours of barometer readings for trend analysis."""
        db = SessionLocal()
        try:
            cutoff = datetime.now(timezone.utc).timestamp() - 3 * 3600
            results = (
                db.query(
                    SensorReadingModel.timestamp,
                    SensorReadingModel.barometer,
                )
                .filter(SensorReadingModel.barometer.isnot(None))
                .filter(SensorReadingModel.timestamp >= datetime.fromtimestamp(cutoff, tz=timezone.utc))
                .order_by(SensorReadingModel.timestamp)
                .all()
            )

            if len(results) < 2:
                return None

            readings = [(r.timestamp.timestamp(), r.barometer) for r in results]
            result = analyze_pressure_trend(readings)
            return result.trend if result else None
        finally:
            db.close()

    @staticmethod
    def _get_daily_extremes(db) -> Optional[dict]:
        """Query today's high/low extremes from sensor_readings."""
        now = datetime.now(timezone.utc)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

        S = SensorReadingModel
        row = (
            db.query(
                func.max(S.outside_temp), func.min(S.outside_temp),
                func.max(S.inside_temp), func.min(S.inside_temp),
                func.max(S.wind_speed),
                func.max(S.barometer), func.min(S.barometer),
                func.max(S.outside_humidity), func.min(S.outside_humidity),
                func.max(S.rain_rate),
            )
            .filter(S.timestamp >= midnight)
            .first()
        )

        if row is None or row[0] is None:
            return None

        def _val(raw, divisor=1, unit=""):
            if raw is None:
                return None
            return {"value": round(raw / divisor, 2) if divisor != 1 else raw, "unit": unit}

        return {
            "outside_temp_hi": _val(row[0], 10, "F"),
            "outside_temp_lo": _val(row[1], 10, "F"),
            "inside_temp_hi": _val(row[2], 10, "F"),
            "inside_temp_lo": _val(row[3], 10, "F"),
            "wind_speed_hi": _val(row[4], 1, "mph"),
            "barometer_hi": _val(row[5], 1000, "inHg"),
            "barometer_lo": _val(row[6], 1000, "inHg"),
            "humidity_hi": _val(row[7], 1, "%"),
            "humidity_lo": _val(row[8], 1, "%"),
            "rain_rate_hi": _val(row[9], 10, "in/hr"),
        }

    @staticmethod
    def _cardinal(degrees: Optional[int]) -> Optional[str]:
        if degrees is None:
            return None
        idx = round(degrees / 22.5) % 16
        return CARDINAL_DIRECTIONS[idx]

    def _reading_to_dict(
        self,
        reading: SensorReading,
        hi: Optional[int],
        dp: Optional[int],
        wc: Optional[int],
        fl: Optional[int],
        theta: Optional[int],
        trend: Optional[str],
        extremes: Optional[dict] = None,
    ) -> dict:
        """Convert a reading to a JSON-serializable dict for WebSocket.

        Format matches the REST /api/current response so the frontend
        can use the same CurrentConditions type for both sources.
        """
        def temp_f(tenths: Optional[int]) -> Optional[float]:
            return tenths / 10.0 if tenths is not None else None

        def bar_inhg(thousandths: Optional[int]) -> Optional[float]:
            return thousandths / 1000.0 if thousandths is not None else None

        model = self.driver.station_model
        station_name = STATION_NAMES.get(model, "Unknown") if model else "Unknown"

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "station_type": station_name,
            "temperature": {
                "inside": {"value": temp_f(reading.inside_temp), "unit": "F"},
                "outside": {"value": temp_f(reading.outside_temp), "unit": "F"},
            },
            "humidity": {
                "inside": {"value": reading.inside_humidity, "unit": "%"},
                "outside": {"value": reading.outside_humidity, "unit": "%"},
            },
            "wind": {
                "speed": {"value": reading.wind_speed, "unit": "mph"},
                "direction": {"value": reading.wind_direction, "unit": "°"},
                "cardinal": self._cardinal(reading.wind_direction),
            },
            "barometer": {
                "value": bar_inhg(reading.barometer),
                "unit": "inHg",
                "trend": trend,
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
                "heat_index": {"value": temp_f(hi), "unit": "F"},
                "dew_point": {"value": temp_f(dp), "unit": "F"},
                "wind_chill": {"value": temp_f(wc), "unit": "F"},
                "feels_like": {"value": temp_f(fl), "unit": "F"},
                "theta_e": {"value": theta / 10.0 if theta is not None else None, "unit": "K"},
            },
            "solar_radiation": (
                {"value": reading.solar_radiation, "unit": "W/m²"}
                if reading.solar_radiation is not None else None
            ),
            "uv_index": (
                {"value": reading.uv_index / 10.0 if reading.uv_index is not None else None, "unit": ""}
                if reading.uv_index is not None else None
            ),
            "daily_extremes": extremes,
        }
