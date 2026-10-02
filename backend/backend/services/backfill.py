"""Historical backfill service for importing past events."""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from backend.adapters import get_all_adapters
from backend.services.events import EventService
from backend.database.base import get_db
from sqlalchemy.orm import Session

logger = logging.getLogger("arr-control.backfill")


class BackfillStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class BackfillProgress:
    status: BackfillStatus
    days: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    sonarr_processed: int = 0
    sonarr_total: int = 0
    radarr_processed: int = 0
    radarr_total: int = 0
    qbittorrent_processed: int = 0
    qbittorrent_total: int = 0
    prowlarr_processed: int = 0
    prowlarr_total: int = 0
    error_message: Optional[str] = None


class BackfillService:
    """Service for performing historical backfill of events."""

    def __init__(self, db: Session):
        self.db = db
        self.event_service = EventService(db)
        self.progress = BackfillProgress(status=BackfillStatus.IDLE, days=0)
        self._cancelled = False

    def cancel(self):
        """Cancel the current backfill operation."""
        self._cancelled = True

    def run_backfill(self, days: int = 30) -> BackfillProgress:
        """Run historical backfill for the specified number of days."""
        if self.progress.status == BackfillStatus.RUNNING:
            raise RuntimeError("Backfill already in progress")

        self._cancelled = False
        self.progress = BackfillProgress(
            status=BackfillStatus.RUNNING,
            days=days,
            started_at=datetime.utcnow()
        )

        try:
            since = datetime.utcnow() - timedelta(days=days)
            adapters = get_all_adapters()

            for adapter in adapters:
                if self._cancelled:
                    break

                service_name = adapter.service_name.value
                logger.info(f"Starting backfill for {service_name} ({days} days)")

                try:
                    events = adapter.fetch_events(since)
                    self.progress.__dict__[f"{service_name}_total"] = len(events)

                    if events:
                        self.event_service.ingest_events(events)
                        self.progress.__dict__[f"{service_name}_processed"] = len(events)

                    logger.info(f"Backfilled {len(events)} events from {service_name}")
                except Exception as e:
                    logger.error(f"Backfill failed for {service_name}: {e}")
                    # Continue with other adapters

            if self._cancelled:
                self.progress.status = BackfillStatus.FAILED
                self.progress.error_message = "Cancelled by user"
            else:
                self.progress.status = BackfillStatus.COMPLETED
                self.progress.completed_at = datetime.utcnow()

        except Exception as e:
            self.progress.status = BackfillStatus.FAILED
            self.progress.error_message = str(e)
            logger.error(f"Backfill failed: {e}")

        return self.progress

    def get_status(self) -> BackfillProgress:
        """Get current backfill status."""
        return self.progress


_backfill_service: Optional[BackfillService] = None


def get_backfill_service(db: Session) -> BackfillService:
    """Get or create the backfill service."""
    global _backfill_service
    if _backfill_service is None:
        _backfill_service = BackfillService(db)
    return _backfill_service