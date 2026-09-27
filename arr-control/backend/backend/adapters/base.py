"""Base adapter interface for all service integrations."""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class SourceService(str, Enum):
    SONARR = "sonarr"
    RADARR = "radarr"
    QBITTORRENT = "qbittorrent"


class MediaType(str, Enum):
    MOVIE = "movie"
    EPISODE = "episode"


class EventType(str, Enum):
    WANTED = "wanted"
    SEARCH_STARTED = "search_started"
    SEARCH_COMPLETED = "search_completed"
    SEARCH_FAILED = "search_failed"
    RELEASE_GRABBED = "release_grabbed"
    DOWNLOAD_STARTED = "download_started"
    DOWNLOAD_PROGRESS = "download_progress"
    DOWNLOAD_COMPLETED = "download_completed"
    DOWNLOAD_FAILED = "download_failed"
    IMPORT_STARTED = "import_started"
    IMPORT_COMPLETED = "import_completed"
    IMPORT_FAILED = "import_failed"
    AVAILABLE = "available"
    STUCK = "stuck"
    UNKNOWN = "unknown"


class EventStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class RawEvent:
    """Normalized event from a service adapter."""
    timestamp: datetime
    source_service: SourceService
    event_type: EventType
    media_type: MediaType
    media_identifier: str  # TVDB/TMDB/IMDb ID
    title: str
    season: Optional[int] = None
    episode: Optional[int] = None
    tvdb_id: Optional[str] = None
    tmdb_id: Optional[str] = None
    imdb_id: Optional[str] = None
    source_item_id: Optional[str] = None
    source_download_id: Optional[str] = None
    source_queue_id: Optional[str] = None
    correlation_key: Optional[str] = None
    source_payload: Optional[Dict[str, Any]] = None
    normalized_metadata: Optional[Dict[str, Any]] = None
    status: EventStatus = EventStatus.COMPLETED
    error_message: Optional[str] = None
    error_details: Optional[str] = None


@dataclass
class ActiveItem:
    """Currently active item being tracked."""
    media_type: MediaType
    media_identifier: str
    title: str
    season: Optional[int] = None
    episode: Optional[int] = None
    tvdb_id: Optional[str] = None
    tmdb_id: Optional[str] = None
    imdb_id: Optional[str] = None
    source_item_id: Optional[str] = None
    source_download_id: Optional[str] = None
    source_queue_id: Optional[str] = None
    current_state: EventType = EventType.UNKNOWN
    progress: Optional[int] = None
    current_service: Optional[SourceService] = None


@dataclass
class ServiceHealth:
    """Service health status."""
    service: SourceService
    status: str  # healthy, degraded, down
    version: Optional[str] = None
    error_message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class ServiceAdapter(ABC):
    """Base interface for service adapters."""
    
    @property
    @abstractmethod
    def service_name(self) -> SourceService:
        """Return the service name."""
        pass
    
    @abstractmethod
    def health(self) -> ServiceHealth:
        """Check service health."""
        pass
    
    @abstractmethod
    def discover(self) -> List[ActiveItem]:
        """Discover all active/tracked items from the service."""
        pass
    
    @abstractmethod
    def fetch_events(self, since: Optional[datetime] = None) -> List[RawEvent]:
        """Fetch events from the service."""
        pass
    
    @abstractmethod
    def fetch_active_items(self) -> List[ActiveItem]:
        """Fetch currently active items (queue, wanted, etc.)."""
        pass