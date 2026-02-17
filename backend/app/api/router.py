"""Top-level API router aggregation."""

from fastapi import APIRouter

from . import current, history, export, config, station, forecast, astronomy, output, setup, weatherlink, backgrounds

api_router = APIRouter(prefix="/api")

api_router.include_router(current.router)
api_router.include_router(history.router)
api_router.include_router(export.router)
api_router.include_router(config.router)
api_router.include_router(station.router)
api_router.include_router(forecast.router)
api_router.include_router(astronomy.router)
api_router.include_router(output.router)
api_router.include_router(setup.router)
api_router.include_router(weatherlink.router)
api_router.include_router(backgrounds.router)
