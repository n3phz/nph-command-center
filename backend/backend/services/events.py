"""Event service for processing and storing events."""
import json
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from backend.adapters.base import RawEvent, SourceService
from backend.models import RawEventModel, MediaItemModel, EventType as DBEventType, EventStatus as DBEventStatus, MediaType as DBMediaType, SourceService as DBSourceService
from backend.correlation.engine import get_correlation_engine, CorrelationResult

logger = logging.getLogger("arr-control.services.events")


class EventService:
    """Service for processing and storing events."""
    
    def __init__(self, db: Session):
        self.db = db
        self.correlation_engine = get_correlation_engine()
    
    def ingest_event(self, event: RawEvent) -> RawEventModel:
        """Ingest a single event into the database."""
        # Check for duplicate
        existing = self._find_duplicate(event)
        if existing:
            logger.debug(f"Duplicate event detected: {event.correlation_key} at {event.timestamp}")
            return existing
        
        # Create database record
        db_event = RawEventModel(
            timestamp=event.timestamp,
            source_service=DBSourceService(event.source_service.value),
            event_type=DBEventType(event.event_type.value),
            media_type=DBMediaType(event.media_type.value),
            media_identifier=event.media_identifier,
            title=event.title,
            season=event.season,
            episode=event.episode,
            tvdb_id=event.tvdb_id,
            tmdb_id=event.tmdb_id,
            imdb_id=event.imdb_id,
            source_item_id=event.source_item_id,
            source_download_id=event.source_download_id,
            source_queue_id=event.source_queue_id,
            correlation_key=event.correlation_key,
            source_payload=json.dumps(event.source_payload) if event.source_payload else None,
            normalized_metadata=json.dumps(event.normalized_metadata) if event.normalized_metadata else None,
            status=DBEventStatus(event.status.value),
            error_message=event.error_message,
            error_details=event.error_details,
            processed=0
        )
        
        self.db.add(db_event)
        self.db.commit()
        self.db.refresh(db_event)
        
        # Update correlation engine
        self.correlation_engine.add_events([event])
        
        return db_event
    
    def ingest_events(self, events: List[RawEvent]) -> List[RawEventModel]:
        """Ingest multiple events."""
        results = []
        for event in events:
            try:
                result = self.ingest_event(event)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to ingest event: {e}")
        return results
    
    def process_pending_events(self) -> int:
        """Process all unprocessed events and update media items."""
        pending = self.db.query(RawEventModel).filter(RawEventModel.processed == 0).all()
        
        if not pending:
            return 0
        
        # Convert to RawEvent objects
        events = []
        for model_event in pending:
            payload = json.loads(model_event.source_payload) if model_event.source_payload else None
            metadata = json.loads(model_event.normalized_metadata) if model_event.normalized_metadata else None
            
            event = RawEvent(
                timestamp=model_event.timestamp,
                source_service=SourceService(model_event.source_service.value),
                event_type=DBEventType(model_event.event_type.value),
                media_type=DBMediaType(model_event.media_type.value),
                media_identifier=model_event.media_identifier,
                title=model_event.title,
                season=model_event.season,
                episode=model_event.episode,
                tvdb_id=model_event.tvdb_id,
                tmdb_id=model_event.tmdb_id,
                imdb_id=model_event.imdb_id,
                source_item_id=model_event.source_item_id,
                source_download_id=model_event.source_download_id,
                source_queue_id=model_event.source_queue_id,
                correlation_key=model_event.correlation_key,
                source_payload=payload,
                normalized_metadata=metadata,
                status=DBEventStatus(model_event.status.value),
                error_message=model_event.error_message,
                error_details=model_event.error_details
            )
            events.append(event)
        
        # Update correlation engine
        self.correlation_engine.add_events(events)
        
        # Mark as processed
        for model_event in pending:
            model_event.processed = 1
            model_event.processed_at = datetime.utcnow()
        
        self.db.commit()
        
        return len(events)
    
    def get_items(self) -> List[CorrelationResult]:
        """Get all correlated media items."""
        return self.correlation_engine.get_all_items()
    
    def get_orphan_torrents(self) -> List[Dict[str, Any]]:
        """Get qBittorrent torrents that could not be correlated to any media item."""
        items = self.correlation_engine.get_all_items()
        
        # Collect all hashes that were successfully correlated
        correlated_hashes = set()
        for item in items:
            for attempt in getattr(item, 'download_attempts', []):
                correlated_hashes.add(attempt.get('hash', '').upper())
        
        # Get all qBittorrent events from the engine
        all_events = []
        for item in items:
            all_events.extend(item.events)
        
        # Find qBittorrent events with hashes not in correlated_hashes
        orphan_events = []
        for event in all_events:
            if event.source_service == SourceService.QBITTORRENT and event.source_download_id:
                hash_key = event.source_download_id.upper()
                if hash_key not in correlated_hashes:
                    orphan_events.append(event)
        
        # Group by hash
        orphans = {}
        for event in orphan_events:
            hash_key = event.source_download_id.upper()
            if hash_key not in orphans:
                orphans[hash_key] = {
                    "hash": hash_key,
                    "title": event.title,
                    "category": event.normalized_metadata.get("category", "") if event.normalized_metadata else "",
                    "tags": event.normalized_metadata.get("tags", "") if event.normalized_metadata else "",
                    "state": event.event_type.value,
                    "progress": event.normalized_metadata.get("progress", 0) if event.normalized_metadata else 0,
                    "save_path": event.normalized_metadata.get("save_path", "") if event.normalized_metadata else "",
                    "reason": "no_matching_arr_history",
                }
        
        return list(orphans.values())
    
    def get_all_items(self) -> List[CorrelationResult]:
        """Get all correlated media items."""
        return self.correlation_engine.get_all_items()
    
    def get_item(self, correlation_key: str) -> Optional[CorrelationResult]:
        """Get a specific media item."""
        return self.correlation_engine.get_item(correlation_key)
    
    def get_timeline(self, correlation_key: str) -> List[dict]:
        """Get the timeline for a specific item."""
        item = self.correlation_engine.get_item(correlation_key)
        if not item:
            return []
        return item.to_dict().get("timeline", [])
    
    def get_explanation(self, correlation_key: str) -> Optional[dict]:
        """Get a human-readable explanation for an item's state."""
        return self.correlation_engine.explain(correlation_key)
    
    def _find_duplicate(self, event: RawEvent) -> Optional[RawEventModel]:
        """Check if event is a duplicate."""
        if not event.correlation_key:
            return None
        
        five_minutes_ago = datetime.utcnow() - timedelta(minutes=5)
        
        existing = self.db.query(RawEventModel).filter(
            RawEventModel.correlation_key == event.correlation_key,
            RawEventModel.event_type == DBEventType(event.event_type.value),
            RawEventModel.source_service == DBSourceService(event.source_service.value),
            RawEventModel.timestamp > five_minutes_ago
        ).first()
        
        return existing
    
    def get_events(self, limit: int = 100, offset: int = 0, 
                   source_service: Optional[SourceService] = None,
                   event_type: Optional[DBEventType] = None) -> List[dict]:
        """Get events with filtering and pagination."""
        query = self.db.query(RawEventModel)
        
        if source_service:
            query = query.filter(RawEventModel.source_service == DBSourceService(source_service.value))
        
        if event_type:
            query = query.filter(RawEventModel.event_type == event_type)
        
        query = query.order_by(RawEventModel.timestamp.desc())
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
                "error_message": e.error_message
            }
            for e in events
        ]