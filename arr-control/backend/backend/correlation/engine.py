"""Correlation engine for matching events across services."""
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from backend.adapters.base import RawEvent, SourceService, MediaType, EventType

logger = logging.getLogger("arr-control.correlation")


class CorrelationResult:
    """Result of correlating events into a media item timeline."""
    
    def __init__(self, correlation_key: str, events: List[RawEvent]):
        self.correlation_key = correlation_key
        self.events = sorted(events, key=lambda e: e.timestamp)
        self.media_type = events[0].media_type if events else MediaType.MOVIE
        self.media_identifier = events[0].media_identifier if events else ""
        self.title = events[0].title if events else "Unknown"
        self.season = events[0].season if events else None
        self.episode = events[0].episode if events else None
        self.tvdb_id = events[0].tvdb_id if events else None
        self.tmdb_id = events[0].tmdb_id if events else None
        self.imdb_id = events[0].imdb_id if events else None
        self.current_state = self._determine_current_state()
        self.progress = self._determine_progress()
        self.current_service = self._determine_current_service()
        self.last_event = self.events[-1] if self.events else None
        self.next_expected_state = self._determine_next_expected()
    
    def _determine_current_state(self) -> EventType:
        """Determine current state from most recent event using StateMachine."""
        if not self.events:
            return EventType.UNKNOWN
        
        # Use StateMachine for proper state classification including stuck detection
        from backend.correlation.state_machine import StateMachine
        state, _ = StateMachine.classify_state(self.events)
        return state
    
    def _determine_progress(self) -> Optional[int]:
        """Determine progress from events."""
        for event in reversed(self.events):
            if event.normalized_metadata and "progress" in event.normalized_metadata:
                return event.normalized_metadata["progress"]
        return None
    
    def _determine_current_service(self) -> Optional[SourceService]:
        """Determine current service handling the item."""
        if not self.events:
            return None
        return self.events[-1].source_service
    
    def _determine_next_expected(self) -> Optional[EventType]:
        """Determine next expected state based on current state."""
        state = self.current_state
        
        transitions = {
            EventType.WANTED: EventType.RELEASE_GRABBED,
            EventType.RELEASE_GRABBED: EventType.DOWNLOAD_STARTED,
            EventType.DOWNLOAD_STARTED: EventType.DOWNLOAD_PROGRESS,
            EventType.DOWNLOAD_PROGRESS: EventType.DOWNLOAD_COMPLETED,
            EventType.DOWNLOAD_COMPLETED: EventType.IMPORT_STARTED,
            EventType.IMPORT_STARTED: EventType.IMPORT_COMPLETED,
            EventType.IMPORT_COMPLETED: EventType.AVAILABLE,
            EventType.DOWNLOAD_FAILED: EventType.WANTED,
            EventType.IMPORT_FAILED: EventType.WANTED,
        }
        
        return transitions.get(state)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "correlation_key": self.correlation_key,
            "media_type": self.media_type.value if self.media_type else None,
            "media_identifier": self.media_identifier,
            "title": self.title,
            "season": self.season,
            "episode": self.episode,
            "tvdb_id": self.tvdb_id,
            "tmdb_id": self.tmdb_id,
            "imdb_id": self.imdb_id,
            "current_state": self.current_state.value,
            "progress": self.progress,
            "current_service": self.current_service.value if self.current_service else None,
            "last_event_at": self.last_event.timestamp.isoformat() if self.last_event else None,
            "next_expected_state": self.next_expected_state.value if self.next_expected_state else None,
            "event_count": len(self.events),
            "timeline": [
                {
                    "timestamp": e.timestamp.isoformat(),
                    "source": e.source_service.value,
                    "event_type": e.event_type.value,
                    "status": e.status.value,
                    "error_message": e.error_message,
                    "normalized_metadata": e.normalized_metadata,
                }
                for e in self.events
            ]
        }


