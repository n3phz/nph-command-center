"""Sonarr adapter for fetching events and active items."""
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

logger = logging.getLogger("arr-control.adapters.sonarr")


class SonarrAdapter(ServiceAdapter):
    """Sonarr API adapter."""
    
    @property
    def service_name(self) -> SourceService:
        return SourceService.SONARR
    
    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.sonarr_url.rstrip("/")
        self.api_key = self.settings.sonarr_api_key
        self.timeout = self.settings.sonarr_timeout_seconds
        self.verify_tls = self.settings.sonarr_verify_tls
        self.session = requests.Session()
        self.session.headers.update({
            "X-Api-Key": self.api_key,
            "Accept": "application/json"
        })
    
    def health(self) -> ServiceHealth:
        """Check Sonarr connectivity."""
        try:
            response = self.session.get(
                urljoin(self.base_url, "/api/v3/system/status"),
                timeout=self.timeout,
                verify=self.verify_tls
            )
            if response.status_code == 200:
                data = response.json()
                return ServiceHealth(
                    service=SourceService.SONARR,
                    status="healthy",
                    version=data.get("version"),
                    details=data
                )
            return ServiceHealth(
                service=SourceService.SONARR,
                status="degraded",
                error_message=f"HTTP {response.status_code}"
            )
        except Exception as e:
            logger.error(f"Sonarr health check failed: {e}")
            return ServiceHealth(
                service=SourceService.SONARR,
                status="down",
                error_message=str(e)
            )
    
    def discover(self) -> List[ActiveItem]:
        """Discover all series and episodes from Sonarr."""
        items = []
        try:
            # Get all series
            response = self.session.get(
                urljoin(self.base_url, "/api/v3/series"),
                timeout=self.timeout,
                verify=self.verify_tls
            )
            if response.status_code != 200:
                return items
            
            series_list = response.json()
            
            for series in series_list:
                tvdb_id = str(series.get("tvdbId", ""))
                title = series.get("title", "Unknown")
                
                # Get episodes for this series
                eps_response = self.session.get(
                    urljoin(self.base_url, f"/api/v3/episode?seriesId={series['id']}"),
                    timeout=self.timeout,
                    verify=self.verify_tls
                )
                if eps_response.status_code != 200:
                    continue
                
                episodes = eps_response.json()
                for ep in episodes:
                    if ep.get("hasFile") or ep.get("monitored"):
                        items.append(ActiveItem(
                            media_type=MediaType.EPISODE,
                            media_identifier=tvdb_id,
                            title=f"{title} S{ep.get('seasonNumber', 0):02d}E{ep.get('episodeNumber', 0):02d}",
                            season=ep.get("seasonNumber"),
                            episode=ep.get("episodeNumber"),
                            tvdb_id=tvdb_id,
                            source_item_id=str(ep.get("id")),
                            current_state=EventType.AVAILABLE if ep.get("hasFile") else EventType.WANTED,
                            current_service=SourceService.SONARR
                        ))
        except Exception as e:
            logger.error(f"Sonarr discover failed: {e}")
        
        return items
    
    def fetch_events(self, since: Optional[datetime] = None) -> List[RawEvent]:
        """Fetch events from Sonarr history and queue."""
        events = []
        
        # Fetch history (imports, grabs, failures)
        events.extend(self._fetch_history(since))
        
        # Fetch queue (downloading, importing)
        events.extend(self._fetch_queue())
        
        # Fetch wanted/missing
        events.extend(self._fetch_wanted(since))
        
        return events
    
    def _fetch_history(self, since: Optional[datetime] = None) -> List[RawEvent]:
        """Fetch Sonarr history events."""
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
                
                episode = record.get("episode", {})
                series = record.get("series", {})
                
                tvdb_id = str(series.get("tvdbId", ""))
                title = series.get("title", "Unknown")
                season = episode.get("seasonNumber")
                episode_num = episode.get("episodeNumber")
                
                # Build correlation key: tvdb_id + season + episode
                corr_key = f"tvdb:{tvdb_id}"
                if season is not None and episode_num is not None:
                    corr_key += f":S{season:02d}E{episode_num:02d}"
                
                events.append(RawEvent(
                    timestamp=datetime.fromisoformat(record.get("date", "").replace("Z", "+00:00")),
                    source_service=SourceService.SONARR,
                    event_type=mapped_type,
                    media_type=MediaType.EPISODE,
                    media_identifier=tvdb_id,
                    title=f"{title} S{season:02d}E{episode_num:02d}" if season and episode_num else title,
                    season=season,
                    episode=episode_num,
                    tvdb_id=tvdb_id,
                    source_item_id=str(episode.get("id")),
                    source_queue_id=str(record.get("id")),
                    correlation_key=corr_key,
                    source_payload=record,
                    status=EventStatus.COMPLETED if "failed" not in event_type.lower() else EventStatus.FAILED,
                    error_message=record.get("details") if "failed" in event_type.lower() else None
                ))
        except Exception as e:
            logger.error(f"Sonarr history fetch failed: {e}")
        
        return events
    
    def _fetch_queue(self) -> List[RawEvent]:
        """Fetch Sonarr queue (active downloads/imports)."""
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
                episode = record.get("episode", {})
                series = record.get("series", {})
                
                tvdb_id = str(series.get("tvdbId", ""))
                title = series.get("title", "Unknown")
                season = episode.get("seasonNumber")
                episode_num = episode.get("episodeNumber")
                
                status = record.get("status", "").lower()
                mapped_type = self._map_queue_status(status)
                
                progress = record.get("sizeleft", 0)
                size = record.get("size", 1)
                if size > 0:
                    progress_pct = int((1 - progress / size) * 100)
                else:
                    progress_pct = 0
                
                corr_key = f"tvdb:{tvdb_id}"
                if season is not None and episode_num is not None:
                    corr_key += f":S{season:02d}E{episode_num:02d}"
                
                events.append(RawEvent(
                    timestamp=datetime.utcnow(),  # Queue items are current
                    source_service=SourceService.SONARR,
                    event_type=mapped_type,
                    media_type=MediaType.EPISODE,
                    media_identifier=tvdb_id,
                    title=f"{title} S{season:02d}E{episode_num:02d}" if season and episode_num else title,
                    season=season,
                    episode=episode_num,
                    tvdb_id=tvdb_id,
                    source_item_id=str(episode.get("id")),
                    source_queue_id=str(record.get("id")),
                    correlation_key=corr_key,
                    source_payload=record,
                    normalized_metadata={"progress": progress_pct, "status": status},
                    status=EventStatus.IN_PROGRESS
                ))
        except Exception as e:
            logger.error(f"Sonarr queue fetch failed: {e}")
        
        return events
    
    def _fetch_wanted(self, since: Optional[datetime] = None) -> List[RawEvent]:
        """Fetch wanted/missing episodes from Sonarr."""
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
                tvdb_id = str(record.get("series", {}).get("tvdbId", ""))
                title = record.get("series", {}).get("title", "Unknown")
                season = record.get("seasonNumber")
                episode_num = record.get("episodeNumber")
                
                corr_key = f"tvdb:{tvdb_id}"
                if season is not None and episode_num is not None:
                    corr_key += f":S{season:02d}E{episode_num:02d}"
                
                events.append(RawEvent(
                    timestamp=datetime.utcnow(),
                    source_service=SourceService.SONARR,
                    event_type=EventType.WANTED,
                    media_type=MediaType.EPISODE,
                    media_identifier=tvdb_id,
                    title=f"{title} S{season:02d}E{episode_num:02d}" if season and episode_num else title,
                    season=season,
                    episode=episode_num,
                    tvdb_id=tvdb_id,
                    source_item_id=str(record.get("id")),
                    correlation_key=corr_key,
                    source_payload=record,
                    status=EventStatus.PENDING
                ))
        except Exception as e:
            logger.error(f"Sonarr wanted fetch failed: {e}")
        
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
                    episode = record.get("episode", {})
                    series = record.get("series", {})
                    tvdb_id = str(series.get("tvdbId", ""))
                    title = series.get("title", "Unknown")
                    season = episode.get("seasonNumber")
                    episode_num = episode.get("episodeNumber")
                    status = record.get("status", "").lower()
                    
                    progress = record.get("sizeleft", 0)
                    size = record.get("size", 1)
                    progress_pct = int((1 - progress / size) * 100) if size > 0 else 0
                    
                    items.append(ActiveItem(
                        media_type=MediaType.EPISODE,
                        media_identifier=tvdb_id,
                        title=f"{title} S{season:02d}E{episode_num:02d}" if season and episode_num else title,
                        season=season,
                        episode=episode_num,
                        tvdb_id=tvdb_id,
                        source_item_id=str(episode.get("id")),
                        source_queue_id=str(record.get("id")),
                        current_state=self._map_queue_status(status),
                        progress=progress_pct,
                        current_service=SourceService.SONARR
                    ))
        except Exception as e:
            logger.error(f"Sonarr active queue fetch failed: {e}")
        
        return items
    
    def _map_history_event_type(self, event_type: str) -> Optional[EventType]:
        """Map Sonarr history event types to our unified types."""
        mapping = {
            "grabbed": EventType.RELEASE_GRABBED,
            "downloadfailed": EventType.DOWNLOAD_FAILED,
            "downloadimported": EventType.IMPORT_COMPLETED,
            "downloadimportfailed": EventType.IMPORT_FAILED,
            "episodedefileimported": EventType.IMPORT_COMPLETED,
            "episodedefileimportfailed": EventType.IMPORT_FAILED,
            "upgrade": EventType.RELEASE_GRABBED,
        }
        return mapping.get(event_type.lower())
    
    def _map_queue_status(self, status: str) -> EventType:
        """Map Sonarr queue status to our unified types."""
        mapping = {
            "downloading": EventType.DOWNLOAD_PROGRESS,
            "importing": EventType.IMPORT_STARTED,
            "completed": EventType.DOWNLOAD_COMPLETED,
            "failed": EventType.DOWNLOAD_FAILED,
            "delayed": EventType.STUCK,
            "paused": EventType.STUCK,
        }
        return mapping.get(status.lower(), EventType.UNKNOWN)