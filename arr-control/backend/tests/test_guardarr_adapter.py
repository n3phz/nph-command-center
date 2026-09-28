"""Tests for Guardarr adapter."""
import pytest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

from backend.adapters.guardarr import GuardarrAdapter
from backend.adapters.base import SourceService, MediaType, EventType, EventStatus, RawEvent


class TestGuardarrAdapter:
    """Test Guardarr adapter."""

    @pytest.fixture
    def adapter(self):
        """Create a Guardarr adapter with mocked settings."""
        adapter = GuardarrAdapter()
        adapter.base_url = "http://guardarr:8000"
        adapter.api_key = "test-api-key"
        adapter.session = Mock()
        return adapter

    def test_service_name(self, adapter):
        """Test service name property."""
        assert adapter.service_name == SourceService.GUARDARR

    def test_health_healthy(self, adapter):
        """Test health check when service is healthy."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"version": "0.1.2", "status": "ok"}
        adapter.session.get.return_value = mock_response

        health = adapter.health()

        assert health.service == SourceService.GUARDARR
        assert health.status == "healthy"
        assert health.version == "0.1.2"

    def test_health_degraded(self, adapter):
        """Test health check when service returns error."""
        mock_response = Mock()
        mock_response.status_code = 500
        adapter.session.get.return_value = mock_response

        health = adapter.health()

        assert health.status == "degraded"
        assert "HTTP 500" in health.error_message

    def test_health_down(self, adapter):
        """Test health check when service is unreachable."""
        adapter.session.get.side_effect = Exception("Connection refused")

        health = adapter.health()

        assert health.status == "down"
        assert "Connection refused" in health.error_message

    def test_health_not_configured(self, adapter):
        """Test health check when not configured."""
        adapter.base_url = ""
        adapter.api_key = ""

        health = adapter.health()

        assert health.status == "down"
        assert "not configured" in health.error_message

    def test_reservation_to_event_admitted(self, adapter):
        """Test conversion of admitted reservation to event."""
        reservation = {
            "reservation_id": "res-123",
            "state": "admitted",
            "content_id": "content-456",
            "arr_item_id": "movie-789",
            "torrent_metadata_hash": "abc123",
            "associated_path": "/data/movies/Movie",
            "target_device": "/data",
            "max_bytes": 1000000000,
            "expected_bytes": 1000000000,
            "observed_materialized_bytes": 500000000,
            "remaining_unfulfilled_bytes": 500000000,
            "import_mode": "move",
            "priority": 1,
            "owner": "radarr",
            "torrent_tag": "radarr",
            "idempotency_key": "idem-123",
            "updated_at": "2026-09-27T10:00:00Z",
            "created_at": "2026-09-27T09:00:00Z",
        }

        event = adapter._reservation_to_event(reservation)

        assert event is not None
        assert event.event_type == EventType.STORAGE_ADMIT
        assert event.correlation_key == "guardarr:content-456"
        assert event.source_download_id == "abc123"
        assert event.normalized_metadata["guardarr_event_type"] == "admitted"
        assert event.normalized_metadata["reservation_id"] == "res-123"

    def test_reservation_to_event_pending(self, adapter):
        """Test conversion of pending reservation to event."""
        reservation = {
            "state": "pending",
            "content_id": "content-456",
            "updated_at": "2026-09-27T10:00:00Z",
        }

        event = adapter._reservation_to_event(reservation)

        assert event is not None
        assert event.event_type == EventType.STORAGE_ESTIMATE

    def test_reservation_to_event_released(self, adapter):
        """Test conversion of released reservation to event."""
        reservation = {
            "state": "released",
            "content_id": "content-456",
            "updated_at": "2026-09-27T10:00:00Z",
        }

        event = adapter._reservation_to_event(reservation)

        assert event is not None
        assert event.event_type == EventType.STORAGE_RELEASE

    def test_reservation_to_event_reconciled(self, adapter):
        """Test conversion of reconciled reservation to event."""
        reservation = {
            "state": "reconciled",
            "content_id": "content-456",
            "updated_at": "2026-09-27T10:00:00Z",
        }

        event = adapter._reservation_to_event(reservation)

        assert event is not None
        assert event.event_type == EventType.STORAGE_RECONCILE

    def test_reservation_to_event_imported(self, adapter):
        """Test conversion of imported reservation to event."""
        reservation = {
            "state": "imported",
            "content_id": "content-456",
            "updated_at": "2026-09-27T10:00:00Z",
        }

        event = adapter._reservation_to_event(reservation)

        assert event is not None
        assert event.event_type == EventType.IMPORT_COMPLETED

    def test_reservation_to_event_failed(self, adapter):
        """Test conversion of failed reservation to event."""
        reservation = {
            "state": "failed",
            "content_id": "content-456",
            "updated_at": "2026-09-27T10:00:00Z",
        }

        event = adapter._reservation_to_event(reservation)

        assert event is not None
        assert event.event_type == EventType.SECURITY_BLOCKED

    def test_reservation_to_event_unknown_state(self, adapter):
        """Test conversion of unknown state reservation."""
        reservation = {
            "state": "unknown_state",
            "content_id": "content-456",
            "updated_at": "2026-09-27T10:00:00Z",
        }

        event = adapter._reservation_to_event(reservation)

        assert event is not None
        assert event.event_type == EventType.UNKNOWN

    def test_unreserved_torrent_to_event(self, adapter):
        """Test conversion of unreserved torrent to event."""
        torrent = {
            "hash": "torrent-hash-123",
            "name": "Movie.Torrent.mkv",
            "size": 1000000000,
            "progress": 100,
            "state": "stalledUP",
            "tags": ["radarr"],
            "save_path": "/data/torrents",
        }

        event = adapter._unreserved_torrent_to_event(torrent)

        assert event is not None
        assert event.event_type == EventType.TORRENT_UNRESERVED
        assert event.correlation_key == "hash:torrent-hash-123"
        assert event.source_download_id == "torrent-hash-123"
        assert event.title == "Movie.Torrent.mkv"
        assert event.normalized_metadata["guardarr_event_type"] == "torrent_unreserved"
        assert event.normalized_metadata["torrent_hash"] == "torrent-hash-123"

    def test_fetch_events_reservations(self, adapter):
        """Test fetching events from reservations."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "reservation_id": "res-1",
                "state": "admitted",
                "content_id": "content-1",
                "updated_at": "2026-09-27T10:00:00Z",
            }
        ]
        adapter.session.get.return_value = mock_response

        events = adapter.fetch_events()

        assert len(events) == 1
        assert events[0].event_type == EventType.STORAGE_ADMIT
        assert events[0].correlation_key == "guardarr:content-1"

    def test_fetch_events_unreserved_torrents(self, adapter):
        """Test fetching events from unreserved torrents."""
        mock_response1 = Mock()
        mock_response1.status_code = 200
        mock_response1.json.return_value = []

        mock_response2 = Mock()
        mock_response2.status_code = 200
        mock_response2.json.return_value = {
            "unreserved_torrents": [
                {
                    "hash": "hash-123",
                    "name": "Test.mkv",
                    "size": 1000000,
                    "progress": 100,
                    "state": "completed",
                    "tags": [],
                    "save_path": "/data/torrents",
                }
            ]
        }

        adapter.session.get.side_effect = [mock_response1, mock_response2]

        events = adapter.fetch_events()

        assert len(events) == 1
        assert events[0].event_type == EventType.TORRENT_UNRESERVED

    def test_discover(self, adapter):
        """Test discovering active items."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "reservation_id": "res-1",
                "content_id": "content-1",
                "arr_item_id": "movie-1",
                "torrent_metadata_hash": "hash-1",
                "state": "admitted",
            }
        ]
        adapter.session.get.return_value = mock_response

        items = adapter.discover()

        assert len(items) == 1
        assert items[0].source_item_id == "res-1"
        assert items[0].current_service == SourceService.GUARDARR


if __name__ == "__main__":
    pytest.main([__file__, "-v"])