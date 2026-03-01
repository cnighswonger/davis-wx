"""Background service that periodically generates AI nowcasts.

Runs as an asyncio task inside the FastAPI web app. Checks config
on each iteration, gathers data, calls Claude, and stores results.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ..models.database import SessionLocal
from ..models.station_config import StationConfigModel
from ..models.nowcast import NowcastHistory, NowcastKnowledge
from .nowcast_collector import collect_all
from .nowcast_analyst import generate_nowcast, AnalystResult
from .nowcast_verifier import verify_expired_nowcasts
from .forecast_nws import fetch_nws_forecast

logger = logging.getLogger(__name__)

# Check interval — the service wakes every 60s to see if it's time to run.
CHECK_INTERVAL = 60

# During active NWS alerts, shorten the nowcast cycle for faster updates.
ALERT_MODE_INTERVAL = 300  # 5 minutes


class NowcastService:
    """Scheduled nowcast generation service."""

    def __init__(self) -> None:
        self._enabled: bool = False
        self._api_key: str = ""
        self._model: str = "claude-haiku-4-5-20251001"
        self._interval: int = 900  # seconds
        self._horizon: int = 2  # hours
        self._max_tokens: int = 3500
        self._latitude: float = 0.0
        self._longitude: float = 0.0
        self._auto_accept_hours: int = 48
        self._station_timezone: str = ""
        self._radar_enabled: bool = True
        self._nearby_iem_enabled: bool = True
        self._nearby_wu_enabled: bool = False
        self._nearby_max_iem: int = 5
        self._nearby_max_wu: int = 5
        self._nearby_aprs_enabled: bool = False
        self._nearby_max_aprs: int = 10
        self._wu_api_key: str = ""
        self._nearby_radius: int = 25
        self._cwop_callsign: str = ""
        self._spray_ai_enabled: bool = False
        self._last_run: float = 0.0
        self._latest: Optional[dict] = None  # cached latest nowcast for quick API access
        self._prev_alert_ids: set[str] = set()  # alert_ids from last cycle
        self._alert_mode: bool = False  # True when NWS alerts are active

    def reload_config(self) -> None:
        """Read nowcast config from the station_config table."""
        db = SessionLocal()
        try:
            keys = [
                "nowcast_enabled", "nowcast_api_key", "nowcast_model",
                "nowcast_interval", "nowcast_horizon", "nowcast_max_tokens", "latitude",
                "longitude", "nowcast_knowledge_auto_accept_hours",
                "station_timezone", "nowcast_radar_enabled",
                "nowcast_nearby_iem_enabled", "nowcast_nearby_wu_enabled",
                "nowcast_nearby_aprs_enabled",
                "nowcast_wu_api_key", "nowcast_nearby_max_iem",
                "nowcast_nearby_max_wu", "nowcast_nearby_max_aprs",
                "nowcast_radius", "cwop_callsign",
                "spray_ai_enabled",
            ]
            rows = db.query(StationConfigModel).filter(
                StationConfigModel.key.in_(keys)
            ).all()
            cfg = {r.key: r.value for r in rows}

            self._enabled = cfg.get("nowcast_enabled", "false").lower() == "true"
            self._api_key = cfg.get("nowcast_api_key", "")
            self._model = cfg.get("nowcast_model", "claude-haiku-4-5-20251001")
            try:
                self._interval = int(cfg.get("nowcast_interval", "900"))
            except ValueError:
                self._interval = 900
            try:
                self._horizon = int(cfg.get("nowcast_horizon", "2"))
            except ValueError:
                self._horizon = 2
            try:
                self._max_tokens = int(cfg.get("nowcast_max_tokens", "3500"))
            except ValueError:
                self._max_tokens = 3500
            try:
                self._latitude = float(cfg.get("latitude", "0"))
            except ValueError:
                self._latitude = 0.0
            try:
                self._longitude = float(cfg.get("longitude", "0"))
            except ValueError:
                self._longitude = 0.0
            try:
                self._auto_accept_hours = int(cfg.get("nowcast_knowledge_auto_accept_hours", "48"))
            except ValueError:
                self._auto_accept_hours = 48
            self._station_timezone = cfg.get("station_timezone", "")
            self._radar_enabled = cfg.get("nowcast_radar_enabled", "true").lower() == "true"
            self._nearby_iem_enabled = cfg.get(
                "nowcast_nearby_iem_enabled", "true"
            ).lower() == "true"
            self._nearby_wu_enabled = cfg.get(
                "nowcast_nearby_wu_enabled", "false"
            ).lower() == "true"
            self._wu_api_key = cfg.get("nowcast_wu_api_key", "")
            try:
                self._nearby_max_iem = int(cfg.get("nowcast_nearby_max_iem", "5"))
            except ValueError:
                self._nearby_max_iem = 5
            try:
                self._nearby_max_wu = int(cfg.get("nowcast_nearby_max_wu", "5"))
            except ValueError:
                self._nearby_max_wu = 5
            self._nearby_aprs_enabled = cfg.get(
                "nowcast_nearby_aprs_enabled", "false"
            ).lower() == "true"
            try:
                self._nearby_max_aprs = int(cfg.get("nowcast_nearby_max_aprs", "10"))
            except ValueError:
                self._nearby_max_aprs = 10
            self._cwop_callsign = cfg.get("cwop_callsign", "")
            try:
                self._nearby_radius = int(cfg.get("nowcast_radius", "25"))
            except ValueError:
                self._nearby_radius = 25
            self._spray_ai_enabled = cfg.get("spray_ai_enabled", "false").lower() == "true"

            # Budget check — may auto-pause nowcast
            if self._enabled:
                from ..api.usage import check_budget
                if check_budget(db):
                    # Re-read enabled flag since check_budget may have changed it
                    row = db.query(StationConfigModel).filter_by(key="nowcast_enabled").first()
                    if row and row.value.lower() != "true":
                        self._enabled = False
        finally:
            db.close()

    def is_enabled(self) -> bool:
        """Check if the nowcast service is enabled."""
        return self._enabled

    def get_latest(self) -> Optional[dict]:
        """Return the most recent nowcast (cached in memory for fast API response)."""
        return self._latest

    async def generate_once(self) -> None:
        """Trigger a single nowcast generation (called from API)."""
        await self._generate()

    def _seed_from_db(self) -> None:
        """Load the latest nowcast from DB into memory on startup.

        Populates ``_latest`` for immediate API responses and sets
        ``_last_run`` so the service respects the existing interval
        instead of immediately triggering a new API call.
        """
        db = SessionLocal()
        try:
            record = (
                db.query(NowcastHistory)
                .order_by(NowcastHistory.created_at.desc())
                .first()
            )
            if record is None:
                return

            # Populate the in-memory cache using the same logic as the API.
            from ..api.nowcast import _history_to_dict
            self._latest = _history_to_dict(record)

            # If the nowcast is still within the update interval, set
            # _last_run so we don't regenerate immediately.
            if record.created_at:
                created = record.created_at.replace(tzinfo=timezone.utc) if record.created_at.tzinfo is None else record.created_at
                age_seconds = (datetime.now(timezone.utc) - created).total_seconds()
                if age_seconds < self._interval:
                    self._last_run = time.monotonic() - age_seconds
                    logger.info(
                        "Nowcast seeded from DB (age %.0fs, next in %.0fs)",
                        age_seconds, self._interval - age_seconds,
                    )
                else:
                    logger.info("Nowcast seeded from DB (age %.0fs, due for refresh)", age_seconds)
        except Exception:
            logger.exception("Failed to seed nowcast from DB")
        finally:
            db.close()

    async def _manage_aprs_collector(self) -> None:
        """Start or stop the APRS collector based on current config."""
        from . import aprs_collector

        should_run = (
            self._enabled
            and self._nearby_aprs_enabled
            and self._latitude != 0.0
            and self._longitude != 0.0
        )

        if should_run and not aprs_collector.is_running():
            await aprs_collector.start(
                self._latitude, self._longitude,
                self._nearby_radius, self._cwop_callsign,
            )
        elif not should_run and aprs_collector.is_running():
            await aprs_collector.stop()

    async def start(self) -> None:
        """Main loop — runs forever as a background task."""
        logger.info("Nowcast service started")
        self.reload_config()
        self._seed_from_db()
        await self._manage_aprs_collector()
        while True:
            try:
                await self._tick()
            except Exception:
                logger.exception("Nowcast service tick failed")
            await asyncio.sleep(CHECK_INTERVAL)

    async def _tick(self) -> None:
        """Single iteration: check config, maybe generate, auto-accept knowledge."""
        self.reload_config()
        await self._manage_aprs_collector()

        if not self._enabled:
            return

        if self._latitude == 0.0 and self._longitude == 0.0:
            return  # No location configured

        now = time.monotonic()

        # Mid-cycle alert check — detect NEW alerts between cycles
        # (uses alerts_nws 2-min cache, so this is cheap).
        if self._latitude and self._longitude:
            from .alerts_nws import fetch_nws_active_alerts
            alert_data = await fetch_nws_active_alerts(
                self._latitude, self._longitude,
            )
            if alert_data:
                current_ids = {a.alert_id for a in alert_data.alerts}
                new_alerts = current_ids - self._prev_alert_ids
                if new_alerts:
                    logger.warning(
                        "New NWS alert detected mid-cycle, triggering immediate nowcast"
                    )
                    self._last_run = now
                    await self._generate()
                    self._auto_accept_knowledge()
                    self._verify_expired()
                    return

        # Use shorter interval when NWS alerts are active.
        effective_interval = (
            min(self._interval, ALERT_MODE_INTERVAL)
            if self._alert_mode
            else self._interval
        )
        if now - self._last_run < effective_interval:
            return

        self._last_run = now
        await self._generate()
        self._auto_accept_knowledge()
        self._verify_expired()

    async def _generate(self) -> None:
        """Gather data and call Claude to generate a nowcast."""
        logger.info("Collecting nowcast data (horizon=%dh)", self._horizon)

        db = SessionLocal()
        try:
            # Fetch NWS forecast (uses its own cache).
            nws = await fetch_nws_forecast(self._latitude, self._longitude)

            # Collect all data sources.
            data = await collect_all(
                db=db,
                lat=self._latitude,
                lon=self._longitude,
                horizon_hours=self._horizon,
                nws_forecast=nws,
                station_timezone=self._station_timezone,
                radar_enabled=self._radar_enabled,
                nearby_iem_enabled=self._nearby_iem_enabled,
                nearby_wu_enabled=self._nearby_wu_enabled,
                nearby_radius=self._nearby_radius,
                nearby_max_iem=self._nearby_max_iem,
                nearby_max_wu=self._nearby_max_wu,
                nearby_aprs_enabled=self._nearby_aprs_enabled,
                nearby_max_aprs=self._nearby_max_aprs,
                wu_api_key=self._wu_api_key,
                spray_ai_enabled=self._spray_ai_enabled,
            )

            if not data.station.has_data:
                logger.warning("Nowcast skipped: no station data available")
                return

            # Track alert state changes.
            current_alert_ids = {a["alert_id"] for a in data.nws_alerts}
            new_alerts = current_alert_ids - self._prev_alert_ids
            was_alert_mode = self._alert_mode
            self._prev_alert_ids = current_alert_ids
            self._alert_mode = bool(current_alert_ids)

            if new_alerts:
                logger.warning("New NWS alert(s) detected: %d new", len(new_alerts))
                await self._broadcast_alert_status(data.nws_alerts, is_new=True)
            elif self._alert_mode and not was_alert_mode:
                await self._broadcast_alert_status(data.nws_alerts, is_new=False)
            elif was_alert_mode and not self._alert_mode:
                await self._broadcast_alert_status([], is_new=False)

            # Increase token budget when NWS alerts are active to ensure
            # the severe_weather correlation output is never truncated.
            effective_max_tokens = self._max_tokens
            if data.nws_alerts:
                effective_max_tokens = self._max_tokens + 500
                logger.info(
                    "Active NWS alerts detected, increasing max_tokens to %d",
                    effective_max_tokens,
                )

            # Escalate model during active NWS alerts — Haiku is fast
            # but lacks reasoning depth for severe weather correlation.
            effective_model = self._model
            if data.nws_alerts and "haiku" in self._model.lower():
                effective_model = "claude-sonnet-4-5-20250929"
                logger.warning(
                    "Active NWS alerts: escalating model from Haiku to Sonnet"
                )

            # Call Claude.
            logger.info(
                "Generating nowcast (model=%s, max_tokens=%d)",
                effective_model, effective_max_tokens,
            )
            result = await generate_nowcast(
                data=data,
                model=effective_model,
                api_key_from_db=self._api_key,
                horizon_hours=self._horizon,
                max_tokens=effective_max_tokens,
                radar_station=data.radar_station,
            )

            if result is None:
                logger.warning("Nowcast generation returned no result")
                return

            # Retry once with +10% tokens if response was truncated and unparseable.
            if result.parse_failed:
                retry_tokens = int(self._max_tokens * 1.1)
                logger.warning(
                    "Nowcast truncated and unparseable, retrying with %d tokens (+10%%)",
                    retry_tokens,
                )
                result = await generate_nowcast(
                    data=data,
                    model=effective_model,
                    api_key_from_db=self._api_key,
                    horizon_hours=self._horizon,
                    max_tokens=retry_tokens,
                    radar_station=data.radar_station,
                )
                if result is None or result.parse_failed:
                    logger.error(
                        "Nowcast retry also failed — discarding result, keeping previous nowcast"
                    )
                    await self._broadcast_warning(
                        f"Nowcast response truncated even after retry ({retry_tokens} tokens). "
                        "Consider increasing Max Output Tokens in Settings > Nowcast."
                    )
                    return

            # Store to database.
            self._store_result(db, result, effective_model)

            # Handle proposed knowledge entry.
            if result.proposed_knowledge:
                self._store_proposed_knowledge(db, result.proposed_knowledge)

            # Write AI spray commentary back to individual schedule records.
            if result.spray_advisory:
                self._update_spray_schedules(db, result.spray_advisory)

            db.commit()
            logger.info(
                "Nowcast generated: %d input tokens, %d output tokens",
                result.input_tokens, result.output_tokens,
            )

            # Push update to connected browser clients via WebSocket.
            await self._broadcast_nowcast()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _store_result(self, db: Session, result: AnalystResult, model_used: str) -> None:
        """Write nowcast result to the database and update in-memory cache."""
        now = datetime.now(timezone.utc)
        valid_until = now + timedelta(hours=self._horizon)

        # Build confidence dict from elements.
        confidence = {}
        for key, val in result.elements.items():
            if isinstance(val, dict) and "confidence" in val:
                confidence[key] = val["confidence"]

        record = NowcastHistory(
            created_at=now,
            valid_from=now,
            valid_until=valid_until,
            model_used=model_used,
            summary=result.summary,
            details=json.dumps(result.elements),
            confidence=json.dumps(confidence),
            sources_used=json.dumps(self._sources_list(result)),
            raw_response=result.raw_response,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        db.add(record)
        db.flush()  # get record.id

        # Update in-memory cache for fast API access.
        self._latest = {
            "id": record.id,
            "created_at": now.isoformat(),
            "valid_from": now.isoformat(),
            "valid_until": valid_until.isoformat(),
            "model_used": model_used,
            "summary": result.summary,
            "elements": result.elements,
            "farming_impact": result.farming_impact,
            "current_vs_model": result.current_vs_model,
            "data_quality": result.data_quality,
            "sources_used": self._sources_list(result),
            "radar_analysis": result.radar_analysis,
            "spray_advisory": result.spray_advisory,
            "severe_weather": result.severe_weather,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        }

    async def _broadcast_nowcast(self) -> None:
        """Push the latest nowcast to all connected WebSocket clients."""
        if self._latest is None:
            return
        try:
            from ..ws.handler import ws_manager
            await ws_manager.broadcast({
                "type": "nowcast_update",
                "data": self._latest,
            })
        except Exception as exc:
            logger.debug("Nowcast WS broadcast failed: %s", exc)

    async def _broadcast_warning(self, message: str) -> None:
        """Push a warning toast to all connected WebSocket clients."""
        try:
            from ..ws.handler import ws_manager
            await ws_manager.broadcast({
                "type": "nowcast_warning",
                "data": {"message": message},
            })
        except Exception as exc:
            logger.debug("Nowcast warning WS broadcast failed: %s", exc)

    async def _broadcast_alert_status(
        self, alerts: list, is_new: bool = False,
    ) -> None:
        """Notify frontend of severe weather mode changes."""
        try:
            from ..ws.handler import ws_manager
            await ws_manager.broadcast({
                "type": "severe_weather_status",
                "data": {
                    "alert_mode": bool(alerts),
                    "is_new_alert": is_new,
                    "alert_count": len(alerts),
                    "cycle_interval": ALERT_MODE_INTERVAL if alerts else self._interval,
                },
            })
        except Exception as exc:
            logger.debug("Alert status WS broadcast failed: %s", exc)

    def _sources_list(self, result: AnalystResult) -> list[str]:
        """Build list of data sources used."""
        sources = ["local_station"]
        sources.append("open_meteo_hrrr")
        sources.append("nws_forecast")
        if result.radar_analysis:
            sources.append("nexrad_radar")
        if self._nearby_iem_enabled:
            sources.append("iem_asos_nearby")
        if self._nearby_wu_enabled and self._wu_api_key:
            sources.append("wu_pws_nearby")
        if self._nearby_aprs_enabled:
            sources.append("cwop_aprs_nearby")
        sources.append("nws_active_alerts")
        return sources

    def _store_proposed_knowledge(self, db: Session, proposed: dict[str, str]) -> None:
        """Store an AI-proposed knowledge base entry as pending."""
        auto_accept_at = None
        if self._auto_accept_hours > 0:
            auto_accept_at = datetime.now(timezone.utc) + timedelta(hours=self._auto_accept_hours)

        entry = NowcastKnowledge(
            source="ai_proposed",
            category=proposed.get("category", "general"),
            content=proposed.get("content", ""),
            status="pending",
            auto_accept_at=auto_accept_at,
        )
        db.add(entry)
        logger.info("Knowledge entry proposed: [%s] %s", entry.category, entry.content[:80])

    def _update_spray_schedules(self, db: Session, advisory: dict) -> None:
        """Write AI commentary from spray_advisory back to SpraySchedule records."""
        from ..models.spray import SpraySchedule

        recommendations = advisory.get("recommendations", [])
        if not recommendations:
            return

        for rec in recommendations:
            schedule_id = rec.get("schedule_id")
            if schedule_id is None:
                continue
            schedule = db.query(SpraySchedule).filter_by(id=schedule_id).first()
            if schedule is None:
                continue
            schedule.ai_commentary = json.dumps({
                "go": rec.get("go"),
                "detail": rec.get("detail", ""),
                "summary": advisory.get("summary", ""),
            })
            logger.info("Spray AI commentary written for schedule #%d", schedule_id)

    def _verify_expired(self) -> None:
        """Check for expired nowcasts that need verification."""
        db = SessionLocal()
        try:
            count = verify_expired_nowcasts(db, self._auto_accept_hours)
            if count > 0:
                logger.info("Verified %d expired nowcast(s)", count)
        except Exception:
            logger.exception("Verification check failed")
        finally:
            db.close()

    def _auto_accept_knowledge(self) -> None:
        """Auto-accept pending knowledge entries past their deadline."""
        if self._auto_accept_hours <= 0:
            return  # Manual-only mode

        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            pending = (
                db.query(NowcastKnowledge)
                .filter(
                    NowcastKnowledge.status == "pending",
                    NowcastKnowledge.auto_accept_at.isnot(None),
                    NowcastKnowledge.auto_accept_at <= now,
                )
                .all()
            )
            for entry in pending:
                entry.status = "accepted"
                entry.reviewed_at = now
                logger.info("Knowledge auto-accepted: [%s] %s", entry.category, entry.content[:80])
            if pending:
                db.commit()
        finally:
            db.close()


# Module-level singleton for use by API endpoints.
nowcast_service = NowcastService()
