"""Tests for API endpoints."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from datetime import datetime

from backend.main import application
from backend.adapters.base import SourceService, MediaType, EventType, EventStatus, RawEvent, ActiveItem, ServiceHealth
from backend.correlation.engine import CorrelationResult


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(application)


@pytest.fixture
def mock_adapter():
    """Mock adapter for testing."""
    with patch('backend.adapters.get_all_adapters') as mock:
        adapter = MagicMock()
        adapter.service_name = SourceService.RADARR
        adapter.health.return_value = ServiceHealth(
            service=SourceService.RADARR,
            status="healthy",
            version="4.0.0"
        )
        adapter.fetch_events.return_value = []
        adapter.fetch_active_items.return_value = []
        mock.return_value = [adapter]
        yield adapter


class TestHealthEndpoints:
    """Tests for health endpoints."""
    
    def test_health_check(self, client):
        """Test health endpoint."""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "arr-control"
    
    def test_ready_check(self, client):
        """Test readiness endpoint."""
        response = client.get("/api/ready")
        assert response.status_code == 200
        data = response.json()
        assert "ready" in data
    
    def test_health_check_v2(self, client):
        """Test alternative health endpoint."""
        response = client.get("/api/health")
        assert response.status_code == 200


class TestServicesEndpoints:
    """Tests for services endpoints."""
    
    def test_list_services(self, client, mock_adapter):
        """Test listing all services."""
        response = client.get("/api/services")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
    
    def test_get_service_status(self, client, mock_adapter):
        """Test getting specific service status."""
        response = client.get("/api/services/radarr")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "radarr"
        assert data["status"] == "healthy"
    
    def test_get_unknown_service(self, client):
        """Test getting unknown service."""
        response = client.get("/api/services/unknown")
        assert response.status_code == 500


class TestItemsEndpoints:
    """Tests for items endpoints."""
    
    def test_list_items_empty(self, client):
        """Test listing items when none exist."""
        response = client.get("/api/items")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0
    
    def test_list_items_with_filter(self, client):
        """Test filtering items."""
        response = client.get("/api/items?state=available&media_type=movie")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_get_item_not_found(self, client):
        """Test getting non-existent item."""
        response = client.get("/api/items/nonexistent")
        assert response.status_code == 404
    
    def test_get_item_timeline_not_found(self, client):
        """Test getting timeline for non-existent item."""
        response = client.get("/api/items/nonexistent/timeline")
        assert response.status_code == 404
    
    def test_get_item_explanation_not_found(self, client):
        """Test getting explanation for non-existent item."""
        response = client.get("/api/items/nonexistent/explain")
        assert response.status_code == 404


class TestEventsEndpoints:
    """Tests for events endpoints."""
    
    def test_list_events_empty(self, client):
        """Test listing events when none exist."""
        response = client.get("/api/events")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_list_events_with_filters(self, client):
        """Test filtering events."""
        response = client.get("/api/events?source_service=radarr&event_type=wanted")
        assert response.status_code == 200
    
    def test_list_events_pagination(self, client):
        """Test event pagination."""
        response = client.get("/api/events?limit=10&offset=0")
        assert response.status_code == 200


class TestForcePoll:
    """Tests for force poll endpoint."""
    
    def test_force_poll(self, client, mock_adapter):
        """Test forcing a poll."""
        response = client.post("/api/services/poll")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])