"""qBittorrent adapter for fetching events and active items."""
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

logger = logging.getLogger("arr-control.adapters.qbittorrent")


class QBittorrentAdapter(ServiceAdapter):
    """qBittorrent API adapter."""
    
    @property
    def service_name(self) -> SourceService:
        return SourceService.QBITTORRENT
    
    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.qbittorrent_url.rstrip("/")
        self.username = self.settings.qbittorrent_username
        self._raw_password = self.settings.qbittorrent_password
        self.timeout = self.settings.qbittorrent_timeout_seconds
        self.verify_tls = self.settings.qbittorrent_verify_tls
        self.session = requests.Session()
        self._session_hash: Optional[str] = None
    
    def _login(self) -> bool:
        """Login to qBittorrent and get session cookie."""
        if not self._session_hash:
            response = self.session.post(
                urljoin(self.base_url, "/api/v2/auth/login"),
                data={"username": self.username, "password": self._raw_password},
                timeout=self.timeout,
                verify=self.verify_tls
            )
            if response.status_code == 200 and response.text.strip() == "Ok.":
                self._session_hash = self.session.cookies.get("SID")
                return True
            logger.warning(f"qBittorrent login failed: HTTP {response.status_code}")
            self._session_hash = None
            return False
        return True
    
    def _request(self, method: str, endpoint: str, **kwargs) -> Optional[requests.Response]:
        """Make authenticated request to qBittorrent API."""
        if not self._login():
            return None
        
        url = urljoin(self.base_url, f"/api/v2/{endpoint.lstrip('/')}")
        try:
            response = self.session.request(method, url, timeout=self.timeout, verify=self.verify_tls, **kwargs)
            if response.status_code == 403:
                self._login()  # Re-login on 403
                response = self.session.request(method, url, timeout=self.timeout, verify=self.verify_tls, **kwargs)
            return response
        except Exception as e:
            logger.error(f"qBittorrent request error ({method} {endpoint}): {e}")
            return None
    
    def health(self) -> ServiceHealth:
        """Check qBittorrent connectivity."""
        try:
            response = self._request("GET", "app/version/api")
            if response and response.status_code == 200:
                api_version = response.text.strip()
                version_response = self._request("GET", "app/version")
                version = version_response.text.strip() if version_response else "unknown"
                return ServiceHealth(
                    service=SourceService.QBITTORRENT,
                    status="healthy",
                    version=f"API v{api_version}"
                )
            return ServiceHealth(
                service=SourceService.QBITTORRENT,
                status="degraded",
                error_message="Failed to connect or authenticate"
            )
        except Exception as e:
            logger.error(f"qBittorrent health check failed: {e}")
            return ServiceHealth(
                service=SourceService.QBITTORRENT,
                status="down",
                error_message=str(e)
            )
    
    def discover(self) -> List[ActiveItem]:
        """Discover all torrents from qBittorrent."""
        items = []
        try:
            response = self._request("GET", "torrents/info")
            if not response or response.status_code != 200:
                return items
            
            torrents = response.json()
            
            for torrent in torrents:
                if not self._is_media_torrent(torrent):
                    continue
                
                items.append(self._torrent_to_item(torrent))
        except Exception as e:
            logger.error(f"qBittorrent discover failed: {e}")
        
        return items
    
    def fetch_events(self, since: Optional[datetime] = None) -> List[RawEvent]:
        """Fetch events from qBittorrent based on torrent state changes."""
        events = []
        try:
            response = self._request("GET", "torrents/info")
            if not response or response.status_code != 200:
                return events
            
            torrents = response.json()
            
            for torrent in torrents:
                if not self._is_media_torrent(torrent):
                    continue
                
                event = self._torrent_to_event(torrent, since)
                if event:
                    events.append(event)
        except Exception as e:
            logger.error(f"qBittorrent events fetch failed: {e}")
        
        return events
    
    def _is_media_torrent(self, torrent: Dict[str, Any]) -> bool:
        """Check if a torrent looks like a media download."""
        tags = torrent.get("tags", "")
        size = torrent.get("size", 0)
        
        # Skip very small torrents (trackers, etc.)
        if size < 10_000_000:  # 10MB
            return False
        
        # Check for media-related tags
        media_tags = ["sonarr", "radarr", "arr", "media", "tv", "movie"]
        if any(tag in tags.lower() for tag in media_tags):
            return True
        
        # Check for common media extensions in name
        name = torrent.get("name", "").lower()
        media_extensions = [".mkv", ".mp4", ".avi", ".m4v", ".flv", ".wmv", ".ts", ".iso"]
        if any(ext in name for ext in media_extensions):
            return True
        
        # Heuristic: large size with typical media naming patterns
        if size > 500_000_000:  # 500MB
            return True
        
        return False
    
    def _torrent_to_item(self, torrent: Dict[str, Any]) -> ActiveItem:
        """Convert a torrent to an ActiveItem."""
        name = torrent.get("name", "Unknown")
        size = torrent.get("size", 0)
        
        # Extract hash for identification
        torrent_hash = torrent.get("hash", "")
        
        # Determine media type
        media_type = MediaType.MOVIE
        if any(s in name.lower() for s in ["s0", "e0", "episode", "s0", "season"]):
            media_type = MediaType.EPISODE
        
        # Parse state
        state = torrent.get("state", "unknown")
        progress = int(torrent.get("progress", 0) * 100)
        
        current_state = self._map_state(state)
        status = EventStatus.IN_PROGRESS if state in ["downloading", "uploading", "queued", "checking"] else EventStatus.COMPLETED
        
        return ActiveItem(
            media_type=media_type,
            media_identifier=torrent_hash,
            title=name,
            source_download_id=torrent_hash,
            current_state=current_state,
            progress=progress,
            current_service=SourceService.QBITTORRENT,
            source_payload=torrent
        )
    
    def _torrent_to_event(self, torrent: Dict[str, Any], since: Optional[datetime] = None) -> Optional[RawEvent]:
        """Convert a torrent to a RawEvent with full normalization."""
        name = torrent.get("name", "Unknown")
        size = torrent.get("size", 0)
        progress = torrent.get("progress", 0)
        
        # Extract hash for identification
        torrent_hash = torrent.get("hash", "").upper()
        if not torrent_hash:
            return None
        
        # Determine media type from category/tags
        category = torrent.get("category", "").lower()
        tags = torrent.get("tags", "").lower()
        
        is_tv = any(x in category for x in ["tv", "sonarr"]) or "sonarr" in tags
        is_movie = any(x in category for x in ["radarr", "movie"]) or "radarr" in tags
        
        # Fallback to name heuristic
        media_type = MediaType.EPISODE if is_tv or (not is_movie and any(s in name.lower() for s in ["s0", "e0", "episode", "season"])) else MediaType.MOVIE
        
        state = torrent.get("state", "unknown")
        event_type = self._map_state(state)
        status = EventStatus.IN_PROGRESS if state in ["downloading", "uploading", "queued", "checking"] else EventStatus.COMPLETED
        
        # Track downloaded amount for progress
        downloaded = torrent.get("downloaded", 0)
        added_on = torrent.get("added_on", 0)
        completion_on = torrent.get("completion_on", 0)
        
        # Use added_on as timestamp if available, else now
        timestamp = datetime.utcfromtimestamp(added_on) if added_on else datetime.utcnow()
        
        return RawEvent(
            timestamp=timestamp,
            source_service=SourceService.QBITTORRENT,
            event_type=event_type,
            media_type=media_type,
            media_identifier=torrent_hash,
            title=name,
            source_download_id=torrent_hash,
            correlation_key=f"hash:{torrent_hash}",
            source_payload=torrent,
            normalized_metadata={
                "progress": int(progress * 100),
                "state": state,
                "downloaded": downloaded,
                "size": size,
                "dl_speed": torrent.get("dlspeed", 0),
                "ul_speed": torrent.get("upspeed", 0),
                "peers": torrent.get("num_peers", 0),
                "seeds": torrent.get("num_seeds", 0),
                "category": category,
                "tags": tags,
                "save_path": torrent.get("save_path", ""),
                "content_path": torrent.get("content_path", ""),
                "ratio": torrent.get("ratio", 0),
                "added_on": added_on,
                "completion_on": completion_on,
            },
            status=status
        )
    
    def _map_state(self, state: str) -> EventType:
        """Map qBittorrent state to our unified types."""
        mapping = {
            "downloading": EventType.DOWNLOAD_PROGRESS,
            "uploading": EventType.DOWNLOAD_COMPLETED,
            "queued": EventType.DOWNLOAD_STARTED,
            "checking": EventType.DOWNLOAD_STARTED,
            "paused_dl": EventType.STUCK,
            "paused_up": EventType.STUCK,
            "completed": EventType.DOWNLOAD_COMPLETED,
            "moving": EventType.DOWNLOAD_STARTED,
            "error": EventType.DOWNLOAD_FAILED,
        }
        return mapping.get(state, EventType.UNKNOWN)
    
    def fetch_active_items(self) -> List[ActiveItem]:
        """Fetch currently active torrents."""
        items = []
        try:
            response = self._request("GET", "torrents/info")
            if not response or response.status_code != 200:
                return items
            
            torrents = response.json()
            
            for torrent in torrents:
                if not self._is_media_torrent(torrent):
                    continue
                
                state = torrent.get("state", "")
                if state in ["downloading", "uploading", "queued", "checking"]:
                    items.append(self._torrent_to_item(torrent))
        except Exception as e:
            logger.error(f"qBittorrent active items fetch failed: {e}")
        
        return items