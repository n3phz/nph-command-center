"""Activity/History API endpoints."""
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from datetime import datetime, timedelta

from backend.database.base import get_db
from backend.models import RawEventModel, EventType as DBEventType, SourceService as DBSourceService, MediaType as DBMediaType
from backend.adapters.base import SourceService, EventType

logger = logging.getLogger("arr-control.api.activity")

router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("", response_model=List[dict], summary="List activity events with filters")
def list_activity(
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    source_service: Optional[str] = Query(None, description="Filter by source service"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    media_type: Optional[str] = Query(None, description="Filter by media type"),
    status: Optional[str] = Query(None, description="Filter by status"),
    days: int = Query(7, ge=1, le=365, description="Days of history to include"),
    search: Optional[str] = Query(None, description="Search in title"),
    stuck_only: bool = Query(False, description="Show only stuck items"),
    failed_only: bool = Query(False, description="Show only failed items"),
    unmatched_only: bool = Query(False, description="Show only unmatched torrents"),
):
    """List activity events with filtering and pagination."""
    query = db.query(RawEventModel)

    # Time filter
    since = datetime.utcnow() - timedelta(days=days)
    query = query.filter(RawEventModel.timestamp >= since)

    # Source service filter
    if source_service:
        try:
            query = query.filter(RawEventModel.source_service == DBSourceService(source_service))
        except ValueError:
            pass

    # Event type filter
    if event_type:
        try:
            query = query.filter(RawEventModel.event_type == DBEventType(event_type))
        except ValueError:
            pass

    # Media type filter
    if media_type:
        try:
            query = query.filter(RawEventModel.media_type == DBMediaType(media_type))
        except ValueError:
            pass

    # Status filter
    if status:
        from backend.models import EventStatus as DBEventStatus
        try:
            query = query.filter(RawEventModel.status == DBEventStatus(status))
        except ValueError:
            pass

    # Stuck filter
    if stuck_only:
        query = query.filter(RawEventModel.event_type == DBEventType.STUCK)

    # Failed filter
    if failed_only:
        from backend.models import EventStatus as DBEventStatus
        query = query.filter(RawEventModel.status == DBEventStatus.FAILED)

    # Unmatched filter (qBittorrent events without *Arr correlation)
    if unmatched_only:
        query = query.filter(
            RawEventModel.source_service == DBSourceService.QBITTORRENT,
            ~RawEventModel.correlation_key.like("media:%")
        )

    # Search filter
    if search:
        query = query.filter(RawEventModel.title.ilike(f"%{search}%"))

    # Order and paginate
    query = query.order_by(desc(RawEventModel.timestamp))
    query = query.offset(offset).limit(limit)

    events = query.all()

    return [
        {
            "id": e.id,
            "timestamp": e.timestamp.isoformat(),
            "source_service": e.source_service.value,
            "event_type": e.event_type.value,
            "media_type": e.media_type.value,
            "title": e.title,
            "season": e.season,
            "episode": e.episode,
            "correlation_key": e.correlation_key,
            "status": e.status.value,
            "error_message": e.error_message,
            "normalized_metadata": e.normalized_metadata,
        }
        for e in events
    ]


@router.get("/stats", response_model=dict, summary="Get activity statistics")
def get_activity_stats(
    db: Session = Depends(get_db),
    days: int = Query(7, ge=1, le=365, description="Days of history"),
):
    """Get activity statistics for dashboard."""
    since = datetime.utcnow() - timedelta(days=days)

    # Total events by source
    source_stats = db.query(
        RawEventModel.source_service,
        func.count(RawEventModel.id)
    ).filter(RawEventModel.timestamp >= since).group_by(RawEventModel.source_service).all()

    # Total events by type
    type_stats = db.query(
        RawEventModel.event_type,
        func.count(RawEventModel.id)
    ).filter(RawEventModel.timestamp >= since).group_by(RawEventModel.event_type).all()

    # Failed events
    failed_count = db.query(func.count(RawEventModel.id)).filter(
        RawEventModel.timestamp >= since,
        RawEventModel.status == "failed"
    ).scalar() or 0

    # Stuck events
    stuck_count = db.query(func.count(RawEventModel.id)).filter(
        RawEventModel.timestamp >= since,
        RawEventModel.event_type == "stuck"
    ).scalar() or 0

    # Events today
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = db.query(func.count(RawEventModel.id)).filter(
        RawEventModel.timestamp >= today_start
    ).scalar() or 0

    return {
        "period_days": days,
        "by_source": {s.value: c for s, c in source_stats},
        "by_type": {t.value: c for t, c in type_stats},
        "failed": failed_count,
        "stuck": stuck_count,
        "today": today_count,
        "total": sum(c for _, c in source_stats),
    }


@router.get("/failures", response_model=List[dict], summary="Get failures for attention view")
def get_failures(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    days: int = Query(30, ge=1, le=365),
):
    """Get failure events for attention/analysis."""
    since = datetime.utcnow() - timedelta(days=days)

    from backend.models import EventStatus as DBEventStatus
    events = db.query(RawEventModel).filter(
        RawEventModel.timestamp >= since,
        RawEventModel.status == DBEventStatus.FAILED
    ).order_by(desc(RawEventModel.timestamp)).limit(limit).all()

    return [
        {
            "id": e.id,
            "timestamp": e.timestamp.isoformat(),
            "source_service": e.source_service.value,
            "event_type": e.event_type.value,
            "media_type": e.media_type.value,
            "title": e.title,
            "season": e.season,
            "episode": e.episode,
            "correlation_key": e.correlation_key,
            "error_message": e.error_message,
            "normalized_metadata": e.normalized_metadata,
        }
        for e in events
    ]


@router.get("/stalled", response_model=List[dict], summary="Get stalled downloads")
def get_stalled_downloads(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    days: int = Query(7, ge=1, le=365),
):
    """Get stalled download events."""
    since = datetime.utcnow() - timedelta(days=days)

    events = db.query(RawEventModel).filter(
        RawEventModel.timestamp >= since,
        RawEventModel.event_type == DBEventType.STUCK
    ).order_by(desc(RawEventModel.timestamp)).limit(limit).all()

    return [
        {
            "id": e.id,
            "timestamp": e.timestamp.isoformat(),
            "source_service": e.source_service.value,
            "event_type": e.event_type.value,
            "media_type": e.media_type.value,
            "title": e.title,
            "season": e.season,
            "episode": e.episode,
            "correlation_key": e.correlation_key,
            "progress": e.normalized_metadata.get("progress") if e.normalized_metadata else None,
            "normalized_metadata": e.normalized_metadata,
        }
        for e in events
    ]