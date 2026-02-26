"""GET/PUT /api/nowcast — AI nowcast endpoints."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..models.database import get_db
from ..models.nowcast import NowcastHistory, NowcastKnowledge
from ..services.nowcast_service import nowcast_service

router = APIRouter()


@router.get("/nowcast")
def get_nowcast(db: Session = Depends(get_db)):
    """Return the latest nowcast, or null if none available."""
    # Try in-memory cache first (fastest).
    cached = nowcast_service.get_latest()
    if cached is not None:
        return cached

    # Fall back to database.
    record = (
        db.query(NowcastHistory)
        .order_by(NowcastHistory.created_at.desc())
        .first()
    )
    if record is None:
        return None

    return _history_to_dict(record)


@router.get("/nowcast/history")
def get_nowcast_history(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """Return recent nowcasts, newest first."""
    records = (
        db.query(NowcastHistory)
        .order_by(NowcastHistory.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_history_to_dict(r) for r in records]


@router.get("/nowcast/knowledge")
def get_knowledge(
    status: str | None = None,
    db: Session = Depends(get_db),
):
    """Return knowledge base entries, optionally filtered by status."""
    query = db.query(NowcastKnowledge).order_by(NowcastKnowledge.created_at.desc())
    if status:
        query = query.filter(NowcastKnowledge.status == status)
    entries = query.limit(100).all()
    return [_knowledge_to_dict(e) for e in entries]


class KnowledgeUpdate(BaseModel):
    status: str  # "accepted" or "rejected"


@router.put("/nowcast/knowledge/{entry_id}")
def update_knowledge(
    entry_id: int,
    update: KnowledgeUpdate,
    db: Session = Depends(get_db),
):
    """Approve or reject a knowledge base entry."""
    if update.status not in ("accepted", "rejected"):
        raise HTTPException(status_code=400, detail="Status must be 'accepted' or 'rejected'")

    entry = db.query(NowcastKnowledge).filter_by(id=entry_id).first()
    if entry is None:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")

    entry.status = update.status
    entry.reviewed_at = datetime.now(timezone.utc)
    db.commit()

    return _knowledge_to_dict(entry)


def _history_to_dict(record: NowcastHistory) -> dict:
    """Convert a NowcastHistory ORM object to an API response dict."""
    try:
        elements = json.loads(record.details)
    except (json.JSONDecodeError, TypeError):
        elements = {}

    try:
        sources = json.loads(record.sources_used)
    except (json.JSONDecodeError, TypeError):
        sources = []

    return {
        "id": record.id,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "valid_from": record.valid_from.isoformat() if record.valid_from else None,
        "valid_until": record.valid_until.isoformat() if record.valid_until else None,
        "model_used": record.model_used,
        "summary": record.summary,
        "elements": elements,
        "farming_impact": elements.get("farming_impact") if isinstance(elements, dict) else None,
        "current_vs_model": record.raw_response[:200] if not elements else "",
        "data_quality": "",
        "sources_used": sources,
        "input_tokens": record.input_tokens or 0,
        "output_tokens": record.output_tokens or 0,
    }


def _knowledge_to_dict(entry: NowcastKnowledge) -> dict:
    """Convert a NowcastKnowledge ORM object to an API response dict."""
    return {
        "id": entry.id,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "source": entry.source,
        "category": entry.category,
        "content": entry.content,
        "status": entry.status,
        "auto_accept_at": entry.auto_accept_at.isoformat() if entry.auto_accept_at else None,
        "reviewed_at": entry.reviewed_at.isoformat() if entry.reviewed_at else None,
    }
