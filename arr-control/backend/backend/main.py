"""Main FastAPI application."""
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.health import router as health_router
from backend.api.items import router as items_router
from backend.api.events import router as events_router
from backend.api.services import router as services_router
from backend.api.webhooks import router as webhooks_router
from backend.api.backfill import router as backfill_router
from backend.api.activity import router as activity_router
from backend.database.base import Base, engine, init_db
from backend.core.config import get_settings
from backend.services.polling import PollingService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("arr-control")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    # Initialize database
    init_db()
    logger.info("Database initialized")
    
    # Start polling service
    settings = get_settings()
    app.state.polling_service = PollingService(poll_interval=settings.poll_interval_seconds)
    app.state.polling_service.start()
    logger.info("Polling service started")
    
    yield
    
    # Cleanup
    app.state.polling_service.stop()
    logger.info("Polling service stopped")


def create_application() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    
    app = FastAPI(
        title=settings.app_name,
        description="Media Automation Control Plane - Observability and correlation layer for ARR stack",
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc"
    )
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include routers
    app.include_router(health_router)
    app.include_router(items_router)
    app.include_router(events_router)
    app.include_router(services_router)
    app.include_router(webhooks_router)
    app.include_router(backfill_router)
    app.include_router(activity_router)
    
    return app


application = create_application()


def main() -> None:
    """Entry point for running the application."""
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "backend.main:application",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level="info"
    )


if __name__ == "__main__":
    main()