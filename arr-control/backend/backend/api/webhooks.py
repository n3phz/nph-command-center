"""Webhook endpoints for Sonarr/Radarr real-time events."""
import logging
import hmac
import hashlib
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, Header, Depends
from pydantic import BaseModel

from backend.adapters.base import SourceService, EventType, MediaType
from backend.correlation.engine import get_correlation_engine
from backend.services.events import EventService
from backend.database.base import get_db
from sqlalchemy.orm import Session

logger = logging.getLogger("arr-control.api.webhooks")

router = APIRouter(prefix="/api/webhook", tags=["webhooks"])


class WebhookPayload(BaseModel):
    """Base webhook payload."""
    eventType: str
    instanceName: Optional[str] = None


def verify_sonarr_signature(payload: bytes, signature: str, api_key: str) -> bool:
    """Verify Sonarr webhook signature."""
    if not signature:
        return False
    expected = hmac.new(
        api_key.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def verify_radarr_signature(payload: bytes, signature: str, api_key: str) -> bool:
    """Verify Radarr webhook signature."""
    if not signature:
        return False
    expected = hmac.new(
        api_key.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


async def process_webhook(
    request: Request,
    source_service: SourceService,
    db: Session,
    x_signature: Optional[str] = Header(None)
):
    """Process a webhook from Sonarr or Radarr."""
    payload = await request.body()
    
    # Parse JSON
    try:
        import json
        data = json.loads(payload)
    except Exception as e:
        logger.error(f"Invalid JSON in webhook: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    event_type_str = data.get("eventType", "").lower()
    
    # Map webhook event types to our EventType
    event_type_map = {
        "grab": EventType.RELEASE_GRABBED,
        "download": EventType.DOWNLOAD_STARTED,
        "import": EventType.IMPORT_STARTED,
        "rename": EventType.UNKNOWN,
        "applicationupdate": EventType.APPLICATION_UPDATE,
        "healthissue": EventType.HEALTH_ISSUE,
        "healthrestored": EventType.HEALTH_RESTORED,
        "test": EventType.WEBHOOK_TEST,
    }
    
    event_type = event_type_map.get(event_type_str, EventType.UNKNOWN)
    
    # Extract common fields
    movie_id = data.get("movie", {}).get("id") or data.get("movieId")
    series_id = data.get("series", {}).get("id") or data.get("seriesId")
    episode_id = data.get("episode", {}).get("id") or data.get("episodeId")
    season_number = data.get("episode", {}).get("seasonNumber") or data.get("seasonNumber")
    episode_number = data.get("episode", {}).get("episodeNumber") or data.get("episodeNumber")
    download_id = data.get("downloadId") or data.get("release", {}).get("downloadId")
    release_title = data.get("release", {}).get("title") or data.get("releaseTitle", "")
    
    # Determine media type and identifiers
    if series_id:
        media_type = MediaType.EPISODE
        media_identifier = str(series_id)
        tvdb_id = str(series_id) if series_id else None
    elif movie_id:
        media_type = MediaType.MOVIE
        media_identifier = str(movie_id)
        tmdb_id = str(movie_id) if movie_id else None
    else:
        media_type = MediaType.MOVIE
        media_identifier = download_id or "unknown"
    
    # Build correlation key
    if movie_id:
        correlation_key = f"media:{movie_id}"
    elif series_id:
        correlation_key = f"media:{series_id}:S{season_number:02d}E{episode_number:02d}" if season_number and episode_number else f"media:{series_id}"
    elif download_id:
        correlation_key = f"hash:{download_id}"
    else:
        correlation_key = f"webhook:{source_service.value}:{release_title}"
    
    # Source service determines which *Arr
    if source_service == SourceService.SONARR:
        arr_service = SourceService.SONARR
    else:
        arr_service = SourceService.RADARR
    
    # Create event
    from backend.adapters.base import RawEvent, EventStatus
    from datetime import datetime
    
    event = RawEvent(
        timestamp=datetime.utcnow(),
        source_service=arr_service,
        event_type=event_type,
        media_type=media_type,
        media_identifier=media_identifier,
        title=release_title,
        season=season_number,
        episode=episode_number,
        tvdb_id=tvdb_id,
        tmdb_id=tmdb_id,
        source_download_id=download_id,
        source_item_id=str(movie_id or series_id or ""),
        correlation_key=correlation_key,
        source_payload=data,
        normalized_metadata={
            "ingestion": "webhook",
            "webhook_event_type": event_type_str,
            "release_title": release_title,
        },
        status=EventStatus.COMPLETED
    )
    
    # Ingest event
    event_service = EventService(db)
    event_service.ingest_event(event)
    
    return {"status": "ok", "event_type": event_type.value, "correlation_key": correlation_key}


@router.post("/sonarr")
async def sonarr_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_signature: Optional[str] = Header(None, alias="X-Signature")
):
    """Sonarr webhook endpoint."""
    from backend.core.config import get_settings
    settings = get_settings()
    
    # Verify signature if configured
    payload = await request.body()
    if settings.sonarr_api_key and not verify_sonarr_signature(payload, x_signature or "", settings.sonarr_api_key):
        logger.warning("Invalid Sonarr webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    return await process_webhook(request, SourceService.SONARR, db, x_signature)


@router.post("/radarr")
async def radarr_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_signature: Optional[str] = Header(None, alias="X-Signature")
):
    """Radarr webhook endpoint."""
    from backend.core.config import get_settings
    settings = get_settings()
    
    # Verify signature if configured
    payload = await request.body()
    if settings.radarr_api_key and not verify_radarr_signature(payload, x_signature or "", settings.radarr_api_key):
        logger.warning("Invalid Radarr webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    return await process_webhook(request, SourceService.RADARR, db, x_signature)


@router.post("/prowlarr")
async def prowlarr_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """Prowlarr webhook endpoint (if supported in future)."""
    # Prowlarr webhook structure may differ
    return await process_webhook(request, SourceService.PROWLARR, db)