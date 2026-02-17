"""FastAPI application factory and lifespan for Davis Weather Station.

The web application reads sensor data from SQLite and proxies hardware
commands to the logger daemon via IPC.  All serial/polling logic lives
in logger_main.py.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from .config import settings
from .models.database import init_database
from .ipc.client import IPCClient
from .ipc.dependencies import set_ipc_client
from .api.router import api_router
from .api import backgrounds as backgrounds_api
from .ws.handler import websocket_endpoint

# Configure logging for our app (uvicorn only configures its own loggers)
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:     %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: database init and IPC client setup."""

    # Initialize database (creates tables, enables WAL)
    logger.info("Database: %s", settings.db_path)
    init_database()
    logger.info("Database initialised")

    # Create IPC client for talking to the logger daemon
    client = IPCClient(settings.ipc_port)
    set_ipc_client(client)

    try:
        available = await client.is_available()
        if available:
            logger.info("Logger daemon connected via IPC (port %d)", settings.ipc_port)
        else:
            logger.warning(
                "Logger daemon not available on port %d — running in degraded mode",
                settings.ipc_port,
            )
    except Exception:
        logger.warning("Logger daemon not reachable — running in degraded mode")

    yield

    await client.close()
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
