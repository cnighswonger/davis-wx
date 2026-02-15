"""GET/PUT /api/config - Configuration management."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..models.database import get_db
from ..models.station_config import StationConfigModel

router = APIRouter()

# Default config items derived from application settings.
# These are shown when the DB has no saved value for a key.
_DEFAULTS: dict[str, object] = {
    "serial_port": settings.serial_port,
    "baud_rate": settings.baud_rate,
    "poll_interval": settings.poll_interval_sec,
    "latitude": settings.latitude,
    "longitude": settings.longitude,
    "elevation": settings.elevation_ft,
    "temp_unit": settings.units_temp,
    "pressure_unit": settings.units_pressure,
    "wind_unit": settings.units_wind,
    "rain_unit": settings.units_rain,
    "metar_enabled": settings.metar_enabled,
    "metar_station": settings.metar_station_id,
    "nws_enabled": settings.nws_enabled,
}


def _coerce_value(raw: str) -> object:
    """Try to coerce a stored string back to bool/int/float."""
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


class ConfigUpdate(BaseModel):
    key: str
    value: str | int | float | bool


def get_effective_config(db: Session) -> dict[str, object]:
    """Return merged config dict: DB overrides take priority over defaults."""
    saved = {item.key: _coerce_value(item.value) for item in db.query(StationConfigModel).all()}
    return {key: saved.get(key, default) for key, default in _DEFAULTS.items()}


@router.get("/config")
def get_config(db: Session = Depends(get_db)):
    """Return all configuration key-value pairs, with defaults for unsaved keys."""
    saved = {item.key: item.value for item in db.query(StationConfigModel).all()}

    result = []
    for key, default in _DEFAULTS.items():
        if key in saved:
            result.append({"key": key, "value": _coerce_value(saved[key])})
        else:
            result.append({"key": key, "value": default})
    return result


@router.put("/config")
def update_config(updates: list[ConfigUpdate], db: Session = Depends(get_db)):
    """Update one or more configuration values."""
    for update in updates:
        existing = db.query(StationConfigModel).filter_by(key=update.key).first()
        if existing:
            existing.value = str(update.value)
            existing.updated_at = datetime.now(timezone.utc)
        else:
            new_item = StationConfigModel(
                key=update.key,
                value=str(update.value),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(new_item)
    db.commit()
    items = db.query(StationConfigModel).all()
    return [{"key": item.key, "value": item.value} for item in items]
