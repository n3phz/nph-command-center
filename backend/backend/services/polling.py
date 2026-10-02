"""Polling service for fetching events from ARR services."""
import logging
import time
import asyncio
from typing import List, Dict, Any
from datetime import datetime, timedelta
from queue import Queue
from threading import Thread, Lock

from backend.adapters.base import ServiceAdapter, SourceService, RawEvent
from backend.adapters import get_all_adapters
from backend.services.events import EventService
from backend.database.base import SessionLocal
from backend.api.events import broadcast_item_update, broadcast_progress_update, broadcast_state_change

logger = logging.getLogger("arr-control.services.polling")


class PollingService:
    """Service for polling ARR services and ingesting events."""
    
    def __init__(self, poll_interval: int = 30):
        self.poll_interval = poll_interval
        self.adapters = get_all_adapters()
        self.running = False
        self.poll_thread: Optional[Thread] = None
        self.last_poll_times: Dict[SourceService, datetime] = {}
        self._lock = Lock()
    
    def start(self) -> None:
        """Start the polling loop."""
        if self.running:
            return
        
        self.running = True
        self.poll_thread = Thread(target=self._poll_loop, daemon=True)
        self.poll_thread.start()
        logger.info(f"Polling service started with interval {self.poll_interval}s")
    
    def stop(self) -> None:
        """Stop the polling loop."""
        self.running = False
        if self.poll_thread:
            self.poll_thread.join(timeout=10)
        logger.info("Polling service stopped")
    
    def _poll_loop(self) -> None:
        """Main polling loop."""
        while self.running:
            try:
                for adapter in self.adapters:
                    try:
                        self._poll_adapter(adapter)
                    except Exception as e:
                        logger.error(f"Error polling {adapter.service_name}: {e}")
                
                time.sleep(self.poll_interval)
            except Exception as e:
                logger.error(f"Poll loop error: {e}")
                time.sleep(self.poll_interval)
    
    def _poll_adapter(self, adapter: ServiceAdapter) -> None:
        """Poll a single adapter for new events."""
        with self._lock:
            last_poll = self.last_poll_times.get(adapter.service_name)
        
        # Only fetch events since last poll
        events = adapter.fetch_events(since=last_poll)
        
        if events:
            # Store events in database
            db = SessionLocal()
            try:
                event_service = EventService(db)
                event_service.ingest_events(events)
                logger.debug(f"Processed {len(events)} events from {adapter.service_name.value}")
                
                # Broadcast events via SSE
                self._broadcast_events(events)
            finally:
                db.close()
            
            # Update last poll time
            with self._lock:
                self.last_poll_times[adapter.service_name] = datetime.utcnow()
    
    def _broadcast_events(self, events: List[RawEvent]) -> None:
        """Broadcast events via SSE for live updates."""
        try:
            # Group events by correlation key for efficient broadcasting
            for event in events:
                item_id = event.correlation_key or f"{event.source_service.value}:{event.source_download_id or event.source_item_id}"
                
                # Broadcast item creation/update
                asyncio.run(broadcast_item_update(
                    item_id,
                    "item_update",
                    {
                        "title": event.title,
                        "media_type": event.media_type.value,
                        "event_type": event.event_type.value,
                        "source_service": event.source_service.value,
                        "progress": event.normalized_metadata.get("progress") if event.normalized_metadata else None,
                        "season": event.season,
                        "episode": event.episode,
                    }
                ))
                
                # Broadcast progress updates for downloads
                if event.event_type.value in ["download_progress", "download_started"]:
                    asyncio.run(broadcast_progress_update(
                        item_id,
                        event.normalized_metadata.get("progress", 0) if event.normalized_metadata else 0,
                        event.event_type.value,
                        event.source_service.value,
                        event.normalized_metadata.get("detail") if event.normalized_metadata else None
                    ))
                
                # Broadcast state changes
                if event.event_type.value in ["download_completed", "download_failed", "import_completed", "import_failed", "available", "stuck"]:
                    asyncio.run(broadcast_state_change(
                        item_id,
                        event.event_type.value,
                        None,
                        event.normalized_metadata
                    ))
        except Exception as e:
            logger.warning(f"Failed to broadcast events via SSE: {e}")
    
    def force_poll(self) -> Dict[str, int]:
        """Force immediate polling of all services.
        
        Returns dict of service_name -> events_processed
        """
        results = {}
        
        for adapter in self.adapters:
            try:
                events = adapter.fetch_events()
                
                if events:
                    db = SessionLocal()
                    try:
                        event_service = EventService(db)
                        event_service.ingest_events(events)
                        results[adapter.service_name.value] = len(events)
                        logger.debug(f"Forced poll: {len(events)} events from {adapter.service_name.value}")
                        
                        # Broadcast events via SSE
                        self._broadcast_events(events)
                    finally:
                        db.close()
                
                # Update last poll time
                with self._lock:
                    self.last_poll_times[adapter.service_name] = datetime.utcnow()
            except Exception as e:
                logger.error(f"Error forcing poll for {adapter.service_name}: {e}")
                results[adapter.service_name.value] = 0
        
        return results
    
    def get_status(self) -> Dict[str, Any]:
        """Get polling service status."""
        return {
            "running": self.running,
            "poll_interval_seconds": self.poll_interval,
            "adapters_count": len(self.adapters),
            "last_poll_times": {
                service.value: time.isoformat() if isinstance(time := ts, datetime) else str(ts)
                for service, ts in self.last_poll_times.items()
            }
        }