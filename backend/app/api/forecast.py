"""GET /api/forecast - Blended Zambretti + NWS forecast."""

from fastapi import APIRouter

router = APIRouter()

# Will be populated by main.py
_forecast_blender = None


def set_forecast_blender(blender):
    global _forecast_blender
    _forecast_blender = blender


@router.get("/forecast")
async def get_forecast():
    """Return blended forecast from local Zambretti and optional NWS."""
    if _forecast_blender is None:
        return {"local": None, "nws": None}

    return await _forecast_blender.get_blended_forecast()
