"""FastAPI application factory and lifespan for Davis Weather Station."""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from .config import settings
from .models.database import init_database, SessionLocal
from .models.station_config import StationConfigModel
from .protocol.link_driver import LinkDriver
from .services.poller import Poller
from .api.router import api_router
from .api import station as station_api
from .api import setup as setup_api
from .api import weatherlink as weatherlink_api
from .api import backgrounds as backgrounds_api
from .ws.handler import websocket_endpoint, set_driver as ws_set_driver

# Configure logging for our app (uvicorn only configures its own loggers)
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:     %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Shared mutable state — accessed by setup.py for reconnect
_app_refs: dict = {
    "driver": None,
    "poller": None,
    "poller_task": None,
}


def _try_serial_connect(port: str, baud: int, timeout: float):
    """Attempt serial connection, station detection, and poller start.

    Updates _app_refs on success. Raises on failure.
    """
    return port, baud, timeout  # placeholder — actual logic is async


async def _bg_connect(port: str, baud: int):
    """Connect to serial port in the background so uvicorn starts immediately."""
    try:
        await _async_connect(port, baud)
    except Exception as e:
        logger.error("Background serial connect failed: %s", e)


async def _bg_connect_and_mark_setup(port: str, baud: int):
    """Try connecting with defaults; if it works, auto-mark setup complete."""
    try:
        await _async_connect(port, baud)
    except Exception as e:
        logger.info("Could not connect with .env defaults (%s)", e)
        logger.info("Waiting for first-run setup wizard")
        return

    # Connection worked → auto-mark setup complete (upgrade path)
    try:
        db = SessionLocal()
        try:
            existing = db.query(StationConfigModel).filter_by(
                key="setup_complete"
            ).first()
            if existing:
                existing.value = "true"
                existing.updated_at = datetime.now(timezone.utc)
            else:
                db.add(StationConfigModel(
                    key="setup_complete", value="true",
                    updated_at=datetime.now(timezone.utc),
                ))
            db.commit()
            logger.info("Existing install detected — auto-marked setup complete")
        finally:
            db.close()
    except Exception as e:
        logger.error("Failed to mark setup complete: %s", e, exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: start/stop serial polling and services."""

    # Initialize database
    logger.info("Database: %s", settings.db_path)
    init_database()
    logger.info("Database initialized")

    # Share refs with setup module for reconnect support
    setup_api.set_app_refs(_app_refs)

    # Check if setup has been completed
    db = SessionLocal()
    try:
        row = db.query(StationConfigModel).filter_by(key="setup_complete").first()
        setup_done = row is not None and row.value == "true"
        row_count = db.query(StationConfigModel).count()
        logger.info("Config DB: %d rows, setup_complete=%s",
                     row_count, row.value if row else "NOT FOUND")
    finally:
        db.close()

    if setup_done:
        # Normal startup — connect with DB config (falls back to .env defaults)
        db = SessionLocal()
        try:
            from .api.config import get_effective_config
            cfg = get_effective_config(db)
            port = str(cfg.get("serial_port", settings.serial_port))
            baud = int(cfg.get("baud_rate", settings.baud_rate))
        finally:
            db.close()

        asyncio.create_task(_bg_connect(port, baud))
    else:
        # Try .env defaults in background — if it works, auto-mark setup complete
        logger.info("Setup not yet complete — trying .env defaults...")
        asyncio.create_task(_bg_connect_and_mark_setup(
            settings.serial_port, settings.baud_rate,
        ))

    yield

    # Shutdown: stop poller loop first, then close serial port
    logger.info("Shutting down...")
    poller = _app_refs.get("poller")
    poller_task = _app_refs.get("poller_task")
    driver = _app_refs.get("driver")

    if poller:
        poller.stop()
    if poller_task:
        poller_task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(poller_task), timeout=6.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
    if driver:
        try:
            driver.close()
        except Exception:
            pass
    logger.info("Application shutdown complete")


async def _async_connect(port: str, baud: int):
    """Connect to serial port, detect station, start poller."""
    logger.info(
        "Connecting to serial port %s at %d baud (timeout=%.1fs)",
        port, baud, settings.serial_timeout,
    )
    driver = LinkDriver(port=port, baud_rate=baud, timeout=settings.serial_timeout)
    driver.open()
    logger.info("Serial port %s opened", port)

    logger.info("Detecting station type...")
    station_type = await driver.async_detect_station_type()
    logger.info("Station detected: %s (model code %d)", station_type.name, station_type.value)

    logger.info("Reading calibration offsets...")
    await driver.async_read_calibration()

    # Backfill any archive records missed during downtime
    from .services.archive_sync import async_sync_archive
    try:
        n_synced = await async_sync_archive(driver)
        logger.info("Archive sync: %d new records", n_synced)
    except Exception as e:
        logger.warning("Archive sync failed (continuing): %s", e)

    poller = Poller(driver, poll_interval=settings.poll_interval_sec)
    poller_task = asyncio.create_task(poller.run())
    logger.info("Poller started (%ds interval)", settings.poll_interval_sec)

    _app_refs["driver"] = driver
    _app_refs["poller"] = poller
    _app_refs["poller_task"] = poller_task

    station_api.set_poller(poller, driver)
    weatherlink_api.set_driver(driver)
    ws_set_driver(driver)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Davis Weather Station",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routes
    app.include_router(api_router)

    # WebSocket
    app.websocket("/ws/live")(websocket_endpoint)

    # Custom background images directory (alongside the database)
    bg_dir = Path(settings.db_path).parent / "backgrounds"
    bg_dir.mkdir(parents=True, exist_ok=True)
    backgrounds_api.set_backgrounds_dir(bg_dir)
    app.mount("/backgrounds", StaticFiles(directory=str(bg_dir)), name="backgrounds")

    # Serve frontend static files if built
    frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
    if frontend_dist.exists():
        # Mount hashed assets at /assets for correct MIME types
        assets_dir = frontend_dist / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        # SPA catch-all: serve the file if it exists, otherwise index.html
        index_html = frontend_dist / "index.html"

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            file_path = frontend_dist / full_path
            if file_path.is_file():
                return FileResponse(str(file_path))
            return FileResponse(str(index_html))

    return app


# Application instance
app = create_app()

if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=settings.host, port=settings.port)
