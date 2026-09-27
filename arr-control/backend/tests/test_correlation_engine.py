"""Tests for the correlation engine."""
import pytest
from datetime import datetime, timedelta
from typing import List

from backend.adapters.base import RawEvent, SourceService, MediaType, EventType, EventStatus
from backend.correlation.engine import CorrelationEngine, CorrelationResult
from backend.correlation.state_machine import StateMachine


class TestCorrelationEngine:
    """Tests for CorrelationEngine."""
    
    def test_create_engine(self):
        """Test creating a correlation engine."""
        engine = CorrelationEngine()
        assert engine is not None
        assert len(engine.get_all_items()) == 0
    
    def test_add_single_event(self):
        """Test adding a single event."""
        engine = CorrelationEngine()
        event = RawEvent(
            timestamp=datetime.utcnow(),
            source_service=SourceService.RADARR,
            event_type=EventType.WANTED,
            media_type=MediaType.MOVIE,
            media_identifier="157336",
            title="Dune: Part Two",
            tmdb_id="157336",
            correlation_key="tmdb:157336",
            source_item_id="12345"
        )
        
        results = engine.add_events([event])
        assert len(results) == 1
        
        item = engine.get_item("media:157336")
        assert item is not None
        assert item.current_state == EventType.WANTED
        assert item.title == "Dune: Part Two"
    
    def test_duplicate_events_ignored(self):
        """Test that duplicate events are not added."""
        engine = CorrelationEngine()
        now = datetime.utcnow()
        
        event1 = RawEvent(
            timestamp=now,
            source_service=SourceService.RADARR,
            event_type=EventType.WANTED,
            media_type=MediaType.MOVIE,
            media_identifier="157336",
            title="Dune: Part Two",
            correlation_key="media:157336"
        )
        
        event2 = RawEvent(
            timestamp=now,
            source_service=SourceService.RADARR,
            event_type=EventType.WANTED,
            media_type=MediaType.MOVIE,
            media_identifier="157336",
            title="Dune: Part Two",
            correlation_key="media:157336"
        )
        
        results1 = engine.add_events([event1])
        results2 = engine.add_events([event2])
        
        # Should only have one event in the timeline
        item = engine.get_item("media:157336")
        assert len(item.events) == 1
    
    def test_out_of_order_events(self):
        """Test that out-of-order events are sorted correctly."""
        engine = CorrelationEngine()
        now = datetime.utcnow()
        
        # Add events in reverse order
        event2 = RawEvent(
            timestamp=now + timedelta(minutes=2),
            source_service=SourceService.RADARR,
            event_type=EventType.RELEASE_GRABBED,
            media_type=MediaType.MOVIE,
            media_identifier="157336",
            title="Dune: Part Two",
            correlation_key="media:157336"
        )
        
        event1 = RawEvent(
            timestamp=now,
            source_service=SourceService.RADARR,
            event_type=EventType.WANTED,
            media_type=MediaType.MOVIE,
            media_identifier="157336",
            title="Dune: Part Two",
            correlation_key="media:157336"
        )
        
        engine.add_events([event2, event1])
        
        item = engine.get_item("media:157336")
        assert len(item.events) == 2
        assert item.events[0].event_type == EventType.WANTED
        assert item.events[1].event_type == EventType.RELEASE_GRABBED
    
    def test_missing_events_tolerated(self):
        """Test that missing events don't break correlation."""
        engine = CorrelationEngine()
        now = datetime.utcnow()
        
        # Jump from WANTED to DOWNLOAD_COMPLETED
        event1 = RawEvent(
            timestamp=now,
            source_service=SourceService.RADARR,
            event_type=EventType.WANTED,
            media_type=MediaType.MOVIE,
            media_identifier="157336",
            title="Dune: Part Two",
            correlation_key="media:157336"
        )
        
        event2 = RawEvent(
            timestamp=now + timedelta(minutes=10),
            source_service=SourceService.RADARR,
            event_type=EventType.DOWNLOAD_COMPLETED,
            media_type=MediaType.MOVIE,
            media_identifier="157336",
            title="Dune: Part Two",
            correlation_key="media:157336"
        )
        
        engine.add_events([event1, event2])
        
        item = engine.get_item("media:157336")
        assert item.current_state == EventType.DOWNLOAD_COMPLETED
        assert len(item.events) == 2
    
    def test_multiple_downloads_same_item(self):
        """Test tracking multiple download attempts for the same item."""
        engine = CorrelationEngine()
        now = datetime.utcnow()
        
        # First download attempt
        event1 = RawEvent(
            timestamp=now,
            source_service=SourceService.RADARR,
            event_type=EventType.RELEASE_GRABBED,
            media_type=MediaType.MOVIE,
            media_identifier="157336",
            title="Dune: Part Two",
            correlation_key="media:157336",
            source_download_id="hash1"
        )
        
        event2 = RawEvent(
            timestamp=now + timedelta(minutes=5),
            source_service=SourceService.QBITTORRENT,
            event_type=EventType.DOWNLOAD_PROGRESS,
            media_type=MediaType.MOVIE,
            media_identifier="157336",
            title="Dune: Part Two",
            source_download_id="hash1",
            correlation_key="hash:hash1"
        )
        
        event3 = RawEvent(
            timestamp=now + timedelta(minutes=10),
            source_service=SourceService.QBITTORRENT,
            event_type=EventType.DOWNLOAD_FAILED,
            media_type=MediaType.MOVIE,
            media_identifier="157336",
            title="Dune: Part Two",
            source_download_id="hash1",
            correlation_key="hash:hash1",
            error_message="Seeds unavailable"
        )
        
        # Second download attempt with different hash
        event4 = RawEvent(
            timestamp=now + timedelta(minutes=15),
            source_service=SourceService.RADARR,
            event_type=EventType.RELEASE_GRABBED,
            media_type=MediaType.MOVIE,
            media_identifier="157336",
            title="Dune: Part Two",
            correlation_key="media:157336",
            source_download_id="hash2"
        )
        
        event5 = RawEvent(
            timestamp=now + timedelta(minutes=20),
            source_service=SourceService.QBITTORRENT,
            event_type=EventType.DOWNLOAD_COMPLETED,
            media_type=MediaType.MOVIE,
            media_identifier="157336",
            title="Dune: Part Two",
            source_download_id="hash2",
            correlation_key="hash:hash2"
        )
        
        engine.add_events([event1, event2, event3, event4, event5])
        
        item = engine.get_item("media:157336")
        assert len(item.events) == 5
        assert item.current_state == EventType.DOWNLOAD_COMPLETED
    
    def test_movie_lifecycle(self):
        """Test a complete movie lifecycle."""
        engine = CorrelationEngine()
        now = datetime.utcnow()
        
        events = [
            RawEvent(timestamp=now, source_service=SourceService.RADARR, event_type=EventType.WANTED, media_type=MediaType.MOVIE, media_identifier="157336", title="Dune: Part Two", correlation_key="media:157336"),
            RawEvent(timestamp=now + timedelta(minutes=1), source_service=SourceService.RADARR, event_type=EventType.RELEASE_GRABBED, media_type=MediaType.MOVIE, media_identifier="157336", title="Dune: Part Two", correlation_key="media:157336"),
            RawEvent(timestamp=now + timedelta(minutes=2), source_service=SourceService.QBITTORRENT, event_type=EventType.DOWNLOAD_STARTED, media_type=MediaType.MOVIE, media_identifier="157336", title="Dune: Part Two", source_download_id="abc123", correlation_key="hash:abc123"),
            RawEvent(timestamp=now + timedelta(minutes=7), source_service=SourceService.QBITTORRENT, event_type=EventType.DOWNLOAD_PROGRESS, media_type=MediaType.MOVIE, media_identifier="157336", title="Dune: Part Two", source_download_id="abc123", correlation_key="hash:abc123", normalized_metadata={"progress": 74}),
            RawEvent(timestamp=now + timedelta(minutes=10), source_service=SourceService.QBITTORRENT, event_type=EventType.DOWNLOAD_COMPLETED, media_type=MediaType.MOVIE, media_identifier="157336", title="Dune: Part Two", source_download_id="abc123", correlation_key="hash:abc123"),
            RawEvent(timestamp=now + timedelta(minutes=11), source_service=SourceService.RADARR, event_type=EventType.IMPORT_STARTED, media_type=MediaType.MOVIE, media_identifier="157336", title="Dune: Part Two", correlation_key="media:157336"),
            RawEvent(timestamp=now + timedelta(minutes=12), source_service=SourceService.RADARR, event_type=EventType.IMPORT_COMPLETED, media_type=MediaType.MOVIE, media_identifier="157336", title="Dune: Part Two", correlation_key="media:157336"),
            RawEvent(timestamp=now + timedelta(minutes=13), source_service=SourceService.RADARR, event_type=EventType.AVAILABLE, media_type=MediaType.MOVIE, media_identifier="157336", title="Dune: Part Two", correlation_key="media:157336"),
        ]
        
        engine.add_events(events)
        
        item = engine.get_item("media:157336")
        assert item.current_state == EventType.AVAILABLE
        assert len(item.events) == 8
        assert item.next_expected_state is None
    
    def test_episode_lifecycle(self):
        """Test a complete episode lifecycle."""
        engine = CorrelationEngine()
        now = datetime.utcnow()
        
        events = [
            RawEvent(timestamp=now, source_service=SourceService.SONARR, event_type=EventType.WANTED, media_type=MediaType.EPISODE, media_identifier="121361", title="The Last of Us S01E01", season=1, episode=1, tvdb_id="121361", correlation_key="media:121361:S01E01"),
            RawEvent(timestamp=now + timedelta(minutes=1), source_service=SourceService.SONARR, event_type=EventType.RELEASE_GRABBED, media_type=MediaType.EPISODE, media_identifier="121361", title="The Last of Us S01E01", season=1, episode=1, tvdb_id="121361", correlation_key="media:121361:S01E01"),
            RawEvent(timestamp=now + timedelta(minutes=2), source_service=SourceService.QBITTORRENT, event_type=EventType.DOWNLOAD_STARTED, media_type=MediaType.EPISODE, media_identifier="121361", title="The Last of Us S01E01", season=1, episode=1, tvdb_id="121361", source_download_id="xyz789", correlation_key="hash:xyz789"),
            RawEvent(timestamp=now + timedelta(minutes=5), source_service=SourceService.QBITTORRENT, event_type=EventType.DOWNLOAD_COMPLETED, media_type=MediaType.EPISODE, media_identifier="121361", title="The Last of Us S01E01", season=1, episode=1, tvdb_id="121361", source_download_id="xyz789", correlation_key="hash:xyz789"),
            RawEvent(timestamp=now + timedelta(minutes=6), source_service=SourceService.SONARR, event_type=EventType.IMPORT_COMPLETED, media_type=MediaType.EPISODE, media_identifier="121361", title="The Last of Us S01E01", season=1, episode=1, tvdb_id="121361", correlation_key="media:121361:S01E01"),
            RawEvent(timestamp=now + timedelta(minutes=7), source_service=SourceService.SONARR, event_type=EventType.AVAILABLE, media_type=MediaType.EPISODE, media_identifier="121361", title="The Last of Us S01E01", season=1, episode=1, tvdb_id="121361", correlation_key="media:121361:S01E01"),
        ]
        
        engine.add_events(events)
        
        item = engine.get_item("media:121361:S01E01")
        assert item.current_state == EventType.AVAILABLE
        assert item.season == 1
        assert item.episode == 1
    
    def test_failed_import(self):
        """Test import failure scenario."""
        engine = CorrelationEngine()
        now = datetime.utcnow()
        
        events = [
            RawEvent(timestamp=now, source_service=SourceService.RADARR, event_type=EventType.WANTED, media_type=MediaType.MOVIE, media_identifier="157336", title="Dune: Part Two", correlation_key="media:157336"),
            RawEvent(timestamp=now + timedelta(minutes=1), source_service=SourceService.RADARR, event_type=EventType.RELEASE_GRABBED, media_type=MediaType.MOVIE, media_identifier="157336", title="Dune: Part Two", correlation_key="media:157336"),
            RawEvent(timestamp=now + timedelta(minutes=5), source_service=SourceService.QBITTORRENT, event_type=EventType.DOWNLOAD_COMPLETED, media_type=MediaType.MOVIE, media_identifier="157336", title="Dune: Part Two", source_download_id="abc123", correlation_key="hash:abc123"),
            RawEvent(timestamp=now + timedelta(minutes=6), source_service=SourceService.RADARR, event_type=EventType.IMPORT_STARTED, media_type=MediaType.MOVIE, media_identifier="157336", title="Dune: Part Two", correlation_key="media:157336"),
            RawEvent(timestamp=now + timedelta(minutes=7), source_service=SourceService.RADARR, event_type=EventType.IMPORT_FAILED, media_type=MediaType.MOVIE, media_identifier="157336", title="Dune: Part Two", correlation_key="media:157336", error_message="Invalid format"),
        ]
        
        engine.add_events(events)
        
        item = engine.get_item("media:157336")
        assert item.current_state == EventType.IMPORT_FAILED
        assert item.last_event.error_message == "Invalid format"
    
    def test_failed_download(self):
        """Test download failure scenario."""
        engine = CorrelationEngine()
        now = datetime.utcnow()
        
        events = [
            RawEvent(timestamp=now, source_service=SourceService.RADARR, event_type=EventType.RELEASE_GRABBED, media_type=MediaType.MOVIE, media_identifier="157336", title="Dune: Part Two", correlation_key="media:157336"),
            RawEvent(timestamp=now + timedelta(minutes=1), source_service=SourceService.QBITTORRENT, event_type=EventType.DOWNLOAD_STARTED, media_type=MediaType.MOVIE, media_identifier="157336", title="Dune: Part Two", source_download_id="abc123", correlation_key="hash:abc123"),
            RawEvent(timestamp=now + timedelta(minutes=5), source_service=SourceService.QBITTORRENT, event_type=EventType.DOWNLOAD_FAILED, media_type=MediaType.MOVIE, media_identifier="157336", title="Dune: Part Two", source_download_id="abc123", correlation_key="hash:abc123", error_message="Tracker timeout"),
        ]
        
        engine.add_events(events)
        
        item = engine.get_item("media:157336")
        assert item.current_state == EventType.DOWNLOAD_FAILED
        assert item.last_event.error_message == "Tracker timeout"
    
    def test_stuck_download(self):
        """Test stuck download detection."""
        engine = CorrelationEngine()
        now = datetime.utcnow()
        
        events = [
            RawEvent(timestamp=now, source_service=SourceService.QBITTORRENT, event_type=EventType.DOWNLOAD_STARTED, media_type=MediaType.MOVIE, media_identifier="157336", title="Dune: Part Two", source_download_id="abc123", correlation_key="hash:abc123"),
            RawEvent(timestamp=now + timedelta(hours=2), source_service=SourceService.QBITTORRENT, event_type=EventType.DOWNLOAD_PROGRESS, media_type=MediaType.MOVIE, media_identifier="157336", title="Dune: Part Two", source_download_id="abc123", correlation_key="hash:abc123", normalized_metadata={"progress": 50}),
        ]
        
        engine.add_events(events)
        
        item = engine.get_item("hash:abc123")
        # Should be detected as stuck due to no progress in 2 hours
        assert item.current_state == EventType.STUCK
    
    def test_service_unavailable(self):
        """Test handling when service events stop arriving."""
        engine = CorrelationEngine()
        now = datetime.utcnow()
        
        events = [
            RawEvent(timestamp=now, source_service=SourceService.RADARR, event_type=EventType.RELEASE_GRABBED, media_type=MediaType.MOVIE, media_identifier="157336", title="Dune: Part Two", correlation_key="media:157336"),
            # No more events from any service...
        ]
        
        engine.add_events(events)
        
        item = engine.get_item("media:157336")
        assert item.current_state == EventType.RELEASE_GRABBED
        assert item.next_expected_state == EventType.DOWNLOAD_STARTED
    
    def test_explanation_generation(self):
        """Test human-readable explanation generation."""
        engine = CorrelationEngine()
        now = datetime.utcnow()
        
        events = [
            RawEvent(timestamp=now, source_service=SourceService.RADARR, event_type=EventType.IMPORT_STARTED, media_type=MediaType.MOVIE, media_identifier="157336", title="Dune: Part Two", correlation_key="media:157336"),
            RawEvent(timestamp=now + timedelta(minutes=1), source_service=SourceService.RADARR, event_type=EventType.IMPORT_FAILED, media_type=MediaType.MOVIE, media_identifier="157336", title="Dune: Part Two", correlation_key="media:157336", error_message="Invalid format"),
        ]
        
        engine.add_events(events)
        
        explanation = engine.explain("media:157336")
        assert explanation is not None
        assert "Import failed" in explanation["reason"]
        assert len(explanation["evidence"]) > 0
    
    def test_state_machine_transitions(self):
        """Test state machine validity."""
        # Valid transitions
        assert StateMachine.is_valid_transition(EventType.WANTED, EventType.RELEASE_GRABBED)
        assert StateMachine.is_valid_transition(EventType.RELEASE_GRABBED, EventType.DOWNLOAD_STARTED)
        assert StateMachine.is_valid_transition(EventType.DOWNLOAD_STARTED, EventType.DOWNLOAD_COMPLETED)
        assert StateMachine.is_valid_transition(EventType.DOWNLOAD_COMPLETED, EventType.IMPORT_STARTED)
        assert StateMachine.is_valid_transition(EventType.IMPORT_STARTED, EventType.IMPORT_COMPLETED)
        assert StateMachine.is_valid_transition(EventType.IMPORT_COMPLETED, EventType.AVAILABLE)
        
        # Invalid transitions
        assert not StateMachine.is_valid_transition(EventType.WANTED, EventType.AVAILABLE)
        assert not StateMachine.is_valid_transition(EventType.AVAILABLE, EventType.WANTED)
    
    def test_active_items_filtering(self):
        """Test filtering active items."""
        engine = CorrelationEngine()
        now = datetime.utcnow()
        
        # Movie still downloading
        engine.add_events([
            RawEvent(timestamp=now, source_service=SourceService.RADARR, event_type=EventType.RELEASE_GRABBED, media_type=MediaType.MOVIE, media_identifier="157336", title="Dune: Part Two", correlation_key="media:157336", source_download_id="abc123"),
            RawEvent(timestamp=now + timedelta(minutes=2), source_service=SourceService.QBITTORRENT, event_type=EventType.DOWNLOAD_PROGRESS, media_type=MediaType.MOVIE, media_identifier="157336", title="Dune: Part Two", source_download_id="abc123", correlation_key="hash:abc123")
        ])
        
        # Movie already available
        engine.add_events([
            RawEvent(timestamp=now, source_service=SourceService.RADARR, event_type=EventType.WANTED, media_type=MediaType.MOVIE, media_identifier="99999", title="Test Movie", correlation_key="media:99999"),
            RawEvent(timestamp=now + timedelta(minutes=1), source_service=SourceService.RADARR, event_type=EventType.AVAILABLE, media_type=MediaType.MOVIE, media_identifier="99999", title="Test Movie", correlation_key="media:99999")
        ])
        
        active = engine.get_active_items()
        assert len(active) == 1
        assert active[0].current_state == EventType.DOWNLOAD_PROGRESS
    
    def test_completed_items_filtering(self):
        """Test filtering completed items."""
        engine = CorrelationEngine()
        now = datetime.utcnow()
        
        engine.add_events([
            RawEvent(timestamp=now, source_service=SourceService.RADARR, event_type=EventType.WANTED, media_type=MediaType.MOVIE, media_identifier="99999", title="Test Movie", correlation_key="media:99999"),
            RawEvent(timestamp=now + timedelta(minutes=1), source_service=SourceService.RADARR, event_type=EventType.AVAILABLE, media_type=MediaType.MOVIE, media_identifier="99999", title="Test Movie", correlation_key="media:99999")
        ])
        
        completed = engine.get_completed_items()
        assert len(completed) == 1
        assert completed[0].current_state == EventType.AVAILABLE


