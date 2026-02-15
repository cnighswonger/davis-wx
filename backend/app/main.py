"""FastAPI application factory and lifespan for Davis Weather Station."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .models.database import init_database
from .protocol.link_driver import LinkDriver
from .services.poller import Poller
from .api.router import api_router
from .api import station as station_api
from .ws.handler import websocket_endpoint

logger = logging.getLogger(__name__)

# Global references for cleanup
_poller: Poller | None = None
_poller_task: asyncio.Task | None = None
_driver: LinkDriver | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: start/stop serial polling and services."""
    global _poller, _poller_task, _driver

    # Initialize database
    init_database()
    logger.info("Database initialized")

    # Try to connect to serial port
    try:
        _driver = LinkDriver(
            port=settings.serial_port,
            baud_rate=settings.baud_rate,
            timeout=settings.serial_timeout,
        )
        _driver.open()

        # Detect station type
        station_type = await _driver.async_detect_station_type()
        logger.info("Connected to %s", station_type.name)

        # Read calibration
        await _driver.async_read_calibration()

        # Start poller
        _poller = Poller(_driver, poll_interval=settings.poll_interval_sec)
        _poller_task = asyncio.create_task(_poller.run())

        # Set references for API endpoints
        station_api.set_poller(_poller, _driver)

    except Exception as e:
        logger.warning("Could not connect to serial port: %s", e)
        logger.info("Running in demo mode (no serial connection)")

    yield

    # Shutdown: stop poller loop first, then close serial port
    if _poller:
        _poller.stop()
    if _poller_task:
        _poller_task.cancel()
        try:
            await _poller_task
        except (asyncio.CancelledError, Exception):
            pass
    # Only close serial after poller is fully stopped
    if _driver:
        try:
            _driver.close()
        except Exception:
            pass
    logger.info("Application shutdown complete")


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

    # Serve frontend static files if built
    frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


# Application instance
app = create_app()

if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=settings.host, port=settings.port)
