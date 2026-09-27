"""Items API endpoints."""
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database.base import get_db
from backend.services.events import EventService
from backend.correlation.engine import CorrelationResult

logger = logging.getLogger("arr-control.api.items")

router = APIRouter(prefix="/api/items", tags=["items"])


@router.get("", response_model=List[dict], summary="List all media items")
def list_items(
    db: Session = Depends(get_db),
    state: Optional[str] = Query(None, description="Filter by current state"),
    media_type: Optional[str] = Query(None, description="Filter by media type (movie, episode)"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("last_event", description="Sort by: last_event, title, state"),
    sort_order: str = Query("desc", description="Sort order: asc, desc")
):
    """List all correlated media items with their current state."""
    event_service = EventService(db)
    items = event_service.get_items()
    
    # Apply filters
    if state:
        items = [i for i in items if i.current_state.value == state]
    
    if media_type:
        items = [i for i in items if i.media_type.value == media_type]
    
    # Apply sorting
    reverse = sort_order.lower() == "desc"
    if sort_by == "last_event":
        items.sort(key=lambda x: x.last_event.timestamp if x.last_event else x.first_seen_at, reverse=reverse)
    elif sort_by == "title":
        items.sort(key=lambda x: x.title.lower(), reverse=reverse)
    elif sort_by == "state":
        items.sort(key=lambda x: x.current_state.value, reverse=reverse)
    
    # Apply pagination
    total = len(items)
    items = items[offset:offset + limit]
    
    return [
        {
            "id": item.correlation_key,
            "media_type": item.media_type.value,
            "title": item.title,
            "season": item.season,
            "episode": item.episode,
            "tvdb_id": item.tvdb_id,
            "tmdb_id": item.tmdb_id,
            "imdb_id": item.imdb_id,
            "current_state": item.current_state.value,
            "progress": item.progress,
            "current_service": item.current_service.value if item.current_service else None,
            "last_event_at": item.last_event.timestamp.isoformat() if item.last_event else None,
            "next_expected_state": item.next_expected_state.value if item.next_expected_state else None,
            "event_count": item.event_count,
            "first_seen_at": item.events[0].timestamp.isoformat() if item.events else None,
        }
        for item in items
    ]


@router.get("/{item_id}", response_model=dict, summary="Get media item detail")
def get_item(item_id: str, db: Session = Depends(get_db)):
    """Get detailed information about a media item including its timeline."""
    event_service = EventService(db)
    item = event_service.get_item(item_id)
    
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    return item.to_dict()


@router.get("/{item_id}/timeline", response_model=List[dict], summary="Get item timeline")
def get_item_timeline(item_id: str, db: Session = Depends(get_db)):
    """Get the timeline of events for a specific item."""
    event_service = EventService(db)
    timeline = event_service.get_timeline(item_id)
    
    if not timeline:
        raise HTTPException(status_code=404, detail="No timeline found for item")
    
    return timeline


@router.get("/{item_id}/explain", response_model=dict, summary="Get item explanation")
def get_item_explanation(item_id: str, db: Session = Depends(get_db)):
    """Get human-readable explanation for item's current state."""
    event_service = EventService(db)
    explanation = event_service.get_explanation(item_id)
    
    if not explanation:
        raise HTTPException(status_code=404, detail="No explanation found for item")
    
    return explanation


@router.get("/orphans", response_model=List[dict], summary="Get unmatched/orphan torrents")
def get_orphan_torrents(db: Session = Depends(get_db)):
    """Get qBittorrent torrents that could not be correlated to any media item."""
    event_service = EventService(db)
    orphans = event_service.get_orphan_torrents()
    return orphans