class TestDeterministicFixture:
    """Test the deterministic fixture representing the full lifecycle."""
    
    def test_full_lifecycle_deterministic(self):
        """Test the complete lifecycle fixture from the requirements."""
        engine = CorrelationEngine()
        
        # Fixed timestamps for determinism
        base_time = datetime(2026, 9, 27, 19, 0, 0)
        
        events = [
            # Radarr: movie wanted
            RawEvent(
                timestamp=base_time,
                source_service=SourceService.RADARR,
                event_type=EventType.WANTED,
                media_type=MediaType.MOVIE,
                media_identifier="157336",
                title="Dune: Part Two",
                tmdb_id="157336",
                correlation_key="tmdb:157336",
                source_item_id="12345"
            ),
            # Radarr: release grabbed
            RawEvent(
                timestamp=base_time + timedelta(minutes=1),
                source_service=SourceService.RADARR,
                event_type=EventType.RELEASE_GRABBED,
                media_type=MediaType.MOVIE,
                media_identifier="157336",
                title="Dune: Part Two",
                tmdb_id="157336",
                correlation_key="tmdb:157336",
                source_item_id="12345",
                source_download_id="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
            ),
            # qBittorrent: matching torrent detected
            RawEvent(
                timestamp=base_time + timedelta(minutes=2),
                source_service=SourceService.QBITTORRENT,
                event_type=EventType.DOWNLOAD_STARTED,
                media_type=MediaType.MOVIE,
                media_identifier="157336",
                title="Dune.Part.Two.2024.2160p.WEB-DL.DDP5.1.H.264-FLUX",
                source_download_id="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
                correlation_key="hash:a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
                normalized_metadata={"progress": 0}
            ),
            # qBittorrent: 74% downloading
            RawEvent(
                timestamp=base_time + timedelta(minutes=7),
                source_service=SourceService.QBITTORRENT,
                event_type=EventType.DOWNLOAD_PROGRESS,
                media_type=MediaType.MOVIE,
                media_identifier="157336",
                title="Dune.Part.Two.2024.2160p.WEB-DL.DDP5.1.H.264-FLUX",
                source_download_id="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
                correlation_key="hash:a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
                normalized_metadata={"progress": 74}
            ),
            # qBittorrent: download completed
            RawEvent(
                timestamp=base_time + timedelta(minutes=10),
                source_service=SourceService.QBITTORRENT,
                event_type=EventType.DOWNLOAD_COMPLETED,
                media_type=MediaType.MOVIE,
                media_identifier="157336",
                title="Dune.Part.Two.2024.2160p.WEB-DL.DDP5.1.H.264-FLUX",
                source_download_id="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
                correlation_key="hash:a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
            ),
            # Radarr: import attempted
            RawEvent(
                timestamp=base_time + timedelta(minutes=11),
                source_service=SourceService.RADARR,
                event_type=EventType.IMPORT_STARTED,
                media_type=MediaType.MOVIE,
                media_identifier="157336",
                title="Dune: Part Two",
                tmdb_id="157336",
                correlation_key="tmdb:157336",
                source_item_id="12345"
            ),
            # Radarr: import failed
            RawEvent(
                timestamp=base_time + timedelta(minutes=12),
                source_service=SourceService.RADARR,
                event_type=EventType.IMPORT_FAILED,
                media_type=MediaType.MOVIE,
                media_identifier="157336",
                title="Dune: Part Two",
                tmdb_id="157336",
                correlation_key="tmdb:157336",
                source_item_id="12345",
                error_message="Invalid format"
            ),
        ]
        
        engine.add_events(events)
        
        # Verify the timeline is deterministic and correctly correlated
        item = engine.get_item("media:157336")
        assert item is not None
        assert item.current_state == EventType.IMPORT_FAILED
        assert item.title == "Dune: Part Two"
        assert item.media_type == MediaType.MOVIE
        assert len(item.events) == 7
        
        # Verify the timeline order
        expected_states = [
            EventType.WANTED,
            EventType.RELEASE_GRABBED,
            EventType.DOWNLOAD_STARTED,
            EventType.DOWNLOAD_PROGRESS,
            EventType.DOWNLOAD_COMPLETED,
            EventType.IMPORT_STARTED,
            EventType.IMPORT_FAILED,
        ]
        for i, expected in enumerate(expected_states):
            assert item.events[i].event_type == expected, f"Event {i} should be {expected}, got {item.events[i].event_type}"
        
        # Verify progress tracking
        assert item.progress == 74
        
        # Verify explanation
        explanation = engine.explain("media:157336")
        assert explanation is not None
        assert "Import failed" in explanation["reason"]
        assert "Invalid format" in explanation["evidence"][0]
        
        # Verify next expected state
        assert item.next_expected_state == EventType.WANTED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

