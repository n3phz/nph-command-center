"""Backfill API endpoints."""
import logging
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from backend.database.base import get_db
from backend.services.backfill import get_backfill_service, BackfillProgress, BackfillStatus

logger = logging.getLogger("arr-control.api.backfill")

router = APIRouter(prefix="/api/backfill", tags=["backfill"])


class BackfillRequest(BaseModel):
    days: int = Field(default=30, ge=1, le=365, description="Number of days of history to backfill")


class BackfillResponse(BaseModel):
    status: str
    days: int
    started_at: str | None = None
    completed_at: str | None = None
    sonarr_processed: int = 0
    sonarr_total: int = 0
    radarr_processed: int = 0
    radarr_total: int = 0
    qbittorrent_processed: int = 0
    qbittorrent_total: int = 0
    prowlarr_processed: int = 0
    prowlarr_total: int = 0
    error_message: str | None = None


@router.post("", response_model=BackfillResponse, summary="Start historical backfill")
def start_backfill(
    request: BackfillRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Start a historical backfill operation."""
    backfill_service = get_backfill_service(db)

    if backfill_service.progress.status == BackfillStatus.RUNNING:
        raise HTTPException(status_code=409, detail="Backfill already in progress")

    def run_backfill():
        backfill_service.run_backfill(request.days)

    background_tasks.add_task(run_backfill)

    return BackfillResponse(
        status=backfill_service.progress.status.value,
        days=backfill_service.progress.days,
        started_at=backfill_service.progress.started_at.isoformat() if backfill_service.progress.started_at else None,
        completed_at=backfill_service.progress.completed_at.isoformat() if backfill_service.progress.completed_at else None,
        sonarr_processed=backfill_service.progress.sonarr_processed,
        sonarr_total=backfill_service.progress.sonarr_total,
        radarr_processed=backfill_service.progress.radarr_processed,
        radarr_total=backfill_service.progress.radarr_total,
        qbittorrent_processed=backfill_service.progress.qbittorrent_processed,
        qbittorrent_total=backfill_service.progress.qbittorrent_total,
        prowlarr_processed=backfill_service.progress.prowlarr_processed,
        prowlarr_total=backfill_service.progress.prowlarr_total,
        error_message=backfill_service.progress.error_message,
    )


@router.get("/status", response_model=BackfillResponse, summary="Get backfill status")
def get_backfill_status(db: Session = Depends(get_db)):
    """Get the current backfill status."""
    backfill_service = get_backfill_service(db)
    progress = backfill_service.get_status()

    return BackfillResponse(
        status=progress.status.value,
        days=progress.days,
        started_at=progress.started_at.isoformat() if progress.started_at else None,
        completed_at=progress.completed_at.isoformat() if progress.completed_at else None,
        sonarr_processed=progress.sonarr_processed,
        sonarr_total=progress.sonarr_total,
        radarr_processed=progress.radarr_processed,
        radarr_total=progress.radarr_total,
        qbittorrent_processed=progress.qbittorrent_processed,
        qbittorrent_total=progress.qbittorrent_total,
        prowlarr_processed=progress.prowlarr_processed,
        prowlarr_total=progress.prowlarr_total,
        error_message=progress.error_message,
    )


@router.post("/cancel", summary="Cancel running backfill")
def cancel_backfill(db: Session = Depends(get_db)):
    """Cancel a running backfill operation."""
    backfill_service = get_backfill_service(db)

    if backfill_service.progress.status != BackfillStatus.RUNNING:
        raise HTTPException(status_code=409, detail="No backfill running")

    backfill_service.cancel()

    return {"status": "cancelled"}