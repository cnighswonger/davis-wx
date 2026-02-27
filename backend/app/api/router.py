"""Top-level API router aggregation."""

from fastapi import APIRouter

from . import current, history, export, config, station, forecast, astronomy, output, setup, weatherlink, backgrounds, nowcast, spray, usage, db_admin

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
api_router.include_router(nowcast.router)
api_router.include_router(spray.router)
api_router.include_router(usage.router)
api_router.include_router(db_admin.router)
