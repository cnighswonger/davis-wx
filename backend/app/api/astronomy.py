"""GET /api/astronomy - Sun and moon data."""

from fastapi import APIRouter

router = APIRouter()

# Will be populated by main.py
_astronomy_service = None


def set_astronomy_service(service):
    global _astronomy_service
    _astronomy_service = service


@router.get("/astronomy")
def get_astronomy():
    """Return sunrise/sunset, twilight, moon phase data."""
    if _astronomy_service is None:
        return {"error": "Astronomy service not configured (set latitude/longitude)"}

    return _astronomy_service.get_current()
