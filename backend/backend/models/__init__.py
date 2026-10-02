from datetime import datetime
from sqlalchemy import Column, String, Integer, BigInteger, DateTime, Text, Enum as SQLEnum, Index, ForeignKey
from sqlalchemy.orm import relationship
import enum
from backend.database.base import Base


class MediaType(str, enum.Enum):
    MOVIE = "movie"
    EPISODE = "episode"


class EventType(str, enum.Enum):
    # Wanted states
    WANTED = "wanted"
    
    # Search states
    SEARCH_STARTED = "search_started"
    SEARCH_COMPLETED = "search_completed"
    SEARCH_FAILED = "search_failed"
    
    # Grab/Download states
    RELEASE_GRABBED = "release_grabbed"
    DOWNLOAD_STARTED = "download_started"
    DOWNLOAD_PROGRESS = "download_progress"
    DOWNLOAD_COMPLETED = "download_completed"
    DOWNLOAD_FAILED = "download_failed"
    
    # Import states
    IMPORT_STARTED = "import_started"
    IMPORT_COMPLETED = "import_completed"
    IMPORT_FAILED = "import_failed"
    
    # Final states
    AVAILABLE = "available"
    
    # Error/Stuck states
    STUCK = "stuck"
    UNKNOWN = "unknown"


class EventStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class SourceService(str, enum.Enum):
    SONARR = "sonarr"
    RADARR = "radarr"
    QBITTORRENT = "qbittorrent"


class RawEventModel(Base):
    """Append-only raw event log from all sources."""
    __tablename__ = "raw_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    source_service = Column(SQLEnum(SourceService), nullable=False, index=True)
    event_type = Column(SQLEnum(EventType), nullable=False, index=True)
    media_type = Column(SQLEnum(MediaType), nullable=False, index=True)
    
    # Media identifiers
    media_identifier = Column(String(255), nullable=False, index=True)  # TVDB/TMDB/IMDb ID
    title = Column(String(512), nullable=False)
    season = Column(Integer, nullable=True)
    episode = Column(Integer, nullable=True)
    
    # External IDs
    tvdb_id = Column(String(64), nullable=True, index=True)
    tmdb_id = Column(String(64), nullable=True, index=True)
    imdb_id = Column(String(64), nullable=True, index=True)
    
    # Source-specific IDs
    source_item_id = Column(String(255), nullable=True, index=True)  # Sonarr/Radarr internal ID
    source_download_id = Column(String(255), nullable=True, index=True)  # qBittorrent torrent hash
    source_queue_id = Column(String(255), nullable=True, index=True)  # Sonarr/Radarr queue ID
    
    # Correlation
    correlation_key = Column(String(255), nullable=True, index=True)  # Computed correlation key
    
    # Normalized metadata / raw payload
    source_payload = Column(Text, nullable=True)  # JSON string of original event
    normalized_metadata = Column(Text, nullable=True)  # JSON string of normalized data
    
    # Status
    status = Column(SQLEnum(EventStatus), nullable=False, default=EventStatus.COMPLETED)
    error_message = Column(Text, nullable=True)
    error_details = Column(Text, nullable=True)
    
    # Processing
    processed = Column(Integer, nullable=False, default=0)  # 0 = unprocessed, 1 = processed
    processed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_raw_events_correlation_media", "correlation_key", "media_type"),
        Index("ix_raw_events_source_item", "source_service", "source_item_id"),
        Index("ix_raw_events_source_download", "source_service", "source_download_id"),
        Index("ix_raw_events_timestamp_source", "timestamp", "source_service"),
    )


class MediaItemModel(Base):
    """Unified media item with correlated state."""
    __tablename__ = "media_items"

    id = Column(String(64), primary_key=True)  # Correlation key
    media_type = Column(SQLEnum(MediaType), nullable=False, index=True)
    media_identifier = Column(String(255), nullable=False, index=True)  # TVDB/TMDB/IMDb
    title = Column(String(512), nullable=False)
    season = Column(Integer, nullable=True)
    episode = Column(Integer, nullable=True)
    
    # External IDs
    tvdb_id = Column(String(64), nullable=True, index=True)
    tmdb_id = Column(String(64), nullable=True, index=True)
    imdb_id = Column(String(64), nullable=True, index=True)
    
    # Current state
    current_state = Column(SQLEnum(EventType), nullable=False, default=EventType.UNKNOWN)
    current_status = Column(SQLEnum(EventStatus), nullable=False, default=EventStatus.PENDING)
    progress = Column(Integer, nullable=True)  # 0-100 for downloads
    
    # Current service handling
    current_service = Column(SQLEnum(SourceService), nullable=True)
    
    # Source IDs
    sonarr_id = Column(String(255), nullable=True, index=True)
    radarr_id = Column(String(255), nullable=True, index=True)
    qbittorrent_hash = Column(String(64), nullable=True, index=True)
    queue_id = Column(String(255), nullable=True, index=True)
    
    # Timestamps
    first_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_event_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Error tracking
    last_error = Column(Text, nullable=True)
    error_count = Column(Integer, nullable=False, default=0)
    
    # Next expected state
    next_expected_state = Column(SQLEnum(EventType), nullable=True)
    
    # Relationship to events (no FK constraint - correlation is by key, not DB FK)
    # events = relationship("RawEventModel", backref="media_item", lazy="dynamic",
    #                       primaryjoin="and_(MediaItemModel.id==RawEventModel.correlation_key, MediaItemModel.media_type==RawEventModel.media_type)")

    __table_args__ = (
        Index("ix_media_items_type_identifier", "media_type", "media_identifier"),
        Index("ix_media_items_state_service", "current_state", "current_service"),
    )


class ServiceHealthModel(Base):
    """Track service health status."""
    __tablename__ = "service_health"

    id = Column(Integer, primary_key=True, autoincrement=True)
    service = Column(SQLEnum(SourceService), nullable=False, unique=True, index=True)
    status = Column(String(32), nullable=False)  # healthy, degraded, down
    last_check_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_success_at = Column(DateTime, nullable=True)
    consecutive_failures = Column(Integer, nullable=False, default=0)
    version = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    details = Column(Text, nullable=True)  # JSON