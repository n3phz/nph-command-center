"""Radarr adapter for fetching events and active items."""
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

logger = logging.getLogger("arr-control.adapters.radarr")


class RadarrAdapter(ServiceAdapter):
    """Radarr API adapter."""
    
    @property
    def service_name(self) -> SourceService:
        return SourceService.RADARR
    
    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.radarr_url.rstrip("/")
        self.api_key = self.settings.radarr_api_key
        self.timeout = self.settings.radarr_timeout_seconds
        self.verify_tls = self.settings.radarr_verify_tls
        self.session = requests.Session()
        self.session.headers.update({
            "X-Api-Key": self.api_key,
            "Accept": "application/json"
        })
    
    def health(self) -> ServiceHealth:
        """Check Radarr connectivity."""
        try:
            response = self.session.get(
                urljoin(self.base_url, "/api/v3/system/status"),
                timeout=self.timeout,
                verify=self.verify_tls
            )
            if response.status_code == 200:
                data = response.json()
                return ServiceHealth(
                    service=SourceService.RADARR,
                    status="healthy",
                    version=data.get("version"),
                    details=data
                )
            return ServiceHealth(
                service=SourceService.RADARR,
                status="degraded",
                error_message=f"HTTP {response.status_code}"
            )
        except Exception as e:
            logger.error(f"Radarr health check failed: {e}")
            return ServiceHealth(
                service=SourceService.RADARR,
                status="down",
                error_message=str(e)
            )
    
    def discover(self) -> List[ActiveItem]:
        """Discover all movies from Radarr."""
        items = []
        try:
            response = self.session.get(
                urljoin(self.base_url, "/api/v3/movie"),
                timeout=self.timeout,
                verify=self.verify_tls
            )
            if response.status_code != 200:
                return items
            
            movies = response.json()
            
            for movie in movies:
                tmdb_id = str(movie.get("tmdbId", ""))
                imdb_id = movie.get("imdbId", "")
                title = movie.get("title", "Unknown")
                year = movie.get("year", "")
                has_file = movie.get("hasFile", False)
                monitored = movie.get("monitored", False)
                
                if has_file or monitored:
                    items.append(ActiveItem(
                        media_type=MediaType.MOVIE,
                        media_identifier=tmdb_id,
                        title=f"{title} ({year})" if year else title,
                        tmdb_id=tmdb_id,
                        imdb_id=imdb_id,
                        source_item_id=str(movie.get("id")),
                        current_state=EventType.AVAILABLE if has_file else EventType.WANTED,
                        current_service=SourceService.RADARR
                    ))
        except Exception as e:
            logger.error(f"Radarr discover failed: {e}")
        
        return items
    
    def fetch_events(self, since: Optional[datetime] = None) -> List[RawEvent]:
        """Fetch events from Radarr history and queue."""
        events = []
        
        # Fetch history
        events.extend(self._fetch_history(since))
        
        # Fetch queue
        events.extend(self._fetch_queue())
        
        # Fetch wanted/missing
        events.extend(self._fetch_wanted(since))
        
        return events
    
    def _fetch_history(self, since: Optional[datetime] = None) -> List[RawEvent]:
        """Fetch Radarr history events."""
        events = []
        try:
            params = {"page": 1, "pageSize": 100}
            if since:
                params["startDate"] = since.isoformat()
            
            response = self.session.get(
                urljoin(self.base_url, "/api/v3/history"),
                params=params,
                timeout=self.timeout,
                verify=self.verify_tls
            )
            if response.status_code != 200:
                return events
            
            data = response.json()
            records = data.get("records", [])
            
            for record in records:
                event_type = record.get("eventType", "").lower()
                mapped_type = self._map_history_event_type(event_type)
                if not mapped_type:
                    continue
                
                movie = record.get("movie", {})
                
                tmdb_id = str(movie.get("tmdbId", ""))
                imdb_id = movie.get("imdbId", "")
                title = movie.get("title", "Unknown")
                year = movie.get("year", "")
                
                # Build correlation key: tmdb_id
                corr_key = f"tmdb:{tmdb_id}"
                
                events.append(RawEvent(
                    timestamp=datetime.fromisoformat(record.get("date", "").replace("Z", "+00:00")),
                    source_service=SourceService.RADARR,
                    event_type=mapped_type,
                    media_type=MediaType.MOVIE,
                    media_identifier=tmdb_id,
                    title=f"{title} ({year})" if year else title,
                    tmdb_id=tmdb_id,
                    imdb_id=imdb_id,
                    source_item_id=str(movie.get("id")),
                    source_queue_id=str(record.get("id")),
                    correlation_key=corr_key,
                    source_payload=record,
                    status=EventStatus.COMPLETED if "failed" not in event_type.lower() else EventStatus.FAILED,
                    error_message=record.get("details") if "failed" in event_type.lower() else None
                ))
        except Exception as e:
            logger.error(f"Radarr history fetch failed: {e}")
        
        return events
    
    def _fetch_queue(self) -> List[RawEvent]:
        """Fetch Radarr queue (active downloads/imports)."""
        events = []
        try:
            response = self.session.get(
                urljoin(self.base_url, "/api/v3/queue"),
                params={"page": 1, "pageSize": 100},
                timeout=self.timeout,
                verify=self.verify_tls
            )
            if response.status_code != 200:
                return events
            
            data = response.json()
            records = data.get("records", [])
            
            for record in records:
                movie = record.get("movie", {})
                
                tmdb_id = str(movie.get("tmdbId", ""))
                imdb_id = movie.get("imdbId", "")
                title = movie.get("title", "Unknown")
                year = movie.get("year", "")
                
                status = record.get("status", "").lower()
                mapped_type = self._map_queue_status(status)
                
                progress = record.get("sizeleft", 0)
                size = record.get("size", 1)
                if size > 0:
                    progress_pct = int((1 - progress / size) * 100)
                else:
                    progress_pct = 0
                
                corr_key = f"tmdb:{tmdb_id}"
                
                events.append(RawEvent(
                    timestamp=datetime.utcnow(),
                    source_service=SourceService.RADARR,
                    event_type=mapped_type,
                    media_type=MediaType.MOVIE,
                    media_identifier=tmdb_id,
                    title=f"{title} ({year})" if year else title,
                    tmdb_id=tmdb_id,
                    imdb_id=imdb_id,
                    source_item_id=str(movie.get("id")),
                    source_queue_id=str(record.get("id")),
                    correlation_key=corr_key,
                    source_payload=record,
                    normalized_metadata={"progress": progress_pct, "status": status},
                    status=EventStatus.IN_PROGRESS
                ))
        except Exception as e:
            logger.error(f"Radarr queue fetch failed: {e}")
        
        return events
    
    def _fetch_wanted(self, since: Optional[datetime] = None) -> List[RawEvent]:
        """Fetch wanted/missing movies from Radarr."""
        events = []
        try:
            params = {"page": 1, "pageSize": 100, "monitored": "true"}
            response = self.session.get(
                urljoin(self.base_url, "/api/v3/wanted/missing"),
                params=params,
                timeout=self.timeout,
                verify=self.verify_tls
            )
            if response.status_code != 200:
                return events
            
            data = response.json()
            records = data.get("records", [])
            
            for record in records:
                tmdb_id = str(record.get("movie", {}).get("tmdbId", ""))
                imdb_id = record.get("movie", {}).get("imdbId", "")
                title = record.get("movie", {}).get("title", "Unknown")
                year = record.get("movie", {}).get("year", "")
                
                corr_key = f"tmdb:{tmdb_id}"
                
                events.append(RawEvent(
                    timestamp=datetime.utcnow(),
                    source_service=SourceService.RADARR,
                    event_type=EventType.WANTED,
                    media_type=MediaType.MOVIE,
                    media_identifier=tmdb_id,
                    title=f"{title} ({year})" if year else title,
                    tmdb_id=tmdb_id,
                    imdb_id=imdb_id,
                    source_item_id=str(record.get("movie", {}).get("id")),
                    correlation_key=corr_key,
                    source_payload=record,
                    status=EventStatus.PENDING
                ))
        except Exception as e:
            logger.error(f"Radarr wanted fetch failed: {e}")
        
        return events
    
    def fetch_active_items(self) -> List[ActiveItem]:
        """Fetch currently active items (queue + wanted)."""
        items = []
        
        # Queue items
        try:
            response = self.session.get(
                urljoin(self.base_url, "/api/v3/queue"),
                params={"page": 1, "pageSize": 100},
                timeout=self.timeout,
                verify=self.verify_tls
            )
            if response.status_code == 200:
                data = response.json()
                for record in data.get("records", []):
                    movie = record.get("movie", {})
                    tmdb_id = str(movie.get("tmdbId", ""))
                    imdb_id = movie.get("imdbId", "")
                    title = movie.get("title", "Unknown")
                    year = movie.get("year", "")
                    status = record.get("status", "").lower()
                    
                    progress = record.get("sizeleft", 0)
                    size = record.get("size", 1)
                    progress_pct = int((1 - progress / size) * 100) if size > 0 else 0
                    
                    items.append(ActiveItem(
                        media_type=MediaType.MOVIE,
                        media_identifier=tmdb_id,
                        title=f"{title} ({year})" if year else title,
                        tmdb_id=tmdb_id,
                        imdb_id=imdb_id,
                        source_item_id=str(movie.get("id")),
                        source_queue_id=str(record.get("id")),
                        current_state=self._map_queue_status(status),
                        progress=progress_pct,
                        current_service=SourceService.RADARR
                    ))
        except Exception as e:
            logger.error(f"Radarr active queue fetch failed: {e}")
        
        return items
    
    def _map_history_event_type(self, event_type: str) -> Optional[EventType]:
        """Map Radarr history event types to our unified types."""
        mapping = {
            "grabbed": EventType.RELEASE_GRABBED,
            "downloadfailed": EventType.DOWNLOAD_FAILED,
            "downloadimported": EventType.IMPORT_COMPLETED,
            "downloadimportfailed": EventType.IMPORT_FAILED,
            "moviefileimported": EventType.IMPORT_COMPLETED,
            "moviefileimportfailed": EventType.IMPORT_FAILED,
            "upgrade": EventType.RELEASE_GRABBED,
        }
        return mapping.get(event_type.lower())
    
    def _map_queue_status(self, status: str) -> EventType:
        """Map Radarr queue status to our unified types."""
        mapping = {
            "downloading": EventType.DOWNLOAD_PROGRESS,
            "importing": EventType.IMPORT_STARTED,
            "completed": EventType.DOWNLOAD_COMPLETED,
            "failed": EventType.DOWNLOAD_FAILED,
            "delayed": EventType.STUCK,
            "paused": EventType.STUCK,
        }
        return mapping.get(status.lower(), EventType.UNKNOWN)