"""Test fixtures and utilities."""
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.database.base import Base, get_db
from backend.models import RawEventModel, MediaType, SourceService, EventType, EventStatus


@pytest.fixture(scope="session")
def test_db():
    """Create a test database in a temporary location."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(bind=engine)
        
        yield engine
        
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(test_db):
    """Create a database session for each test."""
    Connection = sessionmaker(bind=test_db)
    session = Connection()
    
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture
def sample_movie_event():
    """Create a sample movie event."""
    return {
        "timestamp": datetime.utcnow(),
        "source_service": SourceService.RADARR,
        "event_type": EventType.WANTED,
        "media_type": MediaType.MOVIE,
        "media_identifier": "157336",  # TMDB ID for Dune
        "title": "Dune: Part Two (2024)",
        "tmdb_id": "157336",
        "correlation_key": "tmdb:157336",
        "source_item_id": "12345",
        "source_payload": {"id": 12345, "title": "Dune: Part Two"}
    }


@pytest.fixture
def sample_episode_event():
    """Create a sample episode event."""
    return {
        "timestamp": datetime.utcnow(),
        "source_service": SourceService.SONARR,
        "event_type": EventType.WANTED,
        "media_type": MediaType.EPISODE,
        "media_identifier": "121361",  # TVDB ID for The Last of Us
        "title": "The Last of Us S01E01",
        "season": 1,
        "episode": 1,
        "tvdb_id": "121361",
        "correlation_key": "tvdb:121361:S01E01",
        "source_item_id": "67890",
        "source_payload": {"id": 67890, "title": "The Last of Us"}
    }


@pytest.fixture
def sample_torrent_event():
    """Create a sample qBittorrent event."""
    return {
        "timestamp": datetime.utcnow(),
        "source_service": SourceService.QBITTORRENT,
        "event_type": EventType.DOWNLOAD_PROGRESS,
        "media_type": MediaType.MOVIE,
        "media_identifier": "a]b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9",
        "title": "Dune.Part.Two.2024.2160p.WEB-DL.DDP5.1.H.264-FLUX",
        "source_download_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
        "correlation_key": "hash:a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
        "source_payload": {
            "name": "Dune.Part.Two.2024.2160p.WEB-DL.DDP5.1.H.264-FLUX",
            "hash": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
            "progress": 0.74,
            "state": "downloading"
        },
        "normalized_metadata": {
            "progress": 74,
            "state": "downloading",
            "size": 15000000000
        }
    }


@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    with patch('backend.core.config.get_settings') as mock:
        settings = MagicMock()
        settings.sonarr_url = "http://localhost:8989"
        settings.sonarr_api_key = "test_key"
        settings.sonarr_timeout_seconds = 10
        settings.sonarr_verify_tls = True
        settings.radarr_url = "http://localhost:7878"
        settings.radarr_api_key = "test_key"
        settings.radarr_timeout_seconds = 10
        settings.radarr_verify_tls = True
        settings.qbittorrent_url = "http://localhost:8080"
        settings.qbittorrent_username = "admin"
        settings.qbittorrent_password = "password"
        settings.qbittorrent_timeout_seconds = 10
        settings.qbittorrent_verify_tls = True
        settings.data_dir = Path(tempfile.mkdtemp())
        settings.database_url = f"sqlite:///{tempfile.mktemp()}.db"
        settings.poll_interval_seconds = 30
        settings.poll_timeout_seconds = 10
        settings.app_name = "arr-control"
        settings.app_version = "0.1.0"
        settings.environment = "test"
        settings.debug = True
        mock.return_value = settings
        yield mock