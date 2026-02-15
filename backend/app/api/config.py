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
    """Return all configuration key-value pairs as a list."""
    items = db.query(StationConfigModel).all()
    return [{"key": item.key, "value": item.value} for item in items]


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
