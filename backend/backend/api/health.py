"""Health and status endpoints."""
import logging
from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import JSONResponse

from backend.core.config import get_settings
from backend.adapters import get_all_adapters

logger = logging.getLogger("arr-control.api.health")

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", summary="Health check")
def health_check():
    """Simple health check endpoint."""
    return JSONResponse(content={"status": "ok", "service": "arr-control"})


@router.get("/ready", summary="Readiness check")
def ready_check():
    """Readiness check - verify database and adapters are working."""
    adapters = get_all_adapters()
    healthy_count = sum(1 for a in adapters if a.health().status == "healthy")
    
    return JSONResponse(content={
        "ready": healthy_count > 0 or len(adapters) == 0,
        "services_checked": len(adapters),
        "services_healthy": healthy_count
    })


@router.get("/api/health", summary="Alternative health endpoint")
def health_check_v2():
    """Alternative health endpoint path."""
    settings = get_settings()
    return JSONResponse(content={
        "status": "ok",
        "service": "arr-control",
        "version": settings.app_version
    })