"""State machine for media item lifecycle transitions."""
from typing import Dict, Set, Optional
from enum import Enum

from backend.adapters.base import EventType, SourceService


class StateMachine:
    """Deterministic state machine for media item lifecycle."""
    
    # Valid transitions: from_state -> {to_state}
    TRANSITIONS: Dict[EventType, Set[EventType]] = {
        EventType.UNKNOWN: {EventType.WANTED, EventType.RELEASE_GRABBED, EventType.DOWNLOAD_STARTED},
        EventType.WANTED: {EventType.RELEASE_GRABBED, EventType.SEARCH_STARTED, EventType.STUCK, EventType.DOWNLOAD_STARTED},
        EventType.SEARCH_STARTED: {EventType.SEARCH_COMPLETED, EventType.SEARCH_FAILED, EventType.RELEASE_GRABBED},
        EventType.SEARCH_COMPLETED: {EventType.RELEASE_GRABBED, EventType.STUCK},
        EventType.SEARCH_FAILED: {EventType.WANTED, EventType.STUCK},
        EventType.RELEASE_GRABBED: {EventType.DOWNLOAD_STARTED, EventType.DOWNLOAD_PROGRESS, EventType.AVAILABLE, EventType.STUCK},
        EventType.DOWNLOAD_STARTED: {EventType.DOWNLOAD_PROGRESS, EventType.DOWNLOAD_COMPLETED, EventType.DOWNLOAD_FAILED, EventType.STUCK},
        EventType.DOWNLOAD_PROGRESS: {EventType.DOWNLOAD_PROGRESS, EventType.DOWNLOAD_COMPLETED, EventType.DOWNLOAD_FAILED, EventType.STUCK},
        EventType.DOWNLOAD_COMPLETED: {EventType.IMPORT_STARTED, EventType.AVAILABLE, EventType.STUCK},
        EventType.DOWNLOAD_FAILED: {EventType.WANTED, EventType.STUCK},
        EventType.IMPORT_STARTED: {EventType.IMPORT_COMPLETED, EventType.IMPORT_FAILED, EventType.STUCK},
        EventType.IMPORT_COMPLETED: {EventType.AVAILABLE},
        EventType.IMPORT_FAILED: {EventType.WANTED, EventType.STUCK},
        EventType.AVAILABLE: set(),  # Terminal state
        EventType.STUCK: {EventType.WANTED, EventType.DOWNLOAD_STARTED, EventType.RELEASE_GRABBED},
    }
    
    @classmethod
    def is_valid_transition(cls, from_state: EventType, to_state: EventType) -> bool:
        """Check if a state transition is valid."""
        # Terminal states have no outgoing transitions
        if from_state == EventType.AVAILABLE:
            return False
        valid_targets = cls.TRANSITIONS.get(from_state, set())
        return to_state in valid_targets
    
    @classmethod
    def get_valid_transitions(cls, state: EventType) -> Set[EventType]:
        """Get all valid next states for a given state."""
        return cls.TRANSITIONS.get(state, set())
    
    @classmethod
    def get_next_expected(cls, state: EventType) -> Optional[EventType]:
        """Get the expected next state (first in transition set)."""
        valid = cls.TRANSITIONS.get(state, set())
        if not valid:
            return None
        # Return a deterministic ordering
        priority = [
            EventType.RELEASE_GRABBED,
            EventType.SEARCH_STARTED,
            EventType.SEARCH_COMPLETED,
            EventType.SEARCH_FAILED,
            EventType.DOWNLOAD_STARTED,
            EventType.DOWNLOAD_PROGRESS,
            EventType.DOWNLOAD_COMPLETED,
            EventType.DOWNLOAD_FAILED,
            EventType.IMPORT_STARTED,
            EventType.IMPORT_COMPLETED,
            EventType.IMPORT_FAILED,
            EventType.AVAILABLE,
            EventType.STUCK,
        ]
        for p in priority:
            if p in valid:
                return p
        return next(iter(valid)) if valid else None
    
    @classmethod
    def classify_state(cls, events: list) -> tuple[EventType, Optional[str]]:
        """Classify the current state from a list of events.
        
        Returns (state, reason) tuple.
        """
        if not events:
            return EventType.UNKNOWN, "No events recorded"
        
        last_event = events[-1]
        state = last_event.event_type
        
        # Check for qBittorrent stalled states
        # These are explicit signals from qBittorrent that a torrent is stalled
        for event in reversed(events):
            if event.source_service == SourceService.QBITTORRENT:
                qbit_state = event.normalized_metadata.get("state", "").lower() if event.normalized_metadata else ""
                if qbit_state in ["stalleddl", "stallledup"]:
                    progress = event.normalized_metadata.get("progress", 0)
                    return EventType.STUCK, f"qBittorrent reports stalled ({qbit_state}) at {progress}%"
        
        # Check for stuck condition: no progress for a long time
        if len(events) > 1:
            first_ts = events[0].timestamp
            last_ts = events[-1].timestamp
            duration = (last_ts - first_ts).total_seconds()
            
            if duration > 3600 and state in [EventType.DOWNLOAD_PROGRESS, EventType.SEARCH_STARTED]:
                # No progress in over an hour
                return EventType.STUCK, "No progress detected for extended period"
        
        return state, None