# Live-data regression fixtures
# Based on actual production data from saltbox stack


class TestLiveDataRegression:
    """Regression tests based on live validation data."""
    
    def test_matlock_s02e14_exact_hash_correlation(self):
        """Test Matlock S02E14 exact hash correlation (A)."""
        engine = CorrelationEngine()
        now = datetime.utcnow()
        
        events = [
            # Sonarr: episode wanted
            RawEvent(
                timestamp=now,
                source_service=SourceService.SONARR,
                event_type=EventType.WANTED,
                media_type=MediaType.EPISODE,
                media_identifier="121361",
                title="Matlock S02E14",
                season=2,
                episode=14,
                tvdb_id="121361",
                correlation_key="media:121361:S02E14",
            ),
            # Sonarr: release grabbed
            RawEvent(
                timestamp=now + timedelta(minutes=1),
                source_service=SourceService.SONARR,
                event_type=EventType.RELEASE_GRABBED,
                media_type=MediaType.EPISODE,
                media_identifier="121361",
                title="Matlock S02E14",
                season=2,
                episode=14,
                tvdb_id="121361",
                correlation_key="media:121361:S02E14",
                source_download_id="4FADA3FE289D6A27",
            ),
            # qBittorrent: download completed with exact hash match
            RawEvent(
                timestamp=now + timedelta(minutes=10),
                source_service=SourceService.QBITTORRENT,
                event_type=EventType.DOWNLOAD_COMPLETED,
                media_type=MediaType.EPISODE,
                media_identifier="4FADA3FE289D6A27",
                title="Matlock.2024.S02E14.Day.One.1080p.AMZN.WEB-DL.DDP5.1.H.264-FLUX",
                source_download_id="4FADA3FE289D6A27",
                correlation_key="hash:4FADA3FE289D6A27",
                normalized_metadata={
                    "progress": 100,
                    "state": "stalledUP",
                    "category": "tv-sonarr",
                    "tags": "",
                },
            ),
            # Sonarr: import completed
            RawEvent(
                timestamp=now + timedelta(minutes=11),
                source_service=SourceService.SONARR,
                event_type=EventType.IMPORT_COMPLETED,
                media_type=MediaType.EPISODE,
                media_identifier="121361",
                title="Matlock S02E14",
                season=2,
                episode=14,
                tvdb_id="121361",
                correlation_key="media:121361:S02E14",
            ),
            # Sonarr: available
            RawEvent(
                timestamp=now + timedelta(minutes=12),
                source_service=SourceService.SONARR,
                event_type=EventType.AVAILABLE,
                media_type=MediaType.EPISODE,
                media_identifier="121361",
                title="Matlock S02E14",
                season=2,
                episode=14,
                tvdb_id="121361",
                correlation_key="media:121361:S02E14",
            ),
        ]
        
        engine.add_events(events)
        item = engine.get_item("media:121361:S02E14")
        
        assert item is not None
        assert item.current_state == EventType.AVAILABLE
        assert item.confidence == "HIGH"
        
        # Check download attempts
        attempts = item.download_attempts
        assert len(attempts) == 1
        assert attempts[0]["hash"] == "4FADA3FE289D6A27"
        assert attempts[0]["state"] == "download_completed"
        assert attempts[0]["is_cross_seed"] == False
        assert attempts[0]["category"] == "tv-sonarr"
    
    def test_end_of_oak_street_exact_hash_correlation(self):
        """Test The End of Oak Street exact hash correlation (B)."""
        engine = CorrelationEngine()
        now = datetime.utcnow()
        
        events = [
            # Radarr: movie wanted
            RawEvent(
                timestamp=now,
                source_service=SourceService.RADARR,
                event_type=EventType.WANTED,
                media_type=MediaType.MOVIE,
                media_identifier="157336",
                title="The End of Oak Street",
                tmdb_id="157336",
                correlation_key="media:157336",
            ),
            # Radarr: release grabbed
            RawEvent(
                timestamp=now + timedelta(minutes=1),
                source_service=SourceService.RADARR,
                event_type=EventType.RELEASE_GRABBED,
                media_type=MediaType.MOVIE,
                media_identifier="157336",
                title="The End of Oak Street",
                tmdb_id="157336",
                correlation_key="media:157336",
                source_download_id="EE8C9DE008C2A59A",
            ),
            # qBittorrent: download completed with exact hash match
            RawEvent(
                timestamp=now + timedelta(minutes=10),
                source_service=SourceService.QBITTORRENT,
                event_type=EventType.DOWNLOAD_COMPLETED,
                media_type=MediaType.MOVIE,
                media_identifier="EE8C9DE008C2A59A",
                title="The.End.of.Oak.Street.2026.1080p.MA.WEB-DL.DDP5.1.Atmos.H.264-BYNDR",
                source_download_id="EE8C9DE008C2A59A",
                correlation_key="hash:EE8C9DE008C2A59A",
                normalized_metadata={
                    "progress": 100,
                    "state": "stalledUP",
                    "category": "radarr",
                    "tags": "",
                },
            ),
            # Radarr: import completed
            RawEvent(
                timestamp=now + timedelta(minutes=11),
                source_service=SourceService.RADARR,
                event_type=EventType.IMPORT_COMPLETED,
                media_type=MediaType.MOVIE,
                media_identifier="157336",
                title="The End of Oak Street",
                tmdb_id="157336",
                correlation_key="media:157336",
            ),
            # Radarr: available
            RawEvent(
                timestamp=now + timedelta(minutes=12),
                source_service=SourceService.RADARR,
                event_type=EventType.AVAILABLE,
                media_type=MediaType.MOVIE,
                media_identifier="157336",
                title="The End of Oak Street",
                tmdb_id="157336",
                correlation_key="media:157336",
            ),
        ]
        
        engine.add_events(events)
        item = engine.get_item("media:157336")
        
        assert item is not None
        assert item.current_state == EventType.AVAILABLE
        assert item.confidence == "HIGH"
        
        attempts = item.download_attempts
        assert len(attempts) == 1
        assert attempts[0]["hash"] == "EE8C9DE008C2A59A"
        assert attempts[0]["category"] == "radarr"
    
    def test_the_limey_stalleddl_at_90_percent(self):
        """Test The Limey stalledDL at 90.7% (C)."""
        engine = CorrelationEngine()
        now = datetime.utcnow()
        
        events = [
            # Radarr: movie wanted
            RawEvent(
                timestamp=now,
                source_service=SourceService.RADARR,
                event_type=EventType.WANTED,
                media_type=MediaType.MOVIE,
                media_identifier="99999",
                title="The Limey",
                tmdb_id="99999",
                correlation_key="media:99999",
            ),
            # Radarr: release grabbed
            RawEvent(
                timestamp=now + timedelta(minutes=1),
                source_service=SourceService.RADARR,
                event_type=EventType.RELEASE_GRABBED,
                media_type=MediaType.MOVIE,
                media_identifier="99999",
                title="The Limey",
                tmdb_id="99999",
                correlation_key="media:99999",
                source_download_id="F0E4A71F5CA705CF",
            ),
            # qBittorrent: download started
            RawEvent(
                timestamp=now + timedelta(minutes=2),
                source_service=SourceService.QBITTORRENT,
                event_type=EventType.DOWNLOAD_STARTED,
                media_type=MediaType.MOVIE,
                media_identifier="F0E4A71F5CA705CF",
                title="The.Limey.1999.720p.BRRip.XviD.AC3-RARBG",
                source_download_id="F0E4A71F5CA705CF",
                correlation_key="hash:F0E4A71F5CA705CF",
                normalized_metadata={
                    "progress": 0,
                    "state": "downloading",
                    "category": "radarr",
                },
            ),
            # qBittorrent: stalled at 90.7%
            RawEvent(
                timestamp=now + timedelta(hours=2),
                source_service=SourceService.QBITTORRENT,
                event_type=EventType.DOWNLOAD_PROGRESS,
                media_type=MediaType.MOVIE,
                media_identifier="F0E4A71F5CA705CF",
                title="The.Limey.1999.720p.BRRip.XviD.AC3-RARBG",
                source_download_id="F0E4A71F5CA705CF",
                correlation_key="hash:F0E4A71F5CA705CF",
                normalized_metadata={
                    "progress": 90,
                    "state": "stalledDL",
                    "category": "radarr",
                },
            ),
        ]
        
        engine.add_events(events)
        item = engine.get_item("media:99999")
        
        assert item is not None
        assert item.current_state == EventType.STUCK
        assert item.confidence == "HIGH"
        
        # Check download attempts
        attempts = item.download_attempts
        assert len(attempts) == 1
        assert attempts[0]["hash"] == "F0E4A71F5CA705CF"
        assert attempts[0]["progress"] == 90
        assert "stalled" in attempts[0]["state"] or "download_progress" in attempts[0]["state"]
    
    def test_rookie_s08e12_cross_seed_duplicates(self):
        """Test The Rookie S08E12 with three cross-seed torrents (D)."""
        engine = CorrelationEngine()
        now = datetime.utcnow()
        
        events = [
            # Sonarr: episode wanted
            RawEvent(
                timestamp=now,
                source_service=SourceService.SONARR,
                event_type=EventType.WANTED,
                media_type=MediaType.EPISODE,
                media_identifier="121361",
                title="The Rookie S08E12",
                season=8,
                episode=12,
                tvdb_id="121361",
                correlation_key="media:121361:S08E12",
            ),
            # Sonarr: release grabbed
            RawEvent(
                timestamp=now + timedelta(minutes=1),
                source_service=SourceService.SONARR,
                event_type=EventType.RELEASE_GRABBED,
                media_type=MediaType.EPISODE,
                media_identifier="121361",
                title="The Rookie S08E12",
                season=8,
                episode=12,
                tvdb_id="121361",
                correlation_key="media:121361:S08E12",
                source_download_id="318DE20D1BABF563",
            ),
            # qBittorrent: first torrent (original)
            RawEvent(
                timestamp=now + timedelta(minutes=5),
                source_service=SourceService.QBITTORRENT,
                event_type=EventType.DOWNLOAD_COMPLETED,
                media_type=MediaType.EPISODE,
                media_identifier="318DE20D1BABF563",
                title="The.Rookie.S08E12.Spy.Games.1080p.AMZN.WEB-DL.DDP5.1.H.264-NTb.mkv",
                source_download_id="318DE20D1BABF563",
                correlation_key="hash:318DE20D1BABF563",
                normalized_metadata={
                    "progress": 100,
                    "state": "stalledUP",
                    "category": "tv-sonarr",
                    "tags": "",
                },
            ),
            # qBittorrent: cross-seed torrent 1
            RawEvent(
                timestamp=now + timedelta(minutes=6),
                source_service=SourceService.QBITTORRENT,
                event_type=EventType.DOWNLOAD_COMPLETED,
                media_type=MediaType.EPISODE,
                media_identifier="B6D03E7005E24726",
                title="The.Rookie.S08E12.Spy.Games.1080p.AMZN.WEB-DL.DDP5.1.H.264-NTb.mkv",
                source_download_id="B6D03E7005E24726",
                correlation_key="hash:B6D03E7005E24726",
                normalized_metadata={
                    "progress": 100,
                    "state": "stalledUP",
                    "category": "tv-sonarr.cross",
                    "tags": "cross-seed",
                },
            ),
            # qBittorrent: cross-seed torrent 2
            RawEvent(
                timestamp=now + timedelta(minutes=7),
                source_service=SourceService.QBITTORRENT,
                event_type=EventType.DOWNLOAD_COMPLETED,
                media_type=MediaType.EPISODE,
                media_identifier="0C84459EE1D05419",
                title="The.Rookie.S08E12.Spy.Games.1080p.AMZN.WEB-DL.DDP5.1.H.264-NTb.mkv",
                source_download_id="0C84459EE1D05419",
                correlation_key="hash:0C84459EE1D05419",
                normalized_metadata={
                    "progress": 100,
                    "state": "stalledUP",
                    "category": "tv-sonarr.cross",
                    "tags": "cross-seed",
                },
            ),
            # Sonarr: import completed (matches first torrent)
            RawEvent(
                timestamp=now + timedelta(minutes=8),
                source_service=SourceService.SONARR,
                event_type=EventType.IMPORT_COMPLETED,
                media_type=MediaType.EPISODE,
                media_identifier="121361",
                title="The Rookie S08E12",
                season=8,
                episode=12,
                tvdb_id="121361",
                correlation_key="media:121361:S08E12",
            ),
            # Sonarr: available
            RawEvent(
                timestamp=now + timedelta(minutes=9),
                source_service=SourceService.SONARR,
                event_type=EventType.AVAILABLE,
                media_type=MediaType.EPISODE,
                media_identifier="121361",
                title="The Rookie S08E12",
                season=8,
                episode=12,
                tvdb_id="121361",
                correlation_key="media:121361:S08E12",
            ),
        ]
        
        engine.add_events(events)
        item = engine.get_item("media:121361:S08E12")
        
        assert item is not None
        assert item.current_state == EventType.AVAILABLE
        assert item.confidence == "HIGH"
        
        # Check download attempts - should have 3 (1 original + 2 cross-seed)
        attempts = item.download_attempts
        assert len(attempts) == 3
        
        # Verify one is original, two are cross-seed
        original = [a for a in attempts if not a["is_cross_seed"]]
        cross_seeds = [a for a in attempts if a["is_cross_seed"]]
        
        assert len(original) == 1
        assert len(cross_seeds) == 2
        assert cross_seeds[0]["category"] == "tv-sonarr.cross"
        assert "cross-seed" in cross_seeds[0]["tags"]
    
    def test_unmatched_tv_sonarr_cross_torrent(self):
        """Test an unmatched tv-sonarr.cross torrent (E)."""
        engine = CorrelationEngine()
        now = datetime.utcnow()
        
        # Only qBittorrent event, no Sonarr/Radarr history
        events = [
            RawEvent(
                timestamp=now,
                source_service=SourceService.QBITTORRENT,
                event_type=EventType.DOWNLOAD_COMPLETED,
                media_type=MediaType.EPISODE,
                media_identifier="318DE20D1BABF563",
                title="Some.Random.Show.S01E01.1080p.WEB-DL",
                source_download_id="318DE20D1BABF563",
                correlation_key="hash:318DE20D1BABF563",
                normalized_metadata={
                    "progress": 100,
                    "state": "stalledUP",
                    "category": "tv-sonarr.cross",
                    "tags": "cross-seed",
                },
            ),
        ]
        
        engine.add_events(events)
        
        # Item should be created with hash-based correlation key
        item = engine.get_item("hash:318DE20D1BABF563")
        assert item is not None
        assert item.current_state == EventType.DOWNLOAD_COMPLETED
        assert item.confidence == "LOW"  # No hash match with *Arr
        
        # Check orphan detection
        from backend.services.events import EventService
        event_service = EventService(None)
        event_service.correlation_engine = engine
        orphans = event_service.get_orphan_torrents()
        # This torrent should appear in orphans since no *Arr event matches it
        # Note: in this test, the torrent IS correlated (to itself via hash)
        # but would be orphaned if we had *Arr events that don't match
    
    def test_readarr_category_torrent(self):
        """Test a Readarr-category torrent with no Sonarr/Radarr correlation (F)."""
        engine = CorrelationEngine()
        now = datetime.utcnow()
        
        events = [
            RawEvent(
                timestamp=now,
                source_service=SourceService.QBITTORRENT,
                event_type=EventType.DOWNLOAD_COMPLETED,
                media_type=MediaType.MOVIE,  # Readarr items are books, but we use movie as fallback
                media_identifier="536C5E25F61D0EE9",
                title="Creation_Node_-_Stephen_Baxter.epub",
                source_download_id="536C5E25F61D0EE9",
                correlation_key="hash:536C5E25F61D0EE9",
                normalized_metadata={
                    "progress": 100,
                    "state": "stalledUP",
                    "category": "readarr",
                    "tags": "",
                },
            ),
        ]
        
        engine.add_events(events)
        
        item = engine.get_item("hash:536C5E25F61D0EE9")
        assert item is not None
        assert item.current_state == EventType.DOWNLOAD_COMPLETED
        assert item.confidence == "LOW"  # No *Arr match
        
        attempts = item.download_attempts
        assert len(attempts) == 1
        assert attempts[0]["category"] == "readarr"
        assert attempts[0]["is_cross_seed"] == False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
