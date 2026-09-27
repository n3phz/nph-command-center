"""Tests for event matching."""
import pytest
from datetime import datetime

from backend.adapters.base import SourceService, MediaType, EventType, EventStatus, RawEvent
from backend.correlation.matching import match_torrent_to_media, find_candidate_events, _normalize_title


class TestTitleMatching:
    """Tests for title matching utilities."""
    
    def test_normalize_title(self):
        """Test title normalization."""
        assert _normalize_title("Dune: Part Two") == "dune part two"
        assert _normalize_title("Dune.Part.Two") == "dune part two"
        assert _normalize_title("Dune - Part Two") == "dune part two"
        assert _normalize_title("  Dune:  Part  Two  ") == "dune part two"
    
    def test_match_exact_title(self):
        """Test exact title match."""
        torrent = RawEvent(
            timestamp=datetime.utcnow(),
            source_service=SourceService.QBITTORRENT,
            event_type=EventType.DOWNLOAD_PROGRESS,
            media_type=MediaType.MOVIE,
            media_identifier="abc123",
            title="Dune.Part.Two.2024"
        )
        
        candidate = RawEvent(
            timestamp=datetime.utcnow(),
            source_service=SourceService.RADARR,
            event_type=EventType.WANTED,
            media_type=MediaType.MOVIE,
            media_identifier="157336",
            title="Dune: Part Two"
        )
        
        result = match_torrent_to_media(torrent, [candidate])
        assert result is not None
        assert result[0] == torrent
        assert result[1] == candidate
    
    def test_match_by_hash(self):
        """Test matching by source_download_id."""
        torrent = RawEvent(
            timestamp=datetime.utcnow(),
            source_service=SourceService.QBITTORRENT,
            event_type=EventType.DOWNLOAD_PROGRESS,
            media_type=MediaType.MOVIE,
            media_identifier="abc123",
            title="Dune.Part.Two",
            source_download_id="hash123",
            correlation_key="hash:hash123"
        )
        
        candidate = RawEvent(
            timestamp=datetime.utcnow(),
            source_service=SourceService.RADARR,
            event_type=EventType.RELEASE_GRABBED,
            media_type=MediaType.MOVIE,
            media_identifier="157336",
            title="Dune: Part Two",
            correlation_key="hash:hash123"
        )
        
        result = match_torrent_to_media(torrent, [candidate])
        assert result is not None
    
    def test_no_match(self):
        """Test when no match is found."""
        torrent = RawEvent(
            timestamp=datetime.utcnow(),
            source_service=SourceService.QBITTORRENT,
            event_type=EventType.DOWNLOAD_PROGRESS,
            media_type=MediaType.MOVIE,
            media_identifier="xyz",
            title="Completely Different Movie"
        )
        
        candidate = RawEvent(
            timestamp=datetime.utcnow(),
            source_service=SourceService.RADARR,
            event_type=EventType.WANTED,
            media_type=MediaType.MOVIE,
            media_identifier="157336",
            title="Dune: Part Two"
        )
        
        result = match_torrent_to_media(torrent, [candidate])
        assert result is None


class TestFindCandidates:
    """Tests for finding candidate events."""
    
    def test_find_by_correlation_key(self):
        """Test finding candidates by correlation key."""
        event1 = RawEvent(
            timestamp=datetime.utcnow(),
            source_service=SourceService.RADARR,
            event_type=EventType.WANTED,
            media_type=MediaType.MOVIE,
            media_identifier="157336",
            title="Dune: Part Two",
            correlation_key="tmdb:157336"
        )
        
        event2 = RawEvent(
            timestamp=datetime.utcnow(),
            source_service=SourceService.QBITTORRENT,
            event_type=EventType.DOWNLOAD_STARTED,
            media_type=MediaType.MOVIE,
            media_identifier="157336",
            title="Dune.Part.Two",
            correlation_key="tmdb:157336"
        )
        
        candidates = find_candidate_events(event1, [event2])
        assert len(candidates) == 1
        assert candidates[0] == event2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])