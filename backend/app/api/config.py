"""GET/PUT /api/config - Configuration management."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..models.database import get_db
from ..models.station_config import StationConfigModel

router = APIRouter()


class ConfigUpdate(BaseModel):
    key: str
    value: str


@router.get("/config")
def get_config(db: Session = Depends(get_db)):
    """Return all configuration key-value pairs."""
    items = db.query(StationConfigModel).all()
    return {
        "items": [{"key": item.key, "value": item.value} for item in items]
    }


@router.put("/config")
def update_config(update: ConfigUpdate, db: Session = Depends(get_db)):
    """Update a configuration value."""
    existing = db.query(StationConfigModel).filter_by(key=update.key).first()
    if existing:
        existing.value = update.value
        existing.updated_at = datetime.now(timezone.utc)
    else:
        new_item = StationConfigModel(
            key=update.key,
            value=update.value,
            updated_at=datetime.now(timezone.utc),
        )
        db.add(new_item)
    db.commit()
    return {"key": update.key, "value": update.value}
