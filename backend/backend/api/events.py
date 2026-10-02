"""Events API endpoints."""
import logging
import asyncio
import json
from typing import List, Optional, Dict, Any, AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.database.base import get_db
from backend.services.events import EventService
from backend.adapters.base import SourceService, EventType

logger = logging.getLogger("arr-control.api.events")

router = APIRouter(prefix="/api/events", tags=["events"])


# SSE Event Types for live updates
class SSEEventType(str):
    ITEM_UPDATE = "item_update"
    ITEM_CREATED = "item_created"
    ITEM_STATE_CHANGE = "item_state_change"
    PROGRESS_UPDATE = "progress_update"
    DOWNLOAD_STARTED = "download_started"
    DOWNLOAD_PROGRESS = "download_progress"
    DOWNLOAD_COMPLETED = "download_completed"
    DOWNLOAD_FAILED = "download_failed"
    IMPORT_STARTED = "import_started"
    IMPORT_COMPLETED = "import_completed"
    IMPORT_FAILED = "import_failed"
    SERVICE_STATUS_CHANGE = "service_status_change"
    ALERT_CREATED = "alert_created"
    ALERT_ACKNOWLEDGED = "alert_acknowledged"
    ALERT_RESOLVED = "alert_resolved"
    HEARTBEAT = "heartbeat"


@dataclass
class SSEEvent:
    """Server-Sent Event structure."""
    event: str
    data: Dict[str, Any]
    id: Optional[str] = None
    retry: Optional[int] = None

    def to_sse(self) -> str:
        lines = []
        if self.id:
            lines.append(f"id: {self.id}")
        if self.retry:
            lines.append(f"retry: {self.retry}")
        lines.append(f"event: {self.event}")
        lines.append(f"data: {json.dumps(self.data)}")
        return "\n".join(lines) + "\n\n"


# Global SSE broadcaster
class SSEBroadcaster:
    """Manages SSE connections and broadcasts events."""
    
    def __init__(self):
        self._connections: Dict[str, asyncio.Queue] = {}
        self._lock = asyncio.Lock()
    
    async def register(self, client_id: str) -> asyncio.Queue:
        """Register a new SSE connection."""
        queue = asyncio.Queue()
        async with self._lock:
            self._connections[client_id] = queue
        logger.debug(f"SSE client connected: {client_id} (total: {len(self._connections)})")
        return queue
    
    async def unregister(self, client_id: str):
        """Unregister an SSE connection."""
        async with self._lock:
            self._connections.pop(client_id, None)
        logger.debug(f"SSE client disconnected: {client_id} (total: {len(self._connections)})")
    
    async def broadcast(self, event: SSEEvent):
        """Broadcast event to all connected clients."""
        async with self._lock:
            if not self._connections:
                return
            for client_id, queue in self._connections.items():
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning(f"SSE queue full for client {client_id}, dropping event")
    
    async def send_to_client(self, client_id: str, event: SSEEvent):
        """Send event to specific client."""
        async with self._lock:
            queue = self._connections.get(client_id)
            if queue:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning(f"SSE queue full for client {client_id}, dropping event")


# Global broadcaster instance
_broadcaster: Optional[SSEBroadcaster] = None


def get_broadcaster() -> SSEBroadcaster:
    """Get or create the SSE broadcaster."""
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = SSEBroadcaster()
    return _broadcaster


def create_item_update_event(item_id: str, event_type: str, data: Dict[str, Any]) -> SSEEvent:
    """Create a standardized item update event."""
    return SSEEvent(
        event=event_type,
        data={
            "item_id": item_id,
            "timestamp": datetime.utcnow().isoformat(),
            **data
        },
        id=f"{item_id}-{event_type}-{datetime.utcnow().timestamp()}"
    )


async def stream_events(request: Request, db: Session = Depends(get_db)):
    """SSE endpoint for live event streaming."""
    client_id = f"{request.client.host}:{request.client.port}" if request.client else "unknown"
    broadcaster = get_broadcaster()
    queue = await broadcaster.register(client_id)
    
    # Send initial connection event
    await queue.put(SSEEvent(
        event=SSEEventType.HEARTBEAT,
        data={"status": "connected", "client_id": client_id},
        retry=30000
    ))
    
    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # Send initial heartbeat
            yield SSEEvent(
                event=SSEEventType.HEARTBEAT,
                data={"status": "connected", "client_id": client_id},
                retry=30000
            ).to_sse()
            
            # Send current items snapshot
            event_service = EventService(db)
            items = event_service.get_items()
            for item in items:
                yield create_item_update_event(
                    item.correlation_key,
                    SSEEventType.ITEM_CREATED,
                    {
                        "title": item.title,
                        "media_type": item.media_type.value,
                        "current_state": item.current_state.value,
                        "progress": item.progress,
                        "current_service": item.current_service.value if item.current_service else None,
                        "season": item.season,
                        "episode": item.episode,
                    }
                ).to_sse()
            
            # Stream live events
            while True:
                if await request.is_disconnected():
                    break
                
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield event.to_sse()
                except asyncio.TimeoutError:
                    # Send heartbeat
                    yield SSEEvent(
                        event=SSEEventType.HEARTBEAT,
                        data={"timestamp": datetime.utcnow().isoformat()},
                        retry=30000
                    ).to_sse()
        except Exception as e:
            logger.error(f"SSE stream error for {client_id}: {e}")
        finally:
            await broadcaster.unregister(client_id)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/stream")
async def events_stream(request: Request, db: Session = Depends(get_db)):
    """SSE endpoint for live event streaming."""
    return await stream_events(request, db)


@router.get("", response_model=List[dict], summary="List events")
def list_events(
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    source_service: Optional[str] = Query(None, description="Filter by source service"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    media_type: Optional[str] = Query(None, description="Filter by media type"),
):
    """List events with filtering and pagination."""
    event_service = EventService(db)
    
    source = SourceService(source_service) if source_service else None
    etype = EventType(event_type) if event_type else None
    
    return event_service.get_events(
        limit=limit,
        offset=offset,
        source_service=source,
        event_type=etype
    )


# Helper functions for broadcasting from services
async def broadcast_item_update(item_id: str, event_type: str, data: Dict[str, Any]):
    """Broadcast an item update to all SSE clients."""
    broadcaster = get_broadcaster()
    event = create_item_update_event(item_id, event_type, data)
    await broadcaster.broadcast(event)


async def broadcast_progress_update(item_id: str, progress: int, state: str, current_service: Optional[str] = None, detail: Optional[str] = None):
    """Broadcast a progress update for a download/import."""
    await broadcast_item_update(item_id, SSEEventType.PROGRESS_UPDATE, {
        "progress": progress,
        "state": state,
        "current_service": current_service,
        "detail": detail,
    })


async def broadcast_state_change(item_id: str, new_state: str, old_state: Optional[str] = None, metadata: Optional[Dict] = None):
    """Broadcast a state change for an item."""
    await broadcast_item_update(item_id, SSEEventType.ITEM_STATE_CHANGE, {
        "new_state": new_state,
        "old_state": old_state,
        "metadata": metadata,
    })


async def broadcast_service_status_change(service: str, status: str, details: Optional[Dict] = None):
    """Broadcast a service status change."""
    broadcaster = get_broadcaster()
    event = SSEEvent(
        event=SSEEventType.SERVICE_STATUS_CHANGE,
        data={
            "service": service,
            "status": status,
            "details": details,
            "timestamp": datetime.utcnow().isoformat(),
        }
    )
    await broadcaster.broadcast(event)