class CorrelationEngine:
    """Engine for correlating events across services."""
    
    def __init__(self):
        self.items: Dict[str, CorrelationResult] = {}
    
    def add_events(self, events: List[RawEvent]) -> List[CorrelationResult]:
        """Add events and update correlation results.
        
        Handles:
        - Duplicate events (idempotent by correlation key + event type)
        - Out-of-order events (sorted by timestamp)
        - Missing events (tolerated)
        - Multiple downloads (tracked per item)
        """
        updated = []
        
        # Group events by correlation key (using media_identifier as primary)
        grouped: Dict[str, List[RawEvent]] = {}
        for event in events:
            key = self._compute_correlation_key(event)
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(event)
        
        # Update each group
        for key, group_events in grouped.items():
            if key in self.items:
                # Merge with existing events - dedup by event_type + source_service + timestamp
                existing = set(
                    e.event_type.value + e.source_service.value + str(e.timestamp)
                    for e in self.items[key].events
                )
                new_events = [
                    e for e in group_events
                    if e.event_type.value + e.source_service.value + str(e.timestamp) not in existing
                ]
                if new_events:
                    self.items[key].events.extend(new_events)
                    self.items[key].events.sort(key=lambda e: e.timestamp)
                    updated.append(self.items[key])
            else:
                # Create new item
                result = CorrelationResult(key, group_events)
                self.items[key] = result
                updated.append(result)
        
        return updated
    
    def get_item(self, correlation_key: str) -> Optional[CorrelationResult]:
        """Get a correlated item by key."""
        return self.items.get(correlation_key)
    
    def get_all_items(self) -> List[CorrelationResult]:
        """Get all correlated items."""
        return list(self.items.values())
    
    def get_active_items(self) -> List[CorrelationResult]:
        """Get items that are still in progress."""
        active_states = {
            EventType.WANTED,
            EventType.SEARCH_STARTED,
            EventType.RELEASE_GRABBED,
            EventType.DOWNLOAD_STARTED,
            EventType.DOWNLOAD_PROGRESS,
            EventType.IMPORT_STARTED,
            EventType.STUCK,
        }
        return [item for item in self.items.values() if item.current_state in active_states]
    
    def get_failed_items(self) -> List[CorrelationResult]:
        """Get items that have failed."""
        failed_states = {
            EventType.DOWNLOAD_FAILED,
            EventType.IMPORT_FAILED,
            EventType.SEARCH_FAILED,
        }
        return [item for item in self.items.values() if item.current_state in failed_states]
    
    def get_completed_items(self) -> List[CorrelationResult]:
        """Get items that have completed successfully."""
        return [item for item in self.items.values() if item.current_state == EventType.AVAILABLE]
    
    def get_items_by_state(self, state: EventType) -> List[CorrelationResult]:
        """Get items in a specific state."""
        return [item for item in self.items.values() if item.current_state == state]
    
    def _compute_correlation_key(self, event: RawEvent) -> str:
        """Compute correlation key from event data.
        
        Uses deterministic identifiers (TVDB/TMDB/IMDB) as primary keys
        to group all events for the same media item across all sources.
        Normalizes all external IDs to a consistent 'media:{id}' format.
        """
        # Priority order for correlation keys:
        # 1. TVDB/TMDB/IMDB-based (primary - groups all events for same media)
        # All normalized to 'media:{id}' format for cross-service correlation
        if event.tmdb_id:
            return f"media:{event.tmdb_id}"
        
        if event.tvdb_id:
            key = f"media:{event.tvdb_id}"
            if event.season is not None and event.episode is not None:
                key += f":S{event.season:02d}E{event.episode:02d}"
            return key
        
        if event.imdb_id:
            return f"media:{event.imdb_id}"
        
        # 2. Use media_identifier as fallback for cross-service correlation
        if event.media_identifier:
            return f"media:{event.media_identifier}"
        
        # 3. Explicit correlation key (fallback)
        if event.correlation_key:
            return event.correlation_key
        
        # 4. Hash-based (qBittorrent)
        if event.source_download_id:
            return f"hash:{event.source_download_id}"
        
        # 5. Title-based fallback
        return f"title:{event.media_identifier}:{event.title}"
    
    def explain(self, correlation_key: str) -> Optional[Dict[str, Any]]:
        """Generate human-readable explanation for an item's state."""
        item = self.items.get(correlation_key)
        if not item:
            return None
        
        explanation = {
            "correlation_key": correlation_key,
            "current_state": item.current_state.value,
            "reason": self._generate_reason(item),
            "evidence": self._generate_evidence(item),
            "timeline_summary": self._generate_timeline_summary(item),
        }
        
        return explanation
    
    def _generate_reason(self, item: CorrelationResult) -> str:
        """Generate reason for current state."""
        state = item.current_state
        
        if state == EventType.AVAILABLE:
            return "Import completed successfully. Media is available in library."
        elif state == EventType.DOWNLOAD_FAILED:
            return f"Download failed. Last error: {item.last_event.error_message or 'Unknown error'}."
        elif state == EventType.IMPORT_FAILED:
            return f"Import failed. Last error: {item.last_event.error_message or 'Unknown error'}."
        elif state == EventType.STUCK:
            return "Item appears to be stuck. No progress detected."
        elif state == EventType.UNKNOWN:
            return "Unable to determine current state."
        elif state == EventType.DOWNLOAD_PROGRESS:
            progress = item.progress or 0
            return f"Downloading at {progress}% progress."
        elif state == EventType.SEARCH_STARTED:
            return "Searching for available releases."
        elif state == EventType.RELEASE_GRABBED:
            return "Release grabbed, waiting for download."
        else:
            return f"Item is in state: {state.value}."
    
    def _generate_evidence(self, item: CorrelationResult) -> List[str]:
        """Generate evidence for current state."""
        evidence = []
        
        if item.last_event and item.last_event.error_message:
            evidence.append(f"Error: {item.last_event.error_message}")
        
        if item.last_event:
            evidence.append(f"Last event: {item.last_event.event_type.value} from {item.last_event.source_service.value}")
        
        for event in item.events[-3:]:
            evidence.append(f"{event.timestamp.strftime('%H:%M')} - {event.event_type.value} via {event.source_service.value}")
        
        return evidence
    
    def _generate_timeline_summary(self, item: CorrelationResult) -> str:
        """Generate a text summary of the timeline."""
        lines = []
        for event in item.events:
            lines.append(f"{event.timestamp.strftime('%H:%M')} {event.event_type.value}")
        return "\n".join(lines) if lines else "No events recorded"


# Global correlation engine instance
_engine: Optional[CorrelationEngine] = None


def get_correlation_engine() -> CorrelationEngine:
    """Get or create the global correlation engine."""
    global _engine
    if _engine is None:
        _engine = CorrelationEngine()
    return _engine