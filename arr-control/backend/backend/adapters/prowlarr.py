"""Prowlarr adapter for fetching events and indexer health."""
import logging
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime
from urllib.parse import urljoin

from backend.adapters.base import (
    ServiceAdapter, SourceService, MediaType, EventType, EventStatus,
    RawEvent, ActiveItem, ServiceHealth
)
from backend.core.config import get_settings

logger = logging.getLogger("arr-control.adapters.prowlarr")


class ProwlarrAdapter(ServiceAdapter):
    """Prowlarr API adapter."""
    
    @property
    def service_name(self) -> SourceService:
        return SourceService.PROWLARR
    
    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.prowlarr_url.rstrip("/") if hasattr(self.settings, 'prowlarr_url') else ""
        self.api_key = self.settings.prowlarr_api_key if hasattr(self.settings, 'prowlarr_api_key') else ""
        self.timeout = self.settings.prowlarr_timeout_seconds if hasattr(self.settings, 'prowlarr_timeout_seconds') else 10
        self.verify_tls = self.settings.prowlarr_verify_tls if hasattr(self.settings, 'prowlarr_verify_tls') else True
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({
                "X-Api-Key": self.api_key,
                "Accept": "application/json"
            })
    
    def health(self) -> ServiceHealth:
        """Check Prowlarr connectivity."""
        if not self.base_url or not self.api_key:
            return ServiceHealth(
                service=SourceService.PROWLARR,
                status="down",
                error_message="Prowlarr not configured"
            )
        
        try:
            response = self.session.get(
                urljoin(self.base_url, "/api/v1/system/status"),
                timeout=self.timeout,
                verify=self.verify_tls
            )
            if response.status_code == 200:
                data = response.json()
                return ServiceHealth(
                    service=SourceService.PROWLARR,
                    status="healthy",
                    version=data.get("version"),
                    details=data
                )
            return ServiceHealth(
                service=SourceService.PROWLARR,
                status="degraded",
                error_message=f"HTTP {response.status_code}"
            )
        except Exception as e:
            logger.error(f"Prowlarr health check failed: {e}")
            return ServiceHealth(
                service=SourceService.PROWLARR,
                status="down",
                error_message=str(e)
            )
    
    def discover(self) -> List[ActiveItem]:
        """Discover indexers from Prowlarr."""
        items = []
        if not self.base_url or not self.api_key:
            return items
        
        try:
            response = self.session.get(
                urljoin(self.base_url, "/api/v1/indexer"),
                timeout=self.timeout,
                verify=self.verify_tls
            )
            if response.status_code != 200:
                return items
            
            indexers = response.json()
            
            for indexer in indexers:
                items.append(self._indexer_to_item(indexer))
        except Exception as e:
            logger.error(f"Prowlarr discover failed: {e}")
        
        return items
    
    def fetch_events(self, since: Optional[datetime] = None) -> List[RawEvent]:
        """Fetch events from Prowlarr based on history/failed searches."""
        events = []
        if not self.base_url or not self.api_key:
            return events
        
        try:
            # Fetch history
            params = {"page": 1, "pageSize": 100}
            if since:
                params["startDate"] = since.isoformat() + "Z"
            
            response = self.session.get(
                urljoin(self.base_url, "/api/v1/history"),
                params=params,
                timeout=self.timeout,
                verify=self.verify_tls
            )
            if response.status_code == 200:
                history = response.json()
                for record in history.get("records", []):
                    event = self._history_to_event(record)
                    if event:
                        events.append(event)
        except Exception as e:
            logger.error(f"Prowlarr events fetch failed: {e}")
        
        return events
    
    def fetch_active_items(self) -> List[ActiveItem]:
        """Fetch currently active indexers."""
        return self.discover()
    
    def _indexer_to_item(self, indexer: Dict[str, Any]) -> ActiveItem:
        """Convert an indexer to an ActiveItem."""
        return ActiveItem(
            media_type=MediaType.MOVIE,
            media_identifier=str(indexer.get("id", "")),
            title=indexer.get("name", "Unknown"),
            source_item_id=str(indexer.get("id", "")),
            current_state=EventType.UNKNOWN,
            current_service=SourceService.PROWLARR,
            source_payload=indexer
        )
    
    def _history_to_event(self, record: Dict[str, Any]) -> Optional[RawEvent]:
        """Convert a history record to a RawEvent."""
        event_type_str = record.get("eventType", "").lower()
        
        # Map Prowlarr event types to our EventType
        event_type_map = {
            "grab": EventType.RELEASE_GRABBED,
            "download": EventType.DOWNLOAD_STARTED,
            "import": EventType.IMPORT_STARTED,
            "rename": EventType.UNKNOWN,
            "applicationupdate": EventType.APPLICATION_UPDATE,
            "healthissue": EventType.HEALTH_ISSUE,
            "healthrestored": EventType.HEALTH_RESTORED,
            "indexersearch": EventType.INDEXER_SEARCH,
            "indexersearchcompleted": EventType.INDEXER_SEARCH_COMPLETED,
            "indexersearchfailed": EventType.INDEXER_SEARCH_FAILED,
            "releaserejected": EventType.RELEASE_REJECTED,
        }
        
        event_type = event_type_map.get(event_type_str, EventType.UNKNOWN)
        
        # Determine media type
        movie_id = record.get("movieId")
        series_id = record.get("seriesId")
        
        if series_id:
            media_type = MediaType.EPISODE
        else:
            media_type = MediaType.MOVIE
        
        # Get identifiers
        download_id = record.get("downloadId")
        release_title = record.get("releaseTitle", "Unknown")
        
        # Use release title as title if available
        title = release_title
        if movie_id:
            title = f"Movie {movie_id} - {release_title}"
        elif series_id:
            episode_id = record.get("episodeId", 0)
            season = record.get("seasonNumber", 0)
            episode = record.get("episodeNumber", 0)
            title = f"Series {series_id} S{season:02d}E{episode:02d} - {release_title}"
        
        # Parse timestamp
        timestamp_str = record.get("date", record.get("timestamp", ""))
        try:
            timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except:
            timestamp = datetime.utcnow()
        
        return RawEvent(
            timestamp=timestamp,
            source_service=SourceService.PROWLARR,
            event_type=event_type,
            media_type=media_type,
            media_identifier=str(movie_id or series_id or download_id or "unknown"),
            title=title,
            source_download_id=download_id,
            source_item_id=str(movie_id or series_id or ""),
            correlation_key=f"prowlarr:{download_id}" if download_id else None,
            source_payload=record,
            normalized_metadata={
                "prowlarr_event_type": event_type_str,
                "release_title": release_title,
                "movie_id": movie_id,
                "series_id": series_id,
                "episode_id": record.get("episodeId"),
                "season_number": record.get("seasonNumber"),
                "episode_number": record.get("episodeNumber"),
                "quality": record.get("quality"),
                "indexer": record.get("indexer"),
                "indexer_flags": record.get("indexerFlags"),
                "download_client": record.get("downloadClient"),
            },
            status=EventStatus.COMPLETED
        )


def get_prowlarr_adapter() -> ProwlarrAdapter:
    """Get or create the Prowlarr adapter singleton."""
    return ProwlarrAdapter()