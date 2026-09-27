"""Tests for state machine."""
import pytest
from datetime import datetime, timedelta

from backend.adapters.base import SourceService, MediaType, EventType, EventStatus, RawEvent
from backend.correlation.state_machine import StateMachine


class TestStateMachine:
    """Tests for the state machine."""
    
    def test_valid_transitions(self):
        """Test valid state transitions."""
        assert StateMachine.is_valid_transition(EventType.WANTED, EventType.RELEASE_GRABBED)
        assert StateMachine.is_valid_transition(EventType.RELEASE_GRABBED, EventType.DOWNLOAD_STARTED)
        assert StateMachine.is_valid_transition(EventType.DOWNLOAD_STARTED, EventType.DOWNLOAD_PROGRESS)
        assert StateMachine.is_valid_transition(EventType.DOWNLOAD_PROGRESS, EventType.DOWNLOAD_COMPLETED)
        assert StateMachine.is_valid_transition(EventType.DOWNLOAD_COMPLETED, EventType.IMPORT_STARTED)
        assert StateMachine.is_valid_transition(EventType.IMPORT_STARTED, EventType.IMPORT_COMPLETED)
        assert StateMachine.is_valid_transition(EventType.IMPORT_COMPLETED, EventType.AVAILABLE)
    
    def test_invalid_transitions(self):
        """Test invalid state transitions."""
        assert not StateMachine.is_valid_transition(EventType.WANTED, EventType.AVAILABLE)
        assert not StateMachine.is_valid_transition(EventType.AVAILABLE, EventType.WANTED)
        assert not StateMachine.is_valid_transition(EventType.DOWNLOAD_STARTED, EventType.AVAILABLE)
    
    def test_next_expected_state(self):
        """Test next expected state determination."""
        assert StateMachine.get_next_expected(EventType.WANTED) == EventType.RELEASE_GRABBED
        assert StateMachine.get_next_expected(EventType.RELEASE_GRABBED) == EventType.DOWNLOAD_STARTED
        assert StateMachine.get_next_expected(EventType.DOWNLOAD_COMPLETED) == EventType.IMPORT_STARTED
        assert StateMachine.get_next_expected(EventType.AVAILABLE) is None
    
    def test_classify_state_with_no_progress(self):
        """Test stuck detection when no progress is made."""
        now = datetime.utcnow()
        
        events = [
            RawEvent(
                timestamp=now,
                source_service=SourceService.QBITTORRENT,
                event_type=EventType.DOWNLOAD_STARTED,
                media_type=MediaType.MOVIE,
                media_identifier="157336",
                title="Dune: Part Two",
                correlation_key="tmdb:157336"
            ),
            RawEvent(
                timestamp=now + timedelta(hours=2),
                source_service=SourceService.QBITTORRENT,
                event_type=EventType.DOWNLOAD_PROGRESS,
                media_type=MediaType.MOVIE,
                media_identifier="157336",
                title="Dune: Part Two",
                correlation_key="tmdb:157336",
                normalized_metadata={"progress": 50}
            )
        ]
        
        state, reason = StateMachine.classify_state(events)
        assert state == EventType.STUCK
        assert "No progress" in reason
    
    def test_classify_state_with_progress(self):
        """Test normal classification when progress is made."""
        now = datetime.utcnow()
        
        events = [
            RawEvent(
                timestamp=now,
                source_service=SourceService.QBITTORRENT,
                event_type=EventType.DOWNLOAD_STARTED,
                media_type=MediaType.MOVIE,
                media_identifier="157336",
                title="Dune: Part Two",
                correlation_key="tmdb:157336"
            ),
            RawEvent(
                timestamp=now + __import__('datetime').timedelta(minutes=5),
                source_service=SourceService.QBITTORRENT,
                event_type=EventType.DOWNLOAD_PROGRESS,
                media_type=MediaType.MOVIE,
                media_identifier="157336",
                title="Dune: Part Two",
                correlation_key="tmdb:157336",
                normalized_metadata={"progress": 50}
            )
        ]
        
        state, reason = StateMachine.classify_state(events)
        assert state == EventType.DOWNLOAD_PROGRESS
        assert reason is None
    
    def test_classify_state_with_empty_events(self):
        """Test classification with empty events."""
        state, reason = StateMachine.classify_state([])
        assert state == EventType.UNKNOWN
        assert reason == "No events recorded"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])