"""Guardarr adapter for storage admission and security events."""
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

logger = logging.getLogger("arr-control.adapters.guardarr")


class GuardarrAdapter(ServiceAdapter):
    """Guardarr API adapter for storage admission and security events."""

    @property
    def service_name(self) -> SourceService:
        return SourceService.GUARDARR

    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.guardarr_url.rstrip("/") if hasattr(self.settings, 'guardarr_url') else ""
        self.api_key = self.settings.guardarr_api_key if hasattr(self.settings, 'guardarr_api_key') else ""
        self.timeout = self.settings.guardarr_timeout_seconds if hasattr(self.settings, 'guardarr_timeout_seconds') else 10
        self.verify_tls = self.settings.guardarr_verify_tls if hasattr(self.settings, 'guardarr_verify_tls') else True
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({
                "X-Api-Key": self.api_key,
                "Accept": "application/json"
            })

    def health(self) -> ServiceHealth:
        """Check Guardarr connectivity."""
        if not self.base_url or not self.api_key:
            return ServiceHealth(
                service=SourceService.GUARDARR,
                status="down",
                error_message="Guardarr not configured"
            )

        try:
            response = self.session.get(
                urljoin(self.base_url, "/api/health"),
                timeout=self.timeout,
                verify=self.verify_tls
            )
            if response.status_code == 200:
                data = response.json()
                return ServiceHealth(
                    service=SourceService.GUARDARR,
                    status="healthy",
                    version=data.get("version"),
                    details=data
                )
            return ServiceHealth(
                service=SourceService.GUARDARR,
                status="degraded",
                error_message=f"HTTP {response.status_code}"
            )
        except Exception as e:
            logger.error(f"Guardarr health check failed: {e}")
            return ServiceHealth(
                service=SourceService.GUARDARR,
                status="down",
                error_message=str(e)
            )

    def discover(self) -> List[ActiveItem]:
        """Discover active reservations from Guardarr."""
        items = []
        if not self.base_url or not self.api_key:
            return items

        try:
            # Get reservations
            response = self.session.get(
                urljoin(self.base_url, "/api/reservations"),
                timeout=self.timeout,
                verify=self.verify_tls
            )
            if response.status_code != 200:
                return items

            reservations = response.json()
            for reservation in reservations:
                items.append(self._reservation_to_item(reservation))
        except Exception as e:
            logger.error(f"Guardarr discover failed: {e}")

        return items

    def fetch_events(self, since: Optional[datetime] = None) -> List[RawEvent]:
        """Fetch events from Guardarr based on reservations and reconcile operations."""
        events = []
        if not self.base_url or not self.api_key:
            return events

        try:
            # Fetch reservations (which act as events)
            params = {}
            if since:
                params["since"] = since.isoformat() + "Z"

            response = self.session.get(
                urljoin(self.base_url, "/api/reservations"),
                params=params,
                timeout=self.timeout,
                verify=self.verify_tls
            )
            if response.status_code == 200:
                reservations = response.json()
                for reservation in reservations:
                    event = self._reservation_to_event(reservation)
                    if event:
                        events.append(event)

            # Fetch reconcile status
            reconcile_resp = self.session.get(
                urljoin(self.base_url, "/api/qbittorrent/unreserved"),
                timeout=self.timeout,
                verify=self.verify_tls
            )
            if reconcile_resp.status_code == 200:
                reconcile_data = reconcile_resp.json()
                for torrent in reconcile_data.get("unreserved_torrents", []):
                    event = self._unreserved_torrent_to_event(torrent)
                    if event:
                        events.append(event)

        except Exception as e:
            logger.error(f"Guardarr events fetch failed: {e}")

        return events

    def fetch_active_items(self) -> List[ActiveItem]:
        """Fetch currently active reservations."""
        return self.discover()

    def _reservation_to_item(self, reservation: Dict[str, Any]) -> ActiveItem:
        """Convert a reservation to an ActiveItem."""
        return ActiveItem(
            media_type=MediaType.MOVIE,
            media_identifier=reservation.get("content_id", ""),
            title=reservation.get("arr_item_id", "Unknown"),
            source_item_id=reservation.get("reservation_id", ""),
            source_download_id=reservation.get("torrent_metadata_hash", ""),
            current_state=EventType.UNKNOWN,
            current_service=SourceService.GUARDARR,
        )

    def _reservation_to_event(self, reservation: Dict[str, Any]) -> Optional[RawEvent]:
        """Convert a reservation to a RawEvent."""
        try:
            state = reservation.get("state", "").lower()

            # Map Guardarr reservation state to our event types
            event_type_map = {
                "pending": EventType.STORAGE_ESTIMATE,
                "admitted": EventType.STORAGE_ADMIT,
                "released": EventType.STORAGE_RELEASE,
                "reconciled": EventType.STORAGE_RECONCILE,
                "imported": EventType.IMPORT_COMPLETED,
                "failed": EventType.SECURITY_BLOCKED,
            }

            event_type = event_type_map.get(state, EventType.UNKNOWN)

            # Parse timestamp
            timestamp_str = reservation.get("updated_at") or reservation.get("created_at", "")
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except:
                timestamp = datetime.utcnow()

            # Determine correlation key
            content_id = reservation.get("content_id", "")
            torrent_hash = reservation.get("torrent_metadata_hash", "")
            arr_item_id = reservation.get("arr_item_id", "")

            if content_id:
                correlation_key = f"guardarr:{content_id}"
            elif torrent_hash:
                correlation_key = f"hash:{torrent_hash}"
            elif arr_item_id:
                correlation_key = f"arr:{arr_item_id}"
            else:
                correlation_key = f"guardarr:{reservation.get('reservation_id', 'unknown')}"

            # Determine media type from arr_item_id or content_id
            media_type = MediaType.MOVIE  # default

            return RawEvent(
                timestamp=timestamp,
                source_service=SourceService.GUARDARR,
                event_type=event_type,
                media_type=media_type,
                media_identifier=content_id or arr_item_id or torrent_hash or "unknown",
                title=reservation.get("arr_item_id", reservation.get("content_id", "Unknown")),
                source_download_id=torrent_hash,
                source_item_id=reservation.get("reservation_id", ""),
                correlation_key=correlation_key,
                source_payload=reservation,
                normalized_metadata={
                    "guardarr_event_type": state,
                    "reservation_id": reservation.get("reservation_id"),
                    "content_id": content_id,
                    "arr_item_id": arr_item_id,
                    "torrent_metadata_hash": torrent_hash,
                    "associated_path": reservation.get("associated_path"),
                    "target_device": reservation.get("target_device"),
                    "max_bytes": reservation.get("max_bytes"),
                    "expected_bytes": reservation.get("expected_bytes"),
                    "observed_materialized_bytes": reservation.get("observed_materialized_bytes"),
                    "remaining_unfulfilled_bytes": reservation.get("remaining_unfulfilled_bytes"),
                    "import_mode": reservation.get("import_mode"),
                    "priority": reservation.get("priority"),
                    "owner": reservation.get("owner"),
                    "torrent_tag": reservation.get("torrent_tag"),
                    "idempotency_key": reservation.get("idempotency_key"),
                },
                status=EventStatus.COMPLETED
            )
        except Exception as e:
            logger.error(f"Failed to convert reservation to event: {e}")
            return None

    def _unreserved_torrent_to_event(self, torrent: Dict[str, Any]) -> Optional[RawEvent]:
        """Convert an unreserved torrent to a RawEvent."""
        try:
            torrent_hash = torrent.get("hash", "")
            torrent_name = torrent.get("name", "Unknown")

            # Parse timestamp from reconcile operation
            timestamp = datetime.utcnow()

            return RawEvent(
                timestamp=timestamp,
                source_service=SourceService.GUARDARR,
                event_type=EventType.TORRENT_UNRESERVED,
                media_type=MediaType.MOVIE,
                media_identifier=torrent_hash,
                title=torrent_name,
                source_download_id=torrent_hash,
                correlation_key=f"hash:{torrent_hash}",
                source_payload=torrent,
                normalized_metadata={
                    "guardarr_event_type": "torrent_unreserved",
                    "torrent_hash": torrent_hash,
                    "torrent_name": torrent_name,
                    "torrent_size": torrent.get("size"),
                    "torrent_progress": torrent.get("progress"),
                    "torrent_state": torrent.get("state"),
                    "torrent_tags": torrent.get("tags"),
                    "save_path": torrent.get("save_path"),
                },
                status=EventStatus.COMPLETED
            )
        except Exception as e:
            logger.error(f"Failed to convert unreserved torrent to event: {e}")
            return None


def get_guardarr_adapter() -> GuardarrAdapter:
    """Get or create the Guardarr adapter singleton."""
    return GuardarrAdapter()