"""Correlation engine for matching events across services."""
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from backend.adapters.base import RawEvent, SourceService, MediaType, EventType
from backend.correlation.matching import _titles_overlap

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
        self.confidence = self._determine_confidence()
        self.download_attempts = self._determine_download_attempts()
    
    def _determine_current_state(self) -> EventType:
        """Determine current state from most recent event using StateMachine."""
        if not self.events:
            return EventType.UNKNOWN
        
        # Use StateMachine for proper state classification including stuck detection
        from backend.correlation.state_machine import StateMachine
        state, _ = StateMachine.classify_state(self.events)
        return state
    
    def _determine_confidence(self) -> str:
        """Determine correlation confidence.
        
        HIGH: exact hash match between *Arr (source_download_id) and qBittorrent (hash)
        MEDIUM: has category/tag correlation AND at least one *Arr event (but no hash match)
        LOW: only qBittorrent events (no *Arr events), or only heuristic
        """
        # Check for exact hash match between *Arr and qBittorrent
        arr_hashes = set()
        qbit_hashes = set()
        has_arr_event = False
        
        for e in self.events:
            if e.source_service in (SourceService.SONARR, SourceService.RADARR):
                has_arr_event = True
                if e.source_download_id:
                    arr_hashes.add(e.source_download_id.upper())
            elif e.source_service == SourceService.QBITTORRENT and e.source_download_id:
                qbit_hashes.add(e.source_download_id.upper())
        
        # HIGH confidence: at least one hash appears in both *Arr and qBittorrent
        if arr_hashes & qbit_hashes:
            return "HIGH"
        
        # Check for category/tag correlation
        has_category = any(
            e.normalized_metadata and e.normalized_metadata.get("category")
            for e in self.events
        )
        
        # MEDIUM: has category AND at least one *Arr event (but no hash match)
        if has_category and has_arr_event:
            return "MEDIUM"
        
        # Heuristic match or only qBittorrent events
        return "LOW"
    
    def _determine_download_attempts(self) -> List[Dict[str, Any]]:
        """Extract distinct download attempts from events."""
        attempts = []
        
        # Group qBittorrent events by hash
        qbit_by_hash = {}
        for event in self.events:
            if event.source_service == SourceService.QBITTORRENT and event.source_download_id:
                hash_key = event.source_download_id
                if hash_key not in qbit_by_hash:
                    qbit_by_hash[hash_key] = []
                qbit_by_hash[hash_key].append(event)
        
        for hash_key, events in qbit_by_hash.items():
            events.sort(key=lambda e: e.timestamp)
            first = events[0]
            last = events[-1]
            
            # Determine if this is cross-seed
            is_cross_seed = False
            for e in events:
                tags = e.normalized_metadata.get("tags", "").lower() if e.normalized_metadata else ""
                category = e.normalized_metadata.get("category", "").lower() if e.normalized_metadata else ""
                if "cross-seed" in tags or "cross" in category:
                    is_cross_seed = True
                    break
            
            # Determine final state
            final_state = events[-1].event_type
            
            # Track ingestion sources
            ingestion_sources = set()
            for e in events:
                if e.normalized_metadata and e.normalized_metadata.get("ingestion"):
                    ingestion_sources.add(e.normalized_metadata["ingestion"])
                else:
                    ingestion_sources.add("polling")
            
            attempts.append({
                "hash": hash_key,
                "first_event": events[0].timestamp.isoformat(),
                "last_event": events[-1].timestamp.isoformat(),
                "state": final_state.value,
                "progress": events[-1].normalized_metadata.get("progress", 0) if events[-1].normalized_metadata else 0,
                "category": events[0].normalized_metadata.get("category", "") if events[0].normalized_metadata else "",
                "tags": events[0].normalized_metadata.get("tags", "") if events[0].normalized_metadata else "",
                "is_cross_seed": is_cross_seed,
                "event_count": len(events),
                "ingestion_sources": list(ingestion_sources),
            })
        
        return attempts
    
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
            ],
            "confidence": self.confidence,
            "download_attempts": self.download_attempts,
        }
    
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
        - Cross-service hash correlation (Sonarr/Radarr downloadId <-> qBittorrent hash)
        """
        updated = []
        
        # Group events by correlation key (using media_identifier as primary)
        grouped: Dict[str, List[RawEvent]] = {}
        for event in events:
            key = self._compute_correlation_key(event)
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(event)
        
        # Build hash-to-key mapping for cross-service correlation
        # Sonarr/Radarr events with source_download_id should link to qBittorrent hash groups
        # Only use *Arr events for this mapping, not qBittorrent events
        hash_to_media_key = {}
        for key, group_events in grouped.items():
            for event in group_events:
                if event.source_service in (SourceService.SONARR, SourceService.RADARR) and event.source_download_id:
                    hash_key = f"hash:{event.source_download_id}"
                    hash_to_media_key[hash_key] = key
        
        # Merge hash groups into media groups where hash matches
        merged_grouped = {}
        for key, group_events in grouped.items():
            if key in merged_grouped:
                continue
            
            # Start with this group's events
            merged_events = list(group_events)
            
            # If this is a media key, check if any hash groups should merge into it
            if key.startswith("media:"):
                # Find all hash groups that map to this media key
                for hash_key, media_key in hash_to_media_key.items():
                    if media_key == key and hash_key in grouped and hash_key != key:
                        # Merge hash group events into media group
                        merged_events.extend(grouped[hash_key])
            elif key.startswith("hash:"):
                # If this is a hash key, check if it maps to a media key
                media_key = hash_to_media_key.get(key)
                if media_key and media_key != key:
                    # This hash group will be merged into the media group
                    # Skip adding it as a separate group
                    continue
                else:
                    # No direct hash match - try title-based matching for cross-seed torrents
                    # If this hash group's title matches a media item, merge it there
                    if group_events:
                        sample_title = group_events[0].title
                        for media_key, media_events in grouped.items():
                            if media_key.startswith("media:"):
                                for me in media_events:
                                    if _titles_overlap(sample_title, me.title):
                                        merged_grouped.setdefault(media_key, []).extend(grouped[key])
                                        break
                    # If no title match, keep as standalone hash group (orphan)
                    # Don't continue - let it fall through to add to merged_grouped
            
            if merged_events:
                merged_grouped[key] = merged_events
            
            if merged_events:
                merged_grouped[key] = merged_events
        
        # Update each group
        for key, group_events in merged_grouped.items():
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
        
        # 2. For qBittorrent events, always use hash-based correlation key
        # This prevents qBittorrent events from creating "media:<hash>" keys
        if event.source_service == SourceService.QBITTORRENT and event.source_download_id:
            return f"hash:{event.source_download_id}"
        
        # 3. Use media_identifier as fallback for cross-service correlation
        if event.media_identifier:
            return f"media:{event.media_identifier}"
        
        # 4. Explicit correlation key (fallback)
        if event.correlation_key:
            return event.correlation_key
        
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