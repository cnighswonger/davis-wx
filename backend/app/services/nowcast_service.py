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
from .forecast_nws import fetch_nws_forecast

logger = logging.getLogger(__name__)

# Check interval — the service wakes every 60s to see if it's time to run.
CHECK_INTERVAL = 60


class NowcastService:
    """Scheduled nowcast generation service."""

    def __init__(self) -> None:
        self._enabled: bool = False
        self._api_key: str = ""
        self._model: str = "claude-haiku-4-5-20251001"
        self._interval: int = 900  # seconds
        self._horizon: int = 2  # hours
        self._latitude: float = 0.0
        self._longitude: float = 0.0
        self._auto_accept_hours: int = 48
        self._last_run: float = 0.0
        self._latest: Optional[dict] = None  # cached latest nowcast for quick API access

    def reload_config(self) -> None:
        """Read nowcast config from the station_config table."""
        db = SessionLocal()
        try:
            keys = [
                "nowcast_enabled", "nowcast_api_key", "nowcast_model",
                "nowcast_interval", "nowcast_horizon", "latitude",
                "longitude", "nowcast_knowledge_auto_accept_hours",
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
        finally:
            db.close()

    def get_latest(self) -> Optional[dict]:
        """Return the most recent nowcast (cached in memory for fast API response)."""
        return self._latest

    async def start(self) -> None:
        """Main loop — runs forever as a background task."""
        logger.info("Nowcast service started")
        while True:
            try:
                await self._tick()
            except Exception:
                logger.exception("Nowcast service tick failed")
            await asyncio.sleep(CHECK_INTERVAL)

    async def _tick(self) -> None:
        """Single iteration: check config, maybe generate, auto-accept knowledge."""
        self.reload_config()

        if not self._enabled:
            return

        if self._latitude == 0.0 and self._longitude == 0.0:
            return  # No location configured

        now = time.monotonic()
        if now - self._last_run < self._interval:
            return

        self._last_run = now
        await self._generate()
        self._auto_accept_knowledge()

    async def _generate(self) -> None:
        """Gather data and call Claude to generate a nowcast."""
        logger.info("Generating nowcast (model=%s, horizon=%dh)", self._model, self._horizon)

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
            )

            if not data.station.has_data:
                logger.warning("Nowcast skipped: no station data available")
                return

            # Call Claude.
            result = await generate_nowcast(
                data=data,
                model=self._model,
                api_key_from_db=self._api_key,
                horizon_hours=self._horizon,
            )

            if result is None:
                logger.warning("Nowcast generation returned no result")
                return

            # Store to database.
            self._store_result(db, result)

            # Handle proposed knowledge entry.
            if result.proposed_knowledge:
                self._store_proposed_knowledge(db, result.proposed_knowledge)

            db.commit()
            logger.info(
                "Nowcast generated: %d input tokens, %d output tokens",
                result.input_tokens, result.output_tokens,
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _store_result(self, db: Session, result: AnalystResult) -> None:
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
            model_used=self._model,
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
            "model_used": self._model,
            "summary": result.summary,
            "elements": result.elements,
            "farming_impact": result.farming_impact,
            "current_vs_model": result.current_vs_model,
            "data_quality": result.data_quality,
            "sources_used": self._sources_list(result),
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        }

    def _sources_list(self, result: AnalystResult) -> list[str]:
        """Build list of data sources used."""
        sources = ["local_station"]
        if result.data_quality and "model" in result.data_quality.lower():
            sources.append("open_meteo_hrrr")
        else:
            sources.append("open_meteo_hrrr")  # Always attempted
        sources.append("nws_forecast")
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
