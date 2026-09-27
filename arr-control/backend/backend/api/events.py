"""Events API endpoints."""
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.database.base import get_db
from backend.services.events import EventService
from backend.adapters.base import SourceService, EventType

logger = logging.getLogger("arr-control.api.events")

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("", response_model=List[dict], summary="List events")
def list_events(
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    source_service: Optional[str] = Query(None, description="Filter by source service"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    media_type: Optional[str] = Query(None, description="Filter by media type"),
):
    """List events with filtering and pagination."""
    event_service = EventService(db)
    
    source = SourceService(source_service) if source_service else None
    etype = EventType(event_type) if event_type else None
    
    return event_service.get_events(
        limit=limit,
        offset=offset,
        source_service=source,
        event_type=etype